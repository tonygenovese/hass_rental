// ── State ──────────────────────────────────────────────────────────────────
let currentStatus = {};
let allAutomations = [];
let allNotifyServices = [];
let codeVisible = false;
let logCurrentPage = 1;
let logCurrentFilter = "all";
let logTotal = 0;
let actionsOffset = 0;
const ACTIONS_LIMIT = 5;
let _lockData = [];
let _thermoData = [];
let _valveData = null;
const _tempDebounce = {};

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
  if (name === "log")      loadLog(1, logCurrentFilter);
  if (name === "actions")  loadActions();
  if (name === "devices")  loadDevices();
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
  const wsUrl = new URL("ws", location.href);
  wsUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(wsUrl.href);
  const dot = document.getElementById("ws-indicator");

  ws.onopen  = () => { dot.className = "ws-dot connected"; };
  ws.onclose = () => { dot.className = "ws-dot"; setTimeout(connectWS, 3000); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "status_update") renderStatus(msg.data);
    if (msg.type === "log_update")    renderRecentLog(msg.data);
  };
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function loadDashboard() {
  const [status, logData] = await Promise.all([
    fetch("api/status").then(r => r.json()),
    fetch("api/activity-log?page=1&limit=5").then(r => r.json()),
  ]);
  renderStatus(status);
  renderRecentLog(logData.entries);
}

function renderStatus(data) {
  currentStatus = data;
  document.getElementById("test-banner").classList.toggle("hidden", !data.test_mode);
  const card   = document.getElementById("status-card");
  const label  = document.getElementById("status-label");
  const icon   = document.getElementById("status-icon");
  const active = document.getElementById("active-card");
  const next   = document.getElementById("next-card");
  const noRes  = document.getElementById("no-reservations-card");

  const state = data.state || "vacant";
  card.className = `status-hero status-${state}`;
  label.textContent = state.toUpperCase().replace("_", " ");
  icon.textContent = { occupied: "✅", cleaner: "🧹", vacant: "🔓" }[state] || "🔓";

  if (data.current_guest) {
    active.classList.remove("hidden");
    next.classList.add("hidden");
    noRes.classList.add("hidden");
    document.getElementById("guest-name").textContent    = data.current_guest;
    document.getElementById("checkin-time").textContent  = formatDateTime(data.check_in);
    document.getElementById("checkout-time").textContent = formatDateTime(data.check_out);
    const codeEl = document.getElementById("guest-code");
    codeEl.dataset.real = data.guest_code || "——";
    codeEl.textContent  = codeVisible ? (data.guest_code || "——") : "••••••";
  } else {
    active.classList.add("hidden");
    if (data.next_guest) {
      next.classList.remove("hidden");
      noRes.classList.add("hidden");
      document.getElementById("next-guest-name").textContent = data.next_guest;
      document.getElementById("next-checkin").textContent    = formatDateTime(data.next_check_in);
    } else {
      next.classList.add("hidden");
      noRes.classList.remove("hidden");
    }
  }

  const syncBadge = document.getElementById("sync-badge");
  if (data.last_sync) {
    syncBadge.classList.remove("hidden");
    document.getElementById("last-sync").textContent = formatDateTime(data.last_sync);
  }
}

function renderRecentLog(entries) {
  const el = document.getElementById("recent-log");
  if (!entries || entries.length === 0) {
    el.innerHTML = '<li class="empty" style="padding:10px 0">No activity yet</li>';
    return;
  }
  el.innerHTML = entries.map(e => `
    <li class="log-entry">
      <div class="log-entry-icon">${LOG_ICONS[e.type] || "•"}</div>
      <div class="log-entry-body">
        <div class="log-entry-msg">${esc(e.message)}</div>
        <div class="log-entry-meta">${formatDateTime(e.timestamp)}${e.guest ? ` · ${esc(e.guest)}` : ""}</div>
      </div>
    </li>`).join("");
}

function toggleCode() {
  codeVisible = !codeVisible;
  const el = document.getElementById("guest-code");
  el.textContent = codeVisible ? (el.dataset.real || "——") : "••••••";
  document.querySelector(".reveal-btn").textContent = codeVisible ? "Hide" : "Reveal";
}

async function forceRefresh() {
  const spinner = document.getElementById("refresh-spinner");
  spinner.classList.add("spinning");
  await fetch("api/refresh", { method: "POST" });
  setTimeout(() => spinner.classList.remove("spinning"), 1500);
  setTimeout(loadDashboard, 2000);
}

