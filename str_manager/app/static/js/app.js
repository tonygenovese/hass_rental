// ── State ──────────────────────────────────────────────────────────────────
let currentStatus = {};
let allAutomations = [];
let allNotifyServices = [];
let codeVisible = false;
let logCurrentPage = 1;
let logCurrentFilter = "all";
let logTotal = 0;

const LOG_ICONS = {
  checkin: "🏠", checkout: "🚪", first_entry: "🔑", cleaner_entry: "🧹",
  code_set: "🔐", code_cleared: "🔓", thermostat: "🌡️", notify: "🔔",
  info: "ℹ️", error: "⚠️",
};

// ── Tab routing ────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach(el => el.classList.toggle("hidden", el.id !== `tab-${name}`));
  if (name === "upcoming") loadReservations();
  if (name === "log") loadLog(1, logCurrentFilter);
  if (name === "settings") loadSettings();
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});
document.querySelectorAll(".tab-btn-link").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  const indicator = document.getElementById("ws-indicator");

  ws.onopen = () => { indicator.className = "w-2 h-2 rounded-full bg-green-500"; };
  ws.onclose = () => {
    indicator.className = "w-2 h-2 rounded-full bg-red-500";
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "status_update") renderStatus(msg.data);
    if (msg.type === "log_update") renderRecentLog(msg.data);
  };
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function loadDashboard() {
  const [status, logData] = await Promise.all([
    fetch("/api/status").then(r => r.json()),
    fetch("/api/activity-log?page=1&limit=5").then(r => r.json()),
  ]);
  renderStatus(status);
  renderRecentLog(logData.entries);
}

function renderStatus(data) {
  currentStatus = data;
  const card = document.getElementById("status-card");
  const label = document.getElementById("status-label");
  const icon = document.getElementById("status-icon");
  const activeCard = document.getElementById("active-card");
  const nextCard = document.getElementById("next-card");
  const noRes = document.getElementById("no-reservations-card");

  card.className = `rounded-xl p-5 border flex items-center gap-4 status-${data.state || "vacant"}`;
  label.textContent = (data.state || "vacant").toUpperCase().replace("_", " ");
  icon.textContent = { occupied: "✅", cleaner: "🧹", vacant: "🔓" }[data.state] || "🔓";

  if (data.current_guest) {
    activeCard.classList.remove("hidden");
    nextCard.classList.add("hidden");
    noRes.classList.add("hidden");
    document.getElementById("guest-name").textContent = data.current_guest;
    document.getElementById("checkin-time").textContent = formatDateTime(data.check_in);
    document.getElementById("checkout-time").textContent = formatDateTime(data.check_out);
    const codeEl = document.getElementById("guest-code");
    codeEl.dataset.real = data.guest_code || "——";
    codeEl.textContent = codeVisible ? (data.guest_code || "——") : "••••••";
  } else {
    activeCard.classList.add("hidden");
    if (data.next_guest) {
      nextCard.classList.remove("hidden");
      noRes.classList.add("hidden");
      document.getElementById("next-guest-name").textContent = data.next_guest;
      document.getElementById("next-checkin").textContent = formatDateTime(data.next_check_in);
    } else {
      nextCard.classList.add("hidden");
      noRes.classList.remove("hidden");
    }
  }

  const syncBadge = document.getElementById("sync-badge");
  const lastSync = document.getElementById("last-sync");
  if (data.last_sync) {
    syncBadge.classList.remove("hidden");
    lastSync.textContent = formatDateTime(data.last_sync);
  }
}

function renderRecentLog(entries) {
  const el = document.getElementById("recent-log");
  if (!entries || entries.length === 0) {
    el.innerHTML = '<li class="text-gray-500">No activity yet</li>';
    return;
  }
  el.innerHTML = entries.map(e => `
    <li class="log-entry">
      <span class="log-entry-icon">${LOG_ICONS[e.type] || "•"}</span>
      <div class="log-entry-content">
        <div class="log-entry-msg">${esc(e.message)}</div>
        <div class="log-entry-meta">${formatDateTime(e.timestamp)}${e.guest ? ` · ${esc(e.guest)}` : ""}</div>
      </div>
    </li>`).join("");
}

function toggleCode() {
  codeVisible = !codeVisible;
  const el = document.getElementById("guest-code");
  el.textContent = codeVisible ? (el.dataset.real || "——") : "••••••";
}

async function forceRefresh() {
  const spinner = document.getElementById("refresh-spinner");
  spinner.classList.remove("hidden");
  spinner.classList.add("spinning");
  await fetch("/api/refresh", { method: "POST" });
  setTimeout(() => { spinner.classList.add("hidden"); spinner.classList.remove("spinning"); }, 1500);
  setTimeout(loadDashboard, 2000);
}

