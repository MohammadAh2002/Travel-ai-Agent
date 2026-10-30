const state = { session: `web-${crypto.randomUUID().slice(0, 8)}`, pending: null, pendingCard: null, maps: [] };
const thread = document.querySelector("#chat-thread");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
let welcome = document.querySelector(".welcome");
const topStatus = document.querySelector("#top-status");
const statusText = document.querySelector("#status-text");
const voiceStatus = document.querySelector("#voice-status");
const mic = document.querySelector("#mic");
let recorder;
let chunks = [];
let cardSeq = 0;

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function renderText(value) {
  let safe = escapeHTML(value);
  safe = safe.replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1 ↗</a>');
  safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  safe = safe.split(/\n/).map(line => line.startsWith("- ") ? `• ${line.slice(2)}` : line).join("<br>");
  return safe;
}
function scrollThread() {
  thread.scrollTo({ top: thread.scrollHeight, behavior: "smooth" });
}
function addMessage(role, content) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  row.innerHTML = `<div class="avatar">${role === "assistant" ? "R" : "You"}</div><div class="bubble">${renderText(content)}</div>`;
  thread.append(row);
  scrollThread();
  return row;
}
function addMeta(html, isHTML = true) {
  const line = document.createElement("div");
  line.className = "meta-line";
  if (isHTML) line.innerHTML = html;
  else line.textContent = html;
  thread.append(line);
  scrollThread();
}
function setStatus(text, busy) {
  statusText.textContent = text;
  topStatus.classList.toggle("busy", Boolean(busy));
}
function toggleThinking(on) {
  setStatus(on ? "Crew is researching…" : state.pending ? "Plan ready to review" : "Ready when you are", on);
  document.querySelector("#thinking")?.remove();
  if (on) {
    const row = document.createElement("div");
    row.id = "thinking";
    row.className = "message assistant";
    row.innerHTML = '<div class="avatar">R</div><div class="bubble typing"><i></i><i></i><i></i></div>';
    thread.append(row);
    scrollThread();
  }
}

