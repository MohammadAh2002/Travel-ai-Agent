const STORAGE_KEY = "rihla.conversations.v1";
const state = { session: null, pending: null, pendingCard: null, maps: [], guidedFlow: null };
const thread = document.querySelector("#chat-thread");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
let welcome = document.querySelector(".welcome");
const welcomeTemplate = welcome?.cloneNode(true);
const topStatus = document.querySelector("#top-status");
const statusText = document.querySelector("#status-text");
const voiceStatus = document.querySelector("#voice-status");
const mic = document.querySelector("#mic");
const conversationList = document.querySelector("#conversation-list");
const conversationsNav = document.querySelector("#chats-nav");
const alertsNav = document.querySelector("#alerts-nav");
const chatView = document.querySelector("#chat");
const watchView = document.querySelector("#watch-page");
const sidebar = document.querySelector("#sidebar");
const sidebarToggle = document.querySelector("#sidebar-toggle");
let conversations = loadConversations();
let activeConversation = null;
let recorder;
let chunks = [];
let cardSeq = 0;

function loadConversations() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(saved) ? saved.filter(item => item && item.id && item.session && Array.isArray(item.events)) : [];
  } catch {
    return [];
  }
}

function saveConversations() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, 40)));
  } catch {
    // Chat remains usable if browser storage is unavailable or full.
  }
}

function currentConversation() {
  return conversations.find(item => item.id === activeConversation);
}

function persistEvent(event, conversationId = activeConversation) {
  let conversation = conversations.find(item => item.id === conversationId);
  if (!conversation) {
    conversation = {
      id: conversationId || `chat-${crypto.randomUUID()}`,
      session: state.session || `web-${crypto.randomUUID().slice(0, 8)}`,
      title: "New chat",
      createdAt: Date.now(),
      updatedAt: Date.now(),
      events: [],
    };
    conversations.unshift(conversation);
    if (!activeConversation) activeConversation = conversation.id;
    if (!state.session) state.session = conversation.session;
  }
  conversation.events.push(event);
  conversation.updatedAt = Date.now();
  if (event.type === "message" && event.role === "user" && conversation.title === "New chat") {
    conversation.title = event.content.trim().replace(/\s+/g, " ").slice(0, 38) || "New chat";
  }
  conversations.sort((a, b) => b.updatedAt - a.updatedAt);
  saveConversations();
  renderConversationList();
}

function relativeDate(timestamp) {
  const days = Math.floor((Date.now() - timestamp) / 86400000);
  if (days < 1) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderConversationList() {
  conversationList.replaceChildren();
  conversations.filter(item => item.events.length).forEach(conversation => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `conversation-item${conversation.id === activeConversation ? " active" : ""}`;
    button.setAttribute("aria-current", conversation.id === activeConversation ? "page" : "false");
    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title;
    const date = document.createElement("span");
    date.className = "conversation-date";
    date.textContent = relativeDate(conversation.updatedAt);
    button.append(title, date);
    button.addEventListener("click", () => openConversation(conversation.id));
    conversationList.append(button);
  });
  const empty = document.createElement("p");
  empty.className = "history-empty";
  empty.textContent = "Your conversations will appear here.";
  empty.hidden = conversationList.childElementCount > 0;
  conversationList.append(empty);
}

function cloneWelcome() {
  return welcomeTemplate?.cloneNode(true) || null;
}

function openConversation(id) {
  const conversation = conversations.find(item => item.id === id);
  if (!conversation) return;
  activeConversation = id;
  state.session = conversation.session;
  state.pending = null;
  state.pendingCard = null;
  state.guidedFlow = null;
  state.maps.forEach(map => map.remove());
  state.maps = [];
  thread.replaceChildren();
  welcome = null;
  conversation.events.forEach(event => {
    if (event.type === "message") addMessage(event.role, event.content, false);
    if (event.type === "response") renderResponse(event.data);
  });
  if (!conversation.events.length) {
    welcome = cloneWelcome();
    if (welcome) thread.append(welcome);
  }
  if (conversation.guidedFlowType) {
    state.guidedFlow = { type: conversation.guidedFlowType, ...guidedFlows[conversation.guidedFlowType] };
    input.placeholder = state.guidedFlow.placeholder;
  } else {
    input.placeholder = "Tell me where you'd like to go, when, and who's coming...";
  }
  voiceStatus.textContent = "";
  setStatus("Ready when you are", false);
  showView("chat");
  renderConversationList();
  scrollThread();
}

