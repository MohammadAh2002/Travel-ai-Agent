"""Starter UI for the Trip Planner: a small Gradio CLIENT of the API contract.

It only talks to YOUR app (POST /api/chat, POST /api/approve). It never calls the travel API or an LLM.
Start your app on port 8000 first, then:   python ui/app_ui.py      ->  http://localhost:7860
Replace it with your own UI whenever you like.
"""
from __future__ import annotations

import os
import uuid

import gradio as gr
import httpx

APP = (os.getenv("APP_URL") or "http://localhost:8000").rstrip("/")
COLUMNS = ["day", "time", "place", "estimated cost", "source"]


def post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{APP}{path}", json=body, timeout=300)
        data = r.json()
        return data if isinstance(data, dict) else {"reply": str(data)}
    except Exception as exc:  # noqa: BLE001 - show the problem in the chat, do not crash the UI
        return {"reply": f"Could not reach your app at {APP} ({type(exc).__name__}). Is it running?"}


def itinerary_rows(resp: dict) -> list[list]:
    """Rows from pending_action.payload.itinerary (the Trip Store schema in the kit README)."""
    payload = (resp.get("pending_action") or {}).get("payload") or {}
    it = payload.get("itinerary")
    rows = []
    if isinstance(it, dict):
        currency = it.get("currency") or ""
        for day in it.get("days") or []:
            for a in day.get("activities") or []:
                when = "-".join(x for x in (a.get("start_time"), a.get("end_time")) if x)
                cost = a.get("estimated_cost")
                rows.append([day.get("date", ""), when, a.get("name", ""),
                             "" if cost is None else f"~{cost} {currency}".strip(), a.get("source_url") or ""])
        if it.get("estimated_total") is not None:
            rows.append(["", "", "Estimated total", f"~{it['estimated_total']} {currency}".strip(), ""])
    return rows


def details(resp: dict) -> str:
    lines = []
    if resp.get("result"):
        lines.append(f"**Saved:** `{resp['result']}`")
    pa = resp.get("pending_action")
    if pa:
        lines.append(f"**Waiting for your approval:** {pa.get('summary', '')}")
    if resp.get("state"):
        lines.append(f"State: `{resp['state']}`")
    for t in resp.get("tool_calls") or []:
        lines.append(f"- tool `{t.get('tool')}` {'ok' if t.get('ok') else 'FAILED'} ({t.get('ms', '?')} ms)")
    for c in resp.get("citations") or []:
        title = c.get("title") or c.get("id")
        lines.append(f"- source: [{title}]({c['url']})" if c.get("url") else f"- source: {title}")
    return "\n".join(lines) or "_No tool calls or sources in this reply._"


def show(history: list, resp: dict, state: dict):
    history = history + [{"role": "assistant", "content": resp.get("reply") or "(empty reply)"}]
    state = dict(state, pending=resp.get("pending_action"))
    rows = itinerary_rows(resp) or state.get("rows") or []
    state["rows"] = rows
    waiting = bool(state["pending"])
    return history, rows, details(resp), state, gr.update(interactive=waiting), gr.update(interactive=waiting)


def chat(message: str, history: list, state: dict, traveller: str):
    if not message.strip():
        return ("", history, state.get("rows") or [], "", state, gr.update(), gr.update())
    body = {"session_id": state["session"], "message": message}
    if traveller.strip():
        body["user"] = {"traveller_id": traveller.strip()}
    history = history + [{"role": "user", "content": message}]
    return ("",) + show(history, post("/api/chat", body), state)


def plan(dest, start, end, people, budget, currency, interests, traveller, history, state):
    message = (f"Plan a trip to {dest} from {start} to {end} for {int(people or 1)} traveller(s). "
               f"Total budget: {budget} {currency}. Interests: {interests}.")
    return chat(message, history, state, traveller)[1:]


def decide(approved: bool, history: list, state: dict):
    pa = state.get("pending")
    if not pa:
        return show(history, {"reply": "Nothing is waiting for approval."}, state)
    resp = post("/api/approve", {"session_id": state["session"], "action_id": pa.get("action_id"), "approved": approved})
    history = history + [{"role": "user", "content": "Approve" if approved else "Reject"}]
    return show(history, resp, state)


with gr.Blocks(title="Rihla trip planner") as demo:
    state = gr.State({"session": f"ui-{uuid.uuid4().hex[:8]}", "pending": None, "rows": []})
    gr.Markdown("## Rihla trip planner\nRihla is a fictional start-up; the travel data is real. "
                "Costs are **estimates**. Nothing is booked or bought.")
    with gr.Row():
        dest = gr.Textbox("Istanbul", label="Destination")
        start = gr.Textbox("2026-11-02", label="From (YYYY-MM-DD)")
        end = gr.Textbox("2026-11-04", label="To (YYYY-MM-DD)")
        people = gr.Number(1, label="Travellers", precision=0)
        budget = gr.Number(700, label="Total budget")
        currency = gr.Dropdown(["USD", "EUR", "TRY", "JOD"], value="USD", label="Currency")
    with gr.Row():
        interests = gr.Textbox("history, local food, nature", label="Interests", scale=3)
        traveller = gr.Textbox("", label="Traveller id (optional, e.g. TRV-101)")
        plan_btn = gr.Button("Plan my trip", variant="primary")
    chatbot = gr.Chatbot(label="Conversation", height=380)
    msg = gr.Textbox(label="Ask for changes", placeholder="Make day 2 cheaper / Cut the budget by 20% / ...")
    with gr.Row():
        approve = gr.Button("Approve and save", variant="primary", interactive=False)
        reject = gr.Button("Reject", variant="stop", interactive=False)
    table = gr.Dataframe(headers=COLUMNS, label="Proposed itinerary", interactive=False, wrap=True)
    info = gr.Markdown()
    outs = [chatbot, table, info, state, approve, reject]
    plan_btn.click(plan, [dest, start, end, people, budget, currency, interests, traveller, chatbot, state], outs)
    msg.submit(chat, [msg, chatbot, state, traveller], [msg] + outs)
    approve.click(lambda h, s: decide(True, h, s), [chatbot, state], outs)
    reject.click(lambda h, s: decide(False, h, s), [chatbot, state], outs)

if __name__ == "__main__":
    demo.launch()