// ── Upcoming Reservations ──────────────────────────────────────────────────
async function loadReservations() {
  const data = await fetch("/api/reservations").then(r => r.json());
  const el = document.getElementById("reservations-list");
  const syncEl = document.getElementById("res-sync-time");

  if (currentStatus.last_sync) syncEl.textContent = `Synced ${formatDateTime(currentStatus.last_sync)}`;

  if (!data || data.length === 0) {
    el.innerHTML = '<div class="text-gray-500 text-sm">No upcoming reservations found in calendar.</div>';
    return;
  }
  el.innerHTML = data.map(r => `
    <div class="res-card ${r.is_active ? "active-res" : ""}">
      <div class="flex items-start justify-between">
        <div>
          <div class="font-semibold ${r.is_active ? "text-green-400" : "text-gray-100"}">${esc(r.guest_name)}</div>
          <div class="text-xs text-gray-400 mt-0.5">${r.duration_nights} night${r.duration_nights !== 1 ? "s" : ""}</div>
        </div>
        ${r.is_active ? '<span class="text-xs bg-green-900 text-green-300 px-2 py-0.5 rounded-full font-medium">Active</span>' : ""}
      </div>
      <div class="grid grid-cols-2 gap-2 mt-3 text-sm">
        <div class="bg-gray-800 rounded-lg p-2">
          <div class="text-gray-400 text-xs mb-0.5">Check-in</div>
          <div>${formatDateTime(r.check_in)}</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-2">
          <div class="text-gray-400 text-xs mb-0.5">Check-out</div>
          <div>${formatDateTime(r.check_out)}</div>
        </div>
      </div>
    </div>`).join("");
}

// ── Activity Log ───────────────────────────────────────────────────────────
async function loadLog(page = 1, filter = "all") {
  logCurrentPage = page;
  logCurrentFilter = filter;
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.filter === filter));

  const data = await fetch(`/api/activity-log?page=${page}&limit=25&type=${filter}`).then(r => r.json());
  logTotal = data.total;
  const el = document.getElementById("log-list");

  if (!data.entries || data.entries.length === 0) {
    el.innerHTML = '<div class="text-gray-500">No entries found.</div>';
    document.getElementById("log-pagination").classList.add("hidden");
    return;
  }

  el.innerHTML = data.entries.map(e => `
    <div class="log-entry">
      <span class="log-entry-icon">${LOG_ICONS[e.type] || "•"}</span>
      <div class="log-entry-content">
        <div class="log-entry-msg">${esc(e.message)}</div>
        <div class="log-entry-meta">${formatDateTime(e.timestamp)}${e.guest ? ` · ${esc(e.guest)}` : ""} · ${esc(e.type)}</div>
      </div>
    </div>`).join("");

  const totalPages = Math.ceil(data.total / 25);
  const pag = document.getElementById("log-pagination");
  if (totalPages > 1) {
    pag.classList.remove("hidden");
    document.getElementById("log-page-info").textContent = `Page ${page} of ${totalPages} (${data.total} entries)`;
    document.getElementById("log-prev").disabled = page <= 1;
    document.getElementById("log-next").disabled = page >= totalPages;
  } else {
    pag.classList.add("hidden");
  }
}

function logPage(delta) { loadLog(logCurrentPage + delta, logCurrentFilter); }

document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => loadLog(1, btn.dataset.filter));
});