function newConversation() {
  conversations = conversations.filter(item => item.events.length);
  activeConversation = `chat-${crypto.randomUUID()}`;
  state.session = `web-${crypto.randomUUID().slice(0, 8)}`;
  conversations.unshift({
    id: activeConversation,
    session: state.session,
    title: "New chat",
    createdAt: Date.now(),
    updatedAt: Date.now(),
    events: [],
  });
  state.pending = null;
  state.pendingCard = null;
  state.guidedFlow = null;
  state.maps.forEach(map => map.remove());
  state.maps = [];
  thread.replaceChildren();
  welcome = cloneWelcome();
  if (welcome) thread.append(welcome);
  input.value = "";
  input.placeholder = "Tell me where you'd like to go, when, and who's coming...";
  voiceStatus.textContent = "";
  setStatus("Ready when you are", false);
  showView("chat");
  renderConversationList();
}

function showView(view) {
  const isChat = view === "chat";
  chatView.hidden = !isChat;
  watchView.hidden = isChat;
  conversationsNav.classList.toggle("active", isChat);
  alertsNav.classList.toggle("active", !isChat);
  sidebar.classList.remove("open");
  sidebarToggle.setAttribute("aria-expanded", "false");
}

const guidedFlows = {
  trip: {
    prompt: "Let's plan it together. Where are you travelling from, and where would you like to go? If you can, include your dates (or number of days), who is travelling (adults and children's ages), and your total budget with currency. You can answer everything at once or just start with the route; I'll ask for anything missing.",
    prefix: "Plan a trip itinerary. Treat the traveller's message as trip details and ask for any essential information that is still missing:",
    placeholder: "Where from and where to? Add dates, travellers, and budget if you know them…",
  },
  day: {
    prompt: "Let's shape a great day. Which city and date should I plan for? Tell me who is coming (including children's ages), your walking style, and your budget. You can share whatever you know so far.",
    prefix: "Plan one travel day. Treat the traveller's message as day-plan details and ask for any essential information that is still missing:",
    placeholder: "City, date, travellers, and the kind of day you want…",
  },
  nearby: {
    prompt: "Share a Google Maps pin or link, or paste coordinates (latitude, longitude). Also tell me what you're looking for—food, sights, or something else—and how far you're happy to walk. You can share a map pin instead of your device location.",
    prefix: "Find nearby places. Treat the traveller's message as a nearby-search request. If there is no usable location, ask for a Google Maps pin, link, or coordinates:",
    placeholder: "Paste a Google Maps link or coordinates, plus what you want nearby…",
  },
  documents: {
    prompt: "I can help check travel-document guidance from official government sources. What is your passport nationality, destination, any transit countries, and your travel date?",
    prefix: "Answer a travel documents question using official sources only. Treat the traveller's message as their document question and ask for missing details:",
    placeholder: "Passport nationality, destination, transit, and travel date…",
  },
  checklist: {
    prompt: "Let's get you ready. Where are you travelling, when do you leave, and who is going? I'll tailor a practical checklist to your trip.",
    prefix: "Create a practical pre-trip checklist. Use the traveller's message as trip context and ask for useful missing details:",
    placeholder: "Destination, travel dates, and who's going…",
  },
  watch: {
    prompt: "I can watch for weather and currency updates (not flight or hotel prices). Which destination and dates should I monitor, and what currency is your trip budget in?",
    prefix: "Set up a weather and currency trip watch. Treat the traveller's message as watch details and ask for missing destination, dates, or currency:",
    placeholder: "Destination, dates, and budget currency…",
  },
};

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
function addMessage(role, content, persist = true) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  row.innerHTML = `<div class="avatar">${role === "assistant" ? "R" : "You"}</div><div class="bubble">${renderText(content)}</div>`;
  thread.append(row);
  scrollThread();
  if (persist) persistEvent({ type: "message", role, content: String(content) });
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
            <div class="activity-name">${escapeHTML(item.name)}${item.category ? ` <span class="activity-cat">${escapeHTML(item.category)}</span>` : ""}</div>
            ${item.description ? `<div class="activity-desc">${escapeHTML(item.description)}</div>` : ""}
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