// ── Upcoming Reservations ──────────────────────────────────────────────────
async function loadReservations() {
  const data = await fetch("api/reservations").then(r => r.json());
  const el   = document.getElementById("reservations-list");
  const sync = document.getElementById("res-sync-time");

  if (currentStatus.last_sync) sync.textContent = `Synced ${formatDateTime(currentStatus.last_sync)}`;

  if (!data || data.length === 0) {
    el.innerHTML = '<div class="empty">No upcoming reservations found in calendar.</div>';
    return;
  }
  el.innerHTML = data.map(r => `
    <div class="res-card ${r.is_active ? "active-res" : ""}" onclick='openResModal(${JSON.stringify(r).replace(/'/g, "&#39;")})'>
      <div class="res-top">
        <div>
          <div class="res-name">${esc(r.guest_name)}</div>
          <div class="res-meta">
            ${r.duration_nights} night${r.duration_nights !== 1 ? "s" : ""}
            ${r.phone_last4 ? `<span class="res-phone">· ···-${esc(r.phone_last4)}</span>` : ""}
          </div>
        </div>
        ${r.is_active ? '<span class="badge-active">Active</span>' : ""}
      </div>
      <div class="res-dates">
        <div class="res-date-cell">
          <div class="micro-label">Check-in</div>
          <div class="date-val">${formatDateTime(r.check_in)}</div>
        </div>
        <div class="res-date-cell">
          <div class="micro-label">Check-out</div>
          <div class="date-val">${formatDateTime(r.check_out)}</div>
        </div>
      </div>
    </div>`).join("");
}