// ── Settings ───────────────────────────────────────────────────────────────
async function loadSettings() {
  const [cfg, lockEntities, climateEntities, automationEntities, notifyServices] = await Promise.all([
    fetch("/api/settings").then(r => r.json()),
    fetch("/api/ha/entities?domain=lock").then(r => r.json()),
    fetch("/api/ha/entities?domain=climate").then(r => r.json()),
    fetch("/api/ha/entities?domain=automation").then(r => r.json()),
    fetch("/api/ha/notify-services").then(r => r.json()),
  ]);

  allAutomations = automationEntities;

  // Populate simple inputs
  const fields = ["ical_url", "poll_interval_minutes", "default_checkin_time",
    "default_checkout_time", "guest_code_slot", "cleaner_code_slot",
    "cleaner_code", "guest_temp", "away_temp"];
  fields.forEach(f => {
    const el = document.getElementById(f);
    if (el) el.value = cfg[f] ?? "";
  });

  // Cleaner code placeholder
  if (cfg.cleaner_code === "••••") {
    document.getElementById("cleaner_code").placeholder = "Leave blank to keep existing";
    document.getElementById("cleaner_code").value = "";
  }

  // Lock — auto-select if only one exists and nothing saved yet
  const lockValue = cfg.lock_entity_id || (lockEntities.length === 1 ? lockEntities[0].entity_id : "");
  populateSelect("lock_entity_id", lockEntities, lockValue, "Select lock entity...");
  maybeShowAutoHint("lock_entity_id", lockEntities, lockValue, cfg.lock_entity_id);

  // Thermostat — auto-select if only one exists and nothing saved yet
  const climateValue = cfg.thermostat_entity_id || (climateEntities.length === 1 ? climateEntities[0].entity_id : "");
  populateSelect("thermostat_entity_id", climateEntities, climateValue, "None (disabled)");
  maybeShowAutoHint("thermostat_entity_id", climateEntities, climateValue, cfg.thermostat_entity_id);

  // Notify services (from /api/services, not /api/states)
  const notifyOptions = notifyServices.map(s => ({ entity_id: s.service, name: s.label }));
  const notifyValue = cfg.notify_service || (notifyOptions.length === 1 ? notifyOptions[0].entity_id : "");
  populateSelect("notify_service", notifyOptions, notifyValue, "Select notify service...");
  maybeShowAutoHint("notify_service", notifyOptions, notifyValue, cfg.notify_service);

  // Automations
  renderAutomationList("checkin", cfg.checkin_automation_ids || [], automationEntities);
  renderAutomationList("checkout", cfg.checkout_automation_ids || [], automationEntities);
}

function maybeShowAutoHint(fieldId, entities, selectedValue, savedValue) {
  // Show a subtle hint when we auto-selected the only available entity
  if (!savedValue && entities.length === 1 && selectedValue) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    const hint = document.createElement("p");
    hint.className = "text-xs text-blue-400 mt-1";
    hint.textContent = `Auto-selected — only one found. Save to confirm.`;
    el.parentNode.appendChild(hint);
  }
}

function populateSelect(id, entities, currentValue, placeholder) {
  const sel = document.getElementById(id);
  if (!sel) return;
  sel.innerHTML = `<option value="">${placeholder}</option>` +
    entities.map(e => `<option value="${e.entity_id}"${e.entity_id === currentValue ? " selected" : ""}>${e.name || e.entity_id}</option>`).join("");
}

function renderAutomationList(type, selected, entities) {
  const container = document.getElementById(`${type}_automations`);
  container.innerHTML = "";
  if (selected.length === 0) selected = [""];
  selected.forEach(val => container.appendChild(buildAutomationRow(type, val, entities)));
}

function buildAutomationRow(type, value, entities) {
  const div = document.createElement("div");
  div.className = "automation-row";
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">Select automation...</option>` +
    (entities || allAutomations).map(e =>
      `<option value="${e.entity_id}"${e.entity_id === value ? " selected" : ""}>${e.name || e.entity_id}</option>`
    ).join("");
  const rm = document.createElement("button");
  rm.type = "button";
  rm.textContent = "✕";
  rm.onclick = () => div.remove();
  div.appendChild(sel);
  div.appendChild(rm);
  return div;
}

function addAutomation(type) {
  const container = document.getElementById(`${type}_automations`);
  container.appendChild(buildAutomationRow(type, "", allAutomations));
}

async function saveSettings(e) {
  e.preventDefault();
  const form = document.getElementById("settings-form");
  const statusEl = document.getElementById("save-status");

  const data = {};
  ["ical_url", "cleaner_code"].forEach(f => data[f] = document.getElementById(f).value.trim());
  ["poll_interval_minutes", "guest_code_slot", "cleaner_code_slot", "guest_temp", "away_temp"].forEach(f =>
    data[f] = parseInt(document.getElementById(f).value, 10)
  );
  ["default_checkin_time", "default_checkout_time"].forEach(f =>
    data[f] = document.getElementById(f).value
  );
  data.lock_entity_id = document.getElementById("lock_entity_id").value;
  data.thermostat_entity_id = document.getElementById("thermostat_entity_id").value;
  data.notify_service = document.getElementById("notify_service").value;

  data.checkin_automation_ids = [...document.querySelectorAll("#checkin_automations select")]
    .map(s => s.value).filter(Boolean);
  data.checkout_automation_ids = [...document.querySelectorAll("#checkout_automations select")]
    .map(s => s.value).filter(Boolean);

  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  statusEl.classList.remove("hidden");
  if (resp.ok) {
    statusEl.textContent = "✅ Settings saved successfully.";
    statusEl.className = "text-sm text-center mb-2 text-green-400";
  } else {
    statusEl.textContent = "❌ Failed to save settings.";
    statusEl.className = "text-sm text-center mb-2 text-red-400";
  }
  setTimeout(() => statusEl.classList.add("hidden"), 3000);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

// ── Init ───────────────────────────────────────────────────────────────────
loadDashboard();
connectWS();