function dayLabel(dateValue) {
  return new Date(`${dateValue}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
function itineraryCard(itinerary) {
  const card = document.createElement("div");
  card.className = "trip-card";
  const travellers = itinerary.travellers ? `${itinerary.travellers} traveller${itinerary.travellers > 1 ? "s" : ""}` : "";
  const total = itinerary.estimated_total == null ? "Incomplete — some prices unlisted" : `~${escapeHTML(itinerary.estimated_total)} ${escapeHTML(itinerary.currency)}`;
  const days = (itinerary.days || []).map(day => `
    <div class="day-block">
      <div class="day-title">${escapeHTML(dayLabel(day.date))}</div>
      ${(day.activities || []).map(item => `
        <div class="activity">
          <div class="activity-time">${escapeHTML(item.start_time || "")}</div>
          <div>
            <div class="activity-name">${escapeHTML(item.name)}</div>
            <div class="activity-meta">${item.estimated_cost == null ? "Price not listed" : `~${escapeHTML(item.estimated_cost)} ${escapeHTML(itinerary.currency)}`}${item.travel_from_previous_min ? ` · ${escapeHTML(item.travel_from_previous_min)} min walk` : ""}${item.source_url ? ` · <a href="${escapeHTML(item.source_url)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ""}</div>
          </div>
        </div>`).join("")}
    </div>`).join("");
  card.innerHTML = `
    <div class="trip-card-head">
      <h3>${escapeHTML(itinerary.destination || "Your trip")} · ${(itinerary.days || []).length} day${(itinerary.days || []).length === 1 ? "" : "s"}</h3>
      <span class="sub">${[travellers, itinerary.budget_total != null ? `budget ~${escapeHTML(itinerary.budget_total)} ${escapeHTML(itinerary.currency)}` : ""].filter(Boolean).join(" · ")}</span>
    </div>
    ${days}
    <div class="trip-total"><span class="label">ESTIMATED TOTAL (LISTED COSTS)</span><span class="value">${total}</span></div>
    <div class="trip-map" hidden></div>
    <div class="trip-note">Costs are converted estimates from linked listings, not live quotes or bookings. Child pricing may differ.</div>`;
  renderMap(card, itinerary);
  return card;
}
function renderMap(card, itinerary) {
  const points = (itinerary.days || []).flatMap(day => (day.activities || [])
    .filter(item => Number.isFinite(item.lat) && Number.isFinite(item.lon))
    .map(item => ({ ...item, date: day.date })));
  if (!points.length || !window.L) return;
  const holder = card.querySelector(".trip-map");
  holder.hidden = false;
  const id = `trip-map-${++cardSeq}`;
  holder.id = id;
  requestAnimationFrame(() => {
    const map = L.map(id, { zoomControl: false }).setView([points[0].lat, points[0].lon], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
    const markers = points.map((point, index) => L.marker([point.lat, point.lon]).addTo(map)
      .bindPopup(`${index + 1}. ${escapeHTML(point.name)}<br>${escapeHTML(dayLabel(point.date))} · ${escapeHTML(point.start_time || "")}`));
    map.fitBounds(L.featureGroup(markers).getBounds().pad(.2));
    state.maps.push(map);
    setTimeout(() => map.invalidateSize(), 150);
  });
}

function approvalSection(pending) {
  const row = document.createElement("div");
  row.className = "approval";
  row.innerHTML = `
    <div class="summary">${escapeHTML(pending.summary || "Review this action before anything is saved.")}</div>
    <button class="reject" type="button">Not now</button>
    <button class="approve" type="button">Approve &amp; save →</button>`;
  row.querySelector(".approve").addEventListener("click", () => decide(true, row));
  row.querySelector(".reject").addEventListener("click", () => decide(false, row));
  return row;
}
function attachApproval(pending, itinerary) {
  if (state.pendingCard) {
    const old = state.pendingCard.querySelector(".approval");
    if (old) old.innerHTML = '<div class="decision rejected">Superseded by a newer proposal</div>';
  }
  const block = itinerary ? itineraryCard(itinerary) : (() => {
    const plain = document.createElement("div");
    plain.className = "trip-card";
    return plain;
  })();
  block.append(approvalSection(pending));
  thread.append(block);
  state.pendingCard = block;
  scrollThread();
}
async function decide(approved, row) {
  if (!state.pending) return;
  const action = state.pending;
  row.querySelectorAll("button").forEach(button => { button.disabled = true; });
  addMessage("user", approved ? "Approve and save" : "Not now");
  try {
    const response = await fetch("/api/approve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.session, action_id: action.action_id, approved }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not save the plan.");
    state.pending = null;
    state.pendingCard = null;
    row.innerHTML = `<div class="decision ${approved ? "saved" : "rejected"}">${approved ? `Saved${data.result?.trip_id ? ` as ${escapeHTML(data.result.trip_id)}` : ""} — nothing was booked or paid` : "Rejected — nothing was saved"}</div>`;
    setStatus("Ready when you are", false);
    if (data.reply) addMessage("assistant", data.reply);
  } catch (error) {
    row.querySelectorAll("button").forEach(button => { button.disabled = false; });
    addMessage("assistant", error.message);
  }
}

function showResponse(data) {
  document.querySelector("#thinking")?.remove();
  addMessage("assistant", data.reply || "I couldn't create a reply.");
  state.pending = data.pending_action || null;
  const itinerary = state.pending?.payload?.itinerary;
  if (state.pending) attachApproval(state.pending, itinerary?.days?.length ? itinerary : null);
  if (data.agents?.length) {
    const done = data.agents.filter(agent => agent.status === "completed").map(agent => agent.name);
    if (done.length) addMeta(`Crew: ${done.join(" · ")}`, false);
  }
  if (data.tool_calls?.length) {
    addMeta(`Research trail: ${data.tool_calls.map(tool => `${tool.ok ? "✓" : "!"} ${tool.tool}`).join(" · ")}`, false);
  }
  if (data.citations?.length) {
    addMeta(`Sources: ${data.citations.slice(0, 4).map(item => `<a target="_blank" rel="noopener noreferrer" href="${escapeHTML(item.url)}">${escapeHTML(item.title || item.id || "source")}</a>`).join(" · ")}`);
  }
}
async function sendMessage(text) {
  if (!text.trim()) return;
  welcome?.remove();
  welcome = null;
  addMessage("user", text);
  toggleThinking(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.session, message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The travel assistant returned an error.");
    showResponse(data);
  } catch (error) {
    document.querySelector("#thinking")?.remove();
    addMessage("assistant", `I couldn't reach the trip planner: ${error.message}`);
  } finally {
    toggleThinking(false);
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  const text = input.value;
  input.value = "";
  input.style.height = "auto";
  sendMessage(text);
});
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
});
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; });
document.querySelectorAll(".chip").forEach(chip => chip.addEventListener("click", () => sendMessage(chip.dataset.prompt)));

mic.addEventListener("click", async () => {
  if (recorder?.state === "recording") { recorder.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia) { voiceStatus.textContent = "Voice recording needs a secure browser context and microphone permission."; return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = async () => {
      mic.classList.remove("recording");
      stream.getTracks().forEach(track => track.stop());
      voiceStatus.textContent = "Transcribing your voice…";
      const audio = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const body = new FormData();
      body.append("session_id", state.session);
      body.append("audio", audio, "voice.webm");
      try {
        const response = await fetch("/api/voice", { method: "POST", body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Voice transcription is unavailable.");
        welcome?.remove();
        welcome = null;
        addMessage("user", data.transcript || "(voice message)");
        showResponse(data);
        voiceStatus.textContent = "";
      } catch (error) { voiceStatus.textContent = error.message; }
    };
    recorder.start();
    mic.classList.add("recording");
    voiceStatus.textContent = "Listening… click the microphone again to send.";
  } catch (error) { voiceStatus.textContent = `Microphone unavailable: ${error.message}`; }
});