// ── Activity Log ───────────────────────────────────────────────────────────
async function loadLog(page = 1, filter = "all") {
  logCurrentPage   = page;
  logCurrentFilter = filter;
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.filter === filter));

  const data = await fetch(`api/activity-log?page=${page}&limit=25&type=${filter}`).then(r => r.json());
  logTotal = data.total;
  const el = document.getElementById("log-list");

  if (!data.entries || data.entries.length === 0) {
    el.innerHTML = '<div class="empty">No entries found.</div>';
    document.getElementById("log-pagination").classList.add("hidden");
    return;
  }

  el.innerHTML = data.entries.map(e => `
    <div class="log-entry">
      <div class="log-entry-icon">${LOG_ICONS[e.type] || "•"}</div>
      <div class="log-entry-body">
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

// ── Reservation modal ──────────────────────────────────────────────────────
function openResModal(r) {
  const rows = [
    ["Guest",            esc(r.guest_name)],
    r.phone_last4   ? ["Phone",       `···-${esc(r.phone_last4)}`]       : null,
    r.email         ? ["Email",       esc(r.email)]                      : null,
    r.adults        ? ["Adults",      r.adults]                          : null,
    ["Check-in",         formatDateTime(r.check_in)],
    ["Check-out",        formatDateTime(r.check_out)],
    ["Duration",         `${r.duration_nights} night${r.duration_nights !== 1 ? "s" : ""}`],
    r.reservation_code ? ["Reservation Code", esc(r.reservation_code)]  : null,
    r.uid           ? ["UID",         esc(r.uid)]                        : null,
  ].filter(Boolean);

  document.getElementById("modal-body").innerHTML = rows.map(([label, val]) => `
    <div class="modal-row">
      <div class="modal-label">${label}</div>
      <div class="modal-value">${val}</div>
    </div>`).join("");
  document.getElementById("res-modal").classList.remove("hidden");
}

function closeResModal(e) {
  if (!e || e.target === document.getElementById("res-modal")) {
    document.getElementById("res-modal").classList.add("hidden");
  }
}

// ── Upcoming Actions ───────────────────────────────────────────────────────
async function loadActions(append = false) {
  if (!append) {
    actionsOffset = 0;
    document.getElementById("actions-list").innerHTML = '<div class="empty">Loading…</div>';
  }

  const data = await fetch(`api/upcoming-actions?limit=${ACTIONS_LIMIT}&offset=${actionsOffset}`).then(r => r.json());
  const el = document.getElementById("actions-list");
  const btn = document.getElementById("load-more-btn");

  if (!data.actions || data.actions.length === 0) {
    if (!append) {
      el.innerHTML = '<div class="empty">No upcoming actions.<br>Add an iCal URL in Settings to get started.</div>';
    }
    btn.classList.add("hidden");
    return;
  }

  const html = data.actions.map(a => {
    const guestLine = a.next_guest
      ? `${esc(a.guest)} <span class="action-guest-arrow">→</span> <span class="action-next-guest">${esc(a.next_guest)}</span>`
      : esc(a.guest);
    return `<div class="action-card">
      <div class="action-card-header">
        <div class="action-type-badge type-${a.type}">${actionTypeLabel(a.type)}</div>
        <div class="action-time">${formatDateTime(a.scheduled_at)}</div>
      </div>
      <div class="action-guest">${guestLine}</div>
      <ul class="action-steps">
        ${a.steps.map(s => `<li class="action-step"><span class="step-icon">${s.icon}</span>${esc(s.text)}</li>`).join("")}
      </ul>
    </div>`;
  }).join("");

  if (append) {
    el.insertAdjacentHTML("beforeend", html);
  } else {
    el.innerHTML = html;
  }

  actionsOffset += data.actions.length;
  btn.classList.toggle("hidden", actionsOffset >= data.total);
}

function loadMoreActions() { loadActions(true); }

function actionTypeLabel(type) {
  return { checkin: "Check-in", checkout: "Check-out", cleaner_start: "Checkout → Cleaner" }[type] || type;
}

// ── Inline time editing ────────────────────────────────────────────────────
function startEditTime(field) {
  const iso = field === "checkin" ? currentStatus.check_in : currentStatus.check_out;
  if (iso) {
    const d = new Date(iso);
    const offset = d.getTimezoneOffset() * 60000;
    document.getElementById(`${field}-input`).value =
      new Date(d.getTime() - offset).toISOString().slice(0, 16);
  }
  document.getElementById(`${field}-time`).classList.add("hidden");
  document.getElementById(`${field}-edit`).classList.remove("hidden");
}

function cancelEditTime(field) {
  document.getElementById(`${field}-time`).classList.remove("hidden");
  document.getElementById(`${field}-edit`).classList.add("hidden");
}

async function saveTime(field) {
  const val = document.getElementById(`${field}-input`).value;
  if (!val || !currentStatus.uid) return;

  const isoUtc = new Date(val).toISOString();
  const body = { uid: currentStatus.uid };
  if (field === "checkin")  body.check_in  = isoUtc;
  if (field === "checkout") body.check_out = isoUtc;

  await fetch("api/reservation-override", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (field === "checkin")  currentStatus.check_in  = isoUtc;
  if (field === "checkout") currentStatus.check_out = isoUtc;
  document.getElementById(`${field}-time`).textContent = formatDateTime(isoUtc);
  cancelEditTime(field);
}

// ── Devices tab ────────────────────────────────────────────────────────────
async function loadDevices() {
  document.getElementById("devices-locks").innerHTML = '<div class="empty">Loading…</div>';

  const data = await fetch("api/device-status").then(r => r.json());
  const mc = data.managed_codes || {};
  _lockData  = data.locks || [];
  _thermoData = data.thermostats || [];
  _valveData  = data.water_valve || null;

  // ── Locks ──
  const locksEl = document.getElementById("devices-locks");
  if (_lockData.length > 0) {
    locksEl.innerHTML = _lockData.map((lock, li) => {
      const st = (lock.state || "").toLowerCase();
      const stateClass = st === "locked" ? "state-locked" : st === "unlocked" ? "state-unlocked" : "state-unknown";
      const stateLabel = lock.state ? lock.state.charAt(0).toUpperCase() + lock.state.slice(1) : "Unknown";

      const highManaged = Math.max(mc.guest_slot || 0, mc.cleaner_slot || 0, 5);
      const slotsToShow = new Set();
      for (let i = 1; i <= highManaged; i++) slotsToShow.add(i);
      // Add any slot where Z-Wave reports occupied or a code (regardless of position)
      Object.entries(lock.code_slots || {}).forEach(([k, v]) => {
        if (v.occupied || v.code) slotsToShow.add(Number(k));
      });
      const sortedSlots = [...slotsToShow].sort((a, b) => a - b);

      const slotsHtml = sortedSlots.map(i => {
        const isGuest   = mc.guest_slot   === i;
        const isCleaner = mc.cleaner_slot === i;
        const managed   = isGuest || isCleaner;
        const slotData  = lock.code_slots?.[String(i)];

        let code, occupied;
        if (isGuest && mc.active_guest_code) {
          code = mc.active_guest_code; occupied = true;
        } else if (isCleaner && mc.cleaner_code) {
          code = mc.cleaner_code; occupied = true;
        } else if (slotData?.code) {
          code = slotData.code; occupied = true;
        } else if (slotData?.occupied) {
          code = "• • • •"; occupied = true;  // slot has a PIN but it's not in the Z-Wave JS cache
        } else {
          code = "—"; occupied = false;
        }

        const tag = isGuest   ? `<span class="slot-tag tag-guest">Guest</span>`
                  : isCleaner ? `<span class="slot-tag tag-cleaner">Cleaner</span>`
                  : occupied  ? `<span class="slot-tag tag-occupied">In use</span>`
                              : `<span class="slot-tag tag-empty">Empty</span>`;
        return `<div class="slot-row${managed ? " slot-managed" : ""}">
          <div class="slot-num">Slot ${i}</div>
          <div class="slot-code${occupied ? "" : " slot-code-empty"}">${esc(code)}</div>
          ${tag}
        </div>`;
      }).join("");

      return `<div class="device-card">
        <div class="device-card-head">
          <div class="device-name">${esc(lock.name)}</div>
          <div class="device-state-badge ${stateClass}">${stateLabel}</div>
        </div>
        ${lock.battery_level != null ? `<div class="device-battery">🔋 Battery: ${lock.battery_level}%</div>` : ""}
        <div class="slot-list">${slotsHtml}</div>
        <div class="device-controls">
          <button class="device-ctrl-btn" onclick="controlLock(${li},'unlock')">Unlock</button>
          <button class="device-ctrl-btn ctrl-primary" onclick="controlLock(${li},'lock')">Lock</button>
        </div>
      </div>`;
    }).join("");
  } else {
    locksEl.innerHTML = '<div class="empty">No locks configured.<br>Add lock entities in Settings.</div>';
  }

  // ── Thermostats ──
  const thermoSection = document.getElementById("devices-thermostat-section");
  const thermoEl      = document.getElementById("devices-thermostat");
  if (_thermoData.length > 0) {
    const modeLabel = m => m.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const actionClass = a => ({ heating: "state-heating", cooling: "state-cooling", idle: "state-idle", off: "state-unknown" })[a?.toLowerCase()] || "state-unknown";

    thermoEl.innerHTML = _thermoData.map((t, ti) => {
      const modes = (t.hvac_modes?.length ? t.hvac_modes : ["heat", "cool", "auto", "off"]);
      const target = t.target_temperature ?? "";
      const step   = t.temp_step || 1;
      const modesHtml = modes.map(m =>
        `<button class="mode-pill${t.state === m ? " mode-pill-active" : ""}" data-thermo-idx="${ti}" data-mode="${m}" onclick="setHvacMode(${ti},'${m}')">${modeLabel(m)}</button>`
      ).join("");

      return `<div class="device-card">
        <div class="device-card-head">
          <div class="device-name">${esc(t.name)}</div>
          <div class="device-state-badge ${actionClass(t.hvac_action)}">${esc(t.hvac_action || t.state || "—")}</div>
        </div>
        <div class="thermo-layout">
          <div>
            <div class="micro-label">Current</div>
            <div class="thermo-current">${t.current_temperature != null ? t.current_temperature + esc(t.unit) : "—"}</div>
          </div>
          <div class="thermo-stepper">
            <button class="stepper-btn" onclick="adjustTemp(${ti},${-step})">−</button>
            <span class="stepper-val" id="thermo-target-${ti}" data-temp="${target}">${target !== "" ? target + esc(t.unit) : "—"}</span>
            <button class="stepper-btn" onclick="adjustTemp(${ti},${step})">+</button>
          </div>
        </div>
        <div class="mode-pills">${modesHtml}</div>
      </div>`;
    }).join("");
    thermoSection.classList.remove("hidden");
  } else {
    thermoSection.classList.add("hidden");
  }

  // ── Water valve ──
  const valveSection = document.getElementById("devices-valve-section");
  const valveEl      = document.getElementById("devices-valve");
  if (_valveData) {
    const v = _valveData;
    const vs = (v.state || "").toLowerCase();
    const stateClass = (vs === "open" || vs === "on") ? "state-open"
                     : (vs === "closed" || vs === "off") ? "state-closed" : "state-unknown";
    const stateLabel = vs === "on" ? "Open" : vs === "off" ? "Closed"
                     : v.state ? v.state.charAt(0).toUpperCase() + v.state.slice(1) : "Unknown";
    const isOpen = vs === "open" || vs === "on";
    valveEl.innerHTML = `<div class="device-card">
      <div class="device-card-head">
        <div class="device-name">${esc(v.name)}</div>
        <div class="device-state-badge ${stateClass}">${stateLabel}</div>
      </div>
      <div class="device-controls">
        ${isOpen
          ? `<button class="device-ctrl-btn ctrl-danger" onclick="controlValve('close')">Close Valve</button>`
          : `<button class="device-ctrl-btn ctrl-primary" onclick="controlValve('open')">Open Valve</button>`
        }
      </div>
    </div>`;
    valveSection.classList.remove("hidden");
  } else {
    valveSection.classList.add("hidden");
  }
}

// ── Device controls ─────────────────────────────────────────────────────────
async function controlLock(idx, action) {
  const lock = _lockData[idx];
  if (!lock) return;
  const btn = event.currentTarget;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = action === "lock" ? "Locking…" : "Unlocking…";
  await fetch("api/device/lock", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_id: lock.entity_id, action }),
  });
  setTimeout(loadDevices, 1500);
}

async function adjustTemp(idx, delta) {
  const t = _thermoData[idx];
  if (!t) return;
  const el = document.getElementById(`thermo-target-${idx}`);
  const cur = parseFloat(el?.dataset.temp || t.target_temperature || 70);
  const min = t.min_temp ?? 40;
  const max = t.max_temp ?? 95;
  const newTemp = Math.min(max, Math.max(min, Math.round((cur + delta) * 10) / 10));
  if (el) { el.dataset.temp = newTemp; el.textContent = newTemp + (t.unit || "°F"); }
  clearTimeout(_tempDebounce[idx]);
  _tempDebounce[idx] = setTimeout(async () => {
    await fetch("api/device/thermostat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_id: t.entity_id, temperature: newTemp }),
    });
  }, 600);
}

async function setHvacMode(idx, mode) {
  const t = _thermoData[idx];
  if (!t) return;
  document.querySelectorAll(`.mode-pill[data-thermo-idx="${idx}"]`).forEach(btn => {
    btn.classList.toggle("mode-pill-active", btn.dataset.mode === mode);
  });
  await fetch("api/device/thermostat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_id: t.entity_id, hvac_mode: mode }),
  });
}

async function controlValve(action) {
  if (!_valveData) return;
  const btn = event.currentTarget;
  btn.disabled = true;
  btn.textContent = action === "open" ? "Opening…" : "Closing…";
  await fetch("api/device/valve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_id: _valveData.entity_id, action }),
  });
  setTimeout(loadDevices, 1500);
}

// ── Settings ───────────────────────────────────────────────────────────────
async function loadSettings() {
  const [cfg, lockEntities, automationEntities, notifyServices, climateEntities, valveEntities] = await Promise.all([
    fetch("api/settings").then(r => r.json()),
    fetch("api/ha/entities?domain=lock").then(r => r.json()),
    fetch("api/ha/entities?domain=automation").then(r => r.json()),
    fetch("api/ha/notify-services").then(r => r.json()),
    fetch("api/ha/entities?domain=climate").then(r => r.json()),
    fetch("api/ha/entities?domain=valve,switch").then(r => r.json()),
  ]);

  allAutomations = automationEntities;
  window._lockEntities = lockEntities;

  const fields = ["ical_url", "property_timezone", "poll_interval_minutes", "default_checkin_time",
    "default_checkout_time", "guest_code_slot", "cleaner_code_slot", "cleaner_code"];
  fields.forEach(f => { const el = document.getElementById(f); if (el) el.value = cfg[f] ?? ""; });

  if (cfg.cleaner_code === "••••") {
    document.getElementById("cleaner_code").placeholder = "Leave blank to keep existing";
    document.getElementById("cleaner_code").value = "";
  }

  // Multi-lock: migrate single lock_entity_id → lock_entity_ids
  const lockIds = cfg.lock_entity_ids?.length ? cfg.lock_entity_ids
    : (cfg.lock_entity_id ? [cfg.lock_entity_id] : []);
  renderLockList(lockIds, lockEntities);

  const notifyOptions = notifyServices.map(s => ({ entity_id: s.service, name: s.label }));
  const notifyValue = cfg.notify_service || (notifyOptions.length === 1 ? notifyOptions[0].entity_id : "");
  populateSelect("notify_service", notifyOptions, notifyValue, "Select notify service…");
  maybeShowAutoHint("notify_service", notifyOptions, notifyValue, cfg.notify_service);

  renderAutomationList("checkin",    cfg.checkin_automation_ids      || [], automationEntities);
  renderAutomationList("checkout",   cfg.checkout_automation_ids     || [], automationEntities);
  renderAutomationList("precheckin", cfg.pre_checkin_automation_ids  || [], automationEntities);

  window._climateEntities = climateEntities;
  const thermoIds = cfg.thermostat_entity_ids?.length ? cfg.thermostat_entity_ids
    : (cfg.thermostat_entity_id ? [cfg.thermostat_entity_id] : []);
  renderThermostatList(thermoIds, climateEntities);

  populateSelect("water_valve_entity_id", valveEntities, cfg.water_valve_entity_id || "", "None / not configured");

  // Notifications
  const notifs = cfg.notifications || {};
  const notifKeys = ["checkin", "checkout_vacant", "checkout_cleaner", "guest_arrived", "cleaner_arrived", "cleaner_left"];
  notifKeys.forEach(key => {
    const n = notifs[key] || {};
    const enabledEl = document.getElementById(`notif_${key}_enabled`);
    const titleEl   = document.getElementById(`notif_${key}_title`);
    const msgEl     = document.getElementById(`notif_${key}_message`);
    if (enabledEl) enabledEl.checked = n.enabled !== false;
    if (titleEl)   titleEl.value     = n.title   || "";
    if (msgEl)     msgEl.value       = n.message || "";
    updateNotifCard(key, n.enabled !== false);
  });
}

function renderThermostatList(selected, entities) {
  const container = document.getElementById("thermostat_entities");
  container.innerHTML = "";
  if (selected.length === 0) selected = [""];
  selected.forEach(val => container.appendChild(buildThermostatRow(val, entities)));
}

function buildThermostatRow(value, entities) {
  const div = document.createElement("div");
  div.className = "automation-row";
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">Select thermostat…</option>` +
    (entities || []).map(e =>
      `<option value="${e.entity_id}"${e.entity_id === value ? " selected" : ""}>${esc(e.name || e.entity_id)}</option>`
    ).join("");
  const rm = document.createElement("button");
  rm.type = "button"; rm.className = "auto-rm"; rm.textContent = "✕";
  rm.onclick = () => div.remove();
  div.appendChild(sel); div.appendChild(rm);
  return div;
}