function renderResponse(data) {
  document.querySelector("#thinking")?.remove();
  addMessage("assistant", data.reply || "I couldn't create a reply.", false);
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
function showResponse(data, conversationId = activeConversation) {
  persistEvent({ type: "response", data }, conversationId);
  if (activeConversation === conversationId) renderResponse(data);
}
async function sendMessage(text, requestText = text) {
  if (!text.trim()) return;
  welcome?.remove();
  welcome = null;
  addMessage("user", text);
  const conversationId = activeConversation;
  const sessionId = state.session;
  const sentFlow = state.guidedFlow;
  toggleThinking(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: requestText }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The travel assistant returned an error.");
    showResponse(data, conversationId);
    if (isGuidedFlowComplete(sentFlow, data)) {
      if (activeConversation === conversationId) finishGuidedFlow();
      else {
        const conversation = conversations.find(item => item.id === conversationId);
        if (conversation) conversation.guidedFlowType = null;
        saveConversations();
      }
    }
  } catch (error) {
    if (activeConversation === conversationId) {
      document.querySelector("#thinking")?.remove();
      addMessage("assistant", `I couldn't reach the trip planner: ${error.message}`);
    } else {
      persistEvent({ type: "message", role: "assistant", content: `I couldn't reach the trip planner: ${error.message}` }, conversationId);
    }
  } finally {
    if (activeConversation === conversationId) toggleThinking(false);
  }
}

function startGuidedFlow(type) {
  const flow = guidedFlows[type];
  if (!flow) return;
  welcome?.remove();
  welcome = null;
  state.guidedFlow = { type, ...flow };
  input.placeholder = flow.placeholder;
  addMessage("assistant", flow.prompt);
  const conversation = currentConversation();
  if (conversation) {
    conversation.guidedFlowType = type;
    saveConversations();
  }
  input.focus();
}

function isGuidedFlowComplete(flow, data) {
  if (!flow) return false;
  const agents = data.agents || [];
  if (flow.type === "trip" || flow.type === "day") {
    return Boolean(data.pending_action) || agents.some(agent => agent.name === "Itinerary Planner");
  }
  if (flow.type === "nearby") {
    return agents.some(agent => agent.name === "Nearby Guide") && (data.tool_calls || []).some(call => call.ok);
  }
  const completedAgents = {
    documents: "Documents Advisor",
    checklist: "Travel Prep Advisor",
    watch: "Trip Watch",
  };
  return agents.some(agent => agent.name === completedAgents[flow.type] && agent.status === "completed");
}

function finishGuidedFlow() {
  state.guidedFlow = null;
  const conversation = currentConversation();
  if (conversation) {
    conversation.guidedFlowType = null;
    saveConversations();
  }
  input.placeholder = "Tell me where you'd like to go, when, and who's coming...";
}

form.addEventListener("submit", event => {
  event.preventDefault();
  const text = input.value;
  input.value = "";
  input.style.height = "auto";
  const requestText = state.guidedFlow ? `${state.guidedFlow.prefix}\n${text}` : text;
  sendMessage(text, requestText);
});
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
});
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; });
thread.addEventListener("click", event => {
  const chip = event.target.closest(".chip");
  if (chip) startGuidedFlow(chip.dataset.flow);
});

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

document.querySelector("#new-chat").addEventListener("click", newConversation);
conversationsNav.addEventListener("click", () => showView("chat"));
alertsNav.addEventListener("click", () => showView("watch"));
sidebarToggle.addEventListener("click", () => {
  const open = sidebar.classList.toggle("open");
  sidebarToggle.setAttribute("aria-expanded", String(open));
});

const latestConversation = conversations.find(item => item.events.length);
if (latestConversation) openConversation(latestConversation.id);
else newConversation();
