from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..chat.flow import chat_flow, response
from ..chat.itinerary import tool_call
from ..core import config
from ..core.models import ApproveRequest, ChatRequest
from ..features.voice import transcribe
from ..services import watches
from ..services.mcp_client import call_tool, connection
from ..services.memory import get_session, save_session

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(watches.background_loop(config.WATCH_INTERVAL_SECONDS))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Rihla Travel Crew", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rihla-trip-planner", "model": config.MODEL,
            "llm_configured": bool(config.OPENROUTER_API_KEY)}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty")
    return await chat_flow(req)


@app.post("/api/approve")
async def approve(req: ApproveRequest):
    state = get_session(req.session_id)
    action = state.pending_action
    if not action or action.get("action_id") != req.action_id:
        prior = state.completed_actions.get(req.action_id)
        if prior:
            return response(prior["reply"], state=state.model_dump(), result=prior["result"],
                            citations=state.last_sources)
        raise HTTPException(status_code=409, detail="No matching pending action. It may have expired or been replaced.")
    if not req.approved:
        state.pending_action = None
        reply = "Rejected. Nothing was saved, booked, reserved, or paid."
        state.history.append({"role": "assistant", "content": reply})
        save_session(state)
        return response(reply, state=state.model_dump(), result=None)
    try:
        async with connection() as mcp:
            if action.get("type") == "save_preferences":
                result = await call_tool(mcp, "save_preferences", action["payload"])
                result_id = "preferences updated"
                tool = "save_preferences"
            else:
                result = await call_tool(mcp, "save_trip", {
                    **action["payload"], "idempotency_key": action["action_id"],
                })
                result_id = result.get("trip_id")
                tool = "save_trip"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not save the approved plan: {type(exc).__name__}") from exc
    state.pending_action = None
    reply = (f"Saved as {result_id}. Nothing was booked, reserved, or paid."
             if tool == "save_trip" else "Your preferences are saved for future trip planning.")
    state.history.append({"role": "assistant", "content": reply})
    result_data = {"trip_id": result_id} if tool == "save_trip" else {"preferences_saved": True}
    state.completed_actions[req.action_id] = {"reply": reply, "result": result_data}
    save_session(state)
    return response(reply, state=state.model_dump(), result=result_data,
                    tool_calls=[tool_call(tool, True, "Approval Gate")], citations=state.last_sources)


@app.post("/api/voice")
async def voice(session_id: str = Form(...), audio: UploadFile = File(...),
                traveller_id: str | None = Form(None)):
    payload = await audio.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file must be under 20 MB.")
    try:
        text = await asyncio.to_thread(transcribe, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The audio could not be decoded. Try recording again.") from exc
    if not text:
        raise HTTPException(status_code=422, detail="No speech was detected.")
    user = {"traveller_id": traveller_id} if traveller_id else None
    result = await chat_flow(ChatRequest(session_id=session_id, message=text, user=user))
    result["transcript"] = text
    return result


@app.post("/api/watch")
async def create_watch(data: dict):
    if not data.get("session_id"):
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        watch = watches.add_watch(data)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        await watches.refresh(watch)
    except Exception:
        pass
    return watch


@app.get("/api/watch/{session_id}")
async def get_watches(session_id: str):
    return {"watches": [item for item in watches.WATCHES.values() if item["session_id"] == session_id]}


@app.delete("/api/watch/{watch_id}")
async def delete_watch(watch_id: str):
    watch = watches.WATCHES.pop(watch_id, None)
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    return {"deleted": watch_id}