function addThermostat() {
  document.getElementById("thermostat_entities").appendChild(buildThermostatRow("", window._climateEntities || []));
}

function renderLockList(selected, entities) {
  const container = document.getElementById("lock_entities");
  container.innerHTML = "";
  if (selected.length === 0) selected = [""];
  selected.forEach(val => container.appendChild(buildLockRow(val, entities)));
}

function buildLockRow(value, entities) {
  const div = document.createElement("div");
  div.className = "automation-row";
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">Select lock…</option>` +
    (entities || []).map(e =>
      `<option value="${e.entity_id}"${e.entity_id === value ? " selected" : ""}>${esc(e.name || e.entity_id)}</option>`
    ).join("");
  const rm = document.createElement("button");
  rm.type = "button"; rm.className = "auto-rm"; rm.textContent = "✕";
  rm.onclick = () => div.remove();
  div.appendChild(sel); div.appendChild(rm);
  return div;
}

function addLock() {
  document.getElementById("lock_entities").appendChild(buildLockRow("", window._lockEntities || []));
}

function maybeShowAutoHint(fieldId, entities, selectedValue, savedValue) {
  if (!savedValue && entities.length === 1 && selectedValue) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    const existing = el.closest(".field").querySelector(".hint-auto");
    if (existing) return;
    const hint = document.createElement("p");
    hint.className = "field-hint hint-auto";
    hint.textContent = "Auto-selected — only one found. Save to confirm.";
    el.closest(".field").appendChild(hint);
  }
}

function populateSelect(id, entities, currentValue, placeholder) {
  const sel = document.getElementById(id);
  if (!sel) return;
  const ids = new Set(entities.map(e => e.entity_id));
  const orphan = currentValue && !ids.has(currentValue)
    ? `<option value="${esc(currentValue)}" selected>${esc(currentValue)} (saved)</option>` : "";
  sel.innerHTML = `<option value="">${placeholder}</option>` + orphan +
    entities.map(e => `<option value="${e.entity_id}"${e.entity_id === currentValue ? " selected" : ""}>${esc(e.name || e.entity_id)}</option>`).join("");
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
  sel.innerHTML = `<option value="">Select automation…</option>` +
    (entities || allAutomations).map(e =>
      `<option value="${e.entity_id}"${e.entity_id === value ? " selected" : ""}>${esc(e.name || e.entity_id)}</option>`
    ).join("");
  const rm = document.createElement("button");
  rm.type = "button";
  rm.className = "auto-rm";
  rm.textContent = "✕";
  rm.onclick = () => div.remove();
  div.appendChild(sel);
  div.appendChild(rm);
  return div;
}

function addAutomation(type) {
  document.getElementById(`${type}_automations`).appendChild(buildAutomationRow(type, "", allAutomations));
}

async function saveSettings(e) {
  e.preventDefault();
  const statusEl = document.getElementById("save-status");

  const data = {};
  ["ical_url", "cleaner_code", "property_timezone"].forEach(f => { const el = document.getElementById(f); if (el) data[f] = el.value.trim(); });
  data.water_valve_entity_id = document.getElementById("water_valve_entity_id")?.value || "";
  ["poll_interval_minutes", "guest_code_slot", "cleaner_code_slot"].forEach(f =>
    data[f] = parseInt(document.getElementById(f).value, 10)
  );
  ["default_checkin_time", "default_checkout_time"].forEach(f =>
    data[f] = document.getElementById(f).value
  );
  data.lock_entity_ids             = [...document.querySelectorAll("#lock_entities select")].map(s => s.value).filter(Boolean);
  data.thermostat_entity_ids       = [...document.querySelectorAll("#thermostat_entities select")].map(s => s.value).filter(Boolean);
  data.notify_service              = document.getElementById("notify_service").value;
  data.checkin_automation_ids      = [...document.querySelectorAll("#checkin_automations select")].map(s => s.value).filter(Boolean);
  data.checkout_automation_ids     = [...document.querySelectorAll("#checkout_automations select")].map(s => s.value).filter(Boolean);
  data.pre_checkin_automation_ids  = [...document.querySelectorAll("#precheckin_automations select")].map(s => s.value).filter(Boolean);

  const notifKeys = ["checkin", "checkout_vacant", "checkout_cleaner", "guest_arrived", "cleaner_arrived", "cleaner_left"];
  data.notifications = {};
  notifKeys.forEach(key => {
    data.notifications[key] = {
      enabled: document.getElementById(`notif_${key}_enabled`)?.checked ?? true,
      title:   document.getElementById(`notif_${key}_title`)?.value   || "",
      message: document.getElementById(`notif_${key}_message`)?.value || "",
    };
  });

  const resp = await fetch("api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  statusEl.className = "save-msg";
  statusEl.classList.remove("hidden");
  if (resp.ok) {
    statusEl.textContent = "✅ Settings saved.";
    statusEl.classList.add("ok");
  } else {
    statusEl.textContent = "❌ Failed to save settings.";
    statusEl.classList.add("err");
  }
  setTimeout(() => statusEl.classList.add("hidden"), 3000);
}

async function reloadAddonStore() {
  const btn = document.querySelector(".btn-check-update");
  const orig = btn.textContent;
  btn.textContent = "Fetching from GitHub…";
  btn.disabled = true;
  try {
    const resp = await fetch("api/reload-store", { method: "POST" });
    const data = await resp.json();
    btn.textContent = data.ok ? "✓ Done — go to Add-on Info → Update" : "✗ Supervisor call failed";
  } catch {
    btn.textContent = "✗ Request failed";
  }
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 5000);
}

// ── Notification settings helpers ─────────────────────────────────────────
function updateNotifCard(key, enabled) {
  const el = document.getElementById(`notif-fields-${key}`);
  if (el) el.classList.toggle("dimmed", !enabled);
}

function insertVar(targetId, variable) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const start = el.selectionStart ?? el.value.length;
  const end   = el.selectionEnd   ?? el.value.length;
  el.value = el.value.slice(0, start) + variable + el.value.slice(end);
  el.selectionStart = el.selectionEnd = start + variable.length;
  el.focus();
}

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// ── Init ───────────────────────────────────────────────────────────────────
loadDashboard();
connectWS();
