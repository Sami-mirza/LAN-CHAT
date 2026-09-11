/* ═══════════════════════════════════════════════════════════════════════
   LAN Chat — client
   Vanilla JS. State machine for the join/approve flow, SSE for live updates,
   DOM-safe rendering (user data only ever via textContent / createElement).
   ═══════════════════════════════════════════════════════════════════════ */

"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ─── tiny icon factory (static strings only — never user data) ──────── */
const ICONS = {
  chat: '<svg viewBox="0 0 24 24"><path d="M12 5.5c-3.9 0-7 2.47-7 5.7 0 1.76.9 3.36 2.37 4.42l-.5 2.38 2.62-1.32c.78.2 1.6.32 2.51.32 3.9 0 7-2.47 7-5.7S15.9 5.5 12 5.5z" fill="currentColor"/></svg>',
};

/* ─── theme ─────────────────────────────────────────────────────────── */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("lan_chat_theme", theme);
}
function initTheme() {
  const saved = localStorage.getItem("lan_chat_theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
}

/* ─── state ─────────────────────────────────────────────────────────── */
const state = {
  csrf: null,
  status: "new",            // new | pending | rejected | active
  isAdmin: false,
  name: "",
  room: "",
  pendingCount: 0,
  lastMsgId: 0,             // for pagination sliding window
  earliestId: 0,
  maybeMore: false,
  connected: false,
};

const els = {
  gate: $("#gate"),
  app: $("#app"),
  views: {
    join: $("#view-join"),
    pending: $("#view-pending"),
    rejected: $("#view-rejected"),
    signin: $("#view-signin"),
  },
  joinForm: $("#joinForm"), joinName: $("#joinName"), joinError: $("#joinError"),
  joinBtn: $("#joinBtn"), joinRoomTitle: $("#joinRoomTitle"),
  retryForm: $("#retryForm"), retryName: $("#retryName"), retryError: $("#retryError"),
  retryBtn: $("#retryBtn"), rejectedText: $("#rejectedText"),
  signinForm: $("#signinForm"), signinPassword: $("#signinPassword"),
  signinError: $("#signinError"), signinBtn: $("#signinBtn"),
  gotoSignin: $("#gotoSignin"), gotoJoin: $("#gotoJoin"),
  pendingWithdraw: $("#pendingWithdraw"), pendingGoSignin: $("#pendingGoSignin"),

  roomName: $("#roomName"), stageRoom: $("#stageRoom"),
  stageStatus: $("#stageStatus"), connDot: $("#connDot"),
  memberList: $("#memberList"), memberCount: $("#memberCount"),
  myAvatar: $("#myAvatar"), myName: $("#myName"), myRole: $("#myRole"),
  messages: $("#messages"), scroller: $("#scroller"),
  jumpWrap: $("#jumpWrap"), jumpBtn: $("#jumpBtn"),
  composer: $("#composer"), message: $("#message"), sendBtn: $("#sendBtn"),
  counter: $("#counter"),
  requestsBtn: $("#requestsBtn"), pendingBadge: $("#pendingBadge"),
  requestsSheet: $("#requestsSheet"), requestList: $("#requestList"),
  requestsEmpty: $("#requestsEmpty"), scrim: $("#scrim"),
  closeRequests: $("#closeRequests"),
  themeToggle: $("#themeToggle"), signOutBtn: $("#signOutBtn"),
  clearBtn: $("#clearBtn"),
  rail: $("#rail"), railToggle: $("#railToggle"), railClose: $("#railClose"),
  railScrim: $("#railScrim"),
  confirmDlg: $("#confirmDlg"), confirmOk: $("#confirmOk"),
  confirmCancel: $("#confirmCancel"), confirmTitle: $("#confirmTitle"),
  confirmText: $("#confirmText"),
  toasts: $("#toasts"),
  loadEarlierEl: null,
};

/* ─── toast ─────────────────────────────────────────────────────────── */
function toast(message, kind = "info") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  const ico = document.createElement("span");
  ico.className = "toast-ico";
  ico.textContent = kind === "ok" ? "✓" : kind === "err" ? "✕" : "ℹ";
  const text = document.createElement("span");
  text.textContent = message;                 // textContent = safe
  t.append(ico, text);
  els.toasts.appendChild(t);
  setTimeout(() => t.classList.add("out"), 3800);
  setTimeout(() => t.remove(), 4100);
}

/* ─── fetch helper with CSRF + error surfacing ──────────────────────── */
async function api(method, path, body) {
  const headers = { "X-CSRF": state.csrf || "" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}
function errText(data, fallback) {
  return (data && data.error) ? data.error : fallback;
}

/* ─── boot: resolve current state ───────────────────────────────────── */
async function boot() {
  const res = await fetch("/api/bootstrap");
  const b = await res.json();
  state.room = b.room;
  state.csrf = b.csrf || "";
  state.status = b.status;
  state.isAdmin = !!b.is_admin;
  state.name = b.name || "";
  state.pendingCount = b.pending_count || 0;
  renderShellTitle();
  if (b.status === "active") {
    enterApp(b);
    return;
  }
  showGateStatus(b.status, b.banned);
}

function renderShellTitle() {
  els.roomName.textContent = state.room;
  els.stageRoom.textContent = state.room;
  els.joinRoomTitle.textContent = `Join ${state.room}`;
  document.title = `${state.room} — LAN Chat`;
}

function showGateStatus(status, banned) {
  hideAllViews();
  if (status === "pending") {
    els.views.pending.hidden = false;
    pollWhilePending();
  } else if (status === "rejected") {
    els.rejectedText.textContent = banned
      ? "That name was removed from the room. You can rejoin with a different name."
      : "Your request wasn't approved. You can try again with a different name.";
    els.views.rejected.hidden = false;
  } else {
    els.views.join.hidden = false;
  }
}

function hideAllViews() {
  Object.values(els.views).forEach((v) => (v.hidden = true));
}

/* while waiting, poll bootstrap until approved or declined */
let pendingTimer = null;
function pollWhilePending() {
  clearInterval(pendingTimer);
  pendingTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/bootstrap");
      const b = await r.json();
      if (b.csrf) state.csrf = b.csrf;
      if (b.status === "active") {
        clearInterval(pendingTimer);
        enterApp(b);
      } else if (b.status === "rejected" || b.status === "new") {
        clearInterval(pendingTimer);
        showGateStatus(b.status, b.banned);
      }
    } catch (_) { /* transient — keep polling */ }
  }, 2500);
}

/* ─── join / retry / sign-in ────────────────────────────────────────── */
async function submitJoin(form, nameInput, btn, errEl) {
  const name = nameInput.value.trim();
  if (name.length < 2) {
    errEl.textContent = "Use at least 2 characters.";
    errEl.hidden = false;
    return;
  }
  btn.disabled = true;
  btn.textContent = "Sending…";
  const { ok, data } = await api("POST", "/api/request_join", { name });
  btn.disabled = false;
  btn.textContent = "Request to join";
  if (ok) {
    errEl.hidden = true;
    state.name = name;
    hideAllViews();
    els.views.pending.hidden = false;
    pollWhilePending();
  } else {
    errEl.textContent = errText(data, "Couldn't send request.");
    errEl.hidden = false;
  }
}

els.joinForm.addEventListener("submit", (e) => {
  e.preventDefault();
  submitJoin(els.joinForm, els.joinName, els.joinBtn, els.joinError);
});

els.retryForm.addEventListener("submit", (e) => {
  e.preventDefault();
  submitJoin(els.retryForm, els.retryName, els.retryBtn, els.retryError);
});

els.gotoSignin.addEventListener("click", () => {
  hideAllViews();
  els.views.signin.hidden = false;
  els.signinPassword.focus();
});
els.gotoJoin.addEventListener("click", () => {
  hideAllViews();
  els.views.join.hidden = false;
  els.joinName.focus();
});

els.pendingWithdraw.addEventListener("click", async () => {
  clearInterval(pendingTimer);
  const { ok, data } = await api("POST", "/api/cancel_join", {});
  if (!ok) {
    toast(errText(data, "Couldn't withdraw request."), "err");
    pollWhilePending();
    return;
  }
  showGateStatus("new");
});
els.pendingGoSignin.addEventListener("click", () => {
  clearInterval(pendingTimer);
  hideAllViews();
  els.views.signin.hidden = false;
  els.signinPassword.focus();
});

els.signinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = els.signinPassword.value;
  els.signinBtn.disabled = true;
  els.signinBtn.textContent = "Signing in…";
  els.signinError.hidden = true;
  const { ok, data } = await api("POST", "/api/admin_login", { password: pw });
  els.signinBtn.disabled = false;
  els.signinBtn.textContent = "Sign in";
  if (ok) {
    state.csrf = data.csrf || state.csrf;
    const b = await (await fetch("/api/bootstrap")).json();
    enterApp(b);
  } else {
    els.signinError.textContent = errText(data, "Incorrect password.");
    els.signinError.hidden = false;
  }
});

/* ─── enter the app ─────────────────────────────────────────────────── */
function enterApp(b) {
  state.csrf = b.csrf || state.csrf;
  state.status = "active";
  state.isAdmin = !!b.is_admin;
  state.name = b.name;
  state.room = b.room || state.room;
  clearInterval(pendingTimer);
  renderShellTitle();
  els.gate.hidden = true;
  els.app.hidden = false;
  els.myName.textContent = state.name;
  els.myRole.hidden = !state.isAdmin;
  els.myAvatar.textContent = initial(state.name);
  els.myAvatar.style.background = avatarColor(state.name);
  els.signOutBtn.hidden = false;
  els.requestsBtn.hidden = !state.isAdmin;
  els.clearBtn.hidden = !state.isAdmin;
  els.message.placeholder = `Message ${state.room}…`;
  setConnected(false);
  // Open SSE first (buffering) so messages that arrive during the history
  // fetch are not lost; flush the buffer once history is on screen.
  feedReady = false;
  streamBuffer = [];
  openStream();
  loadInitialMessages();
}

/* ─── messages: loading & rendering ───────────────────────────────────
   Ordering invariant: the feed is always strictly chronological.
   * live SSE arrival  → append (ids arrive ascending)
   * "load earlier"    → prepend in reverse
   Date dividers are inserted exactly when a message's day differs from the
   neighbouring message's day. All user data goes through textContent.   */
let seenIds = new Set();
let feedReady = false;
let streamBuffer = [];

function loadInitialMessages() {
  seenIds = new Set();
  return fetchMessages(0).finally(() => {
    feedReady = true;
    const buf = streamBuffer;
    streamBuffer = [];
    buf.forEach((m) => appendLive(m));
  });
}
async function fetchMessages(afterId) {
  const res = await fetch(`/api/messages?after=${afterId}&limit=100`);
  if (!res.ok) return;
  const data = await res.json();
  // Always paint history for the initial load (after=0), even if SSE already
  // delivered a live id into the buffer — those are flushed after reset.
  if (afterId === 0) resetFeedTo(data.messages, data.more_before);
  updatePendingFromData(data.pending);
  return data;
}

function resetFeedTo(msgs, moreBefore) {
  els.messages.innerHTML = "";
  state.lastMsgId = 0;
  state.earliestId = 0;
  state.maybeMore = !!moreBefore;
  if (msgs.length === 0) {
    renderEmpty();
    maybeShowLoadEarlier(false);
    return;
  }
  let lastDate = null;
  for (const m of msgs) {
    const d = dayKey(m.created_at);
    if (d !== lastDate) {
      els.messages.appendChild(dividerFor(null, d));
      lastDate = d;
    }
    els.messages.appendChild(nodeFor(m));
    seenIds.add(m.id);
    state.lastMsgId = Math.max(state.lastMsgId, Number(m.id));
    state.earliestId = state.earliestId === 0 ? Number(m.id) : Math.min(state.earliestId, Number(m.id));
  }
  maybeShowLoadEarlier(state.maybeMore);
  scrollToBottom(false);
}

function renderDay(key) {
  const now = new Date();
  if (key === dayKey(now.toISOString())) return "Today";
  const label = new Date(key + "T12:00:00");
  const yesterday = new Date(+now - 86400000);
  if (key === dayKey(yesterday.toISOString())) return "Yesterday";
  return label.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function renderEmpty() {
  els.messages.innerHTML = "";
  const box = document.createElement("div");
  box.className = "empty-chat";
  box.innerHTML = `<div class="empty-inner">
      <div class="empty-icon">${ICONS.chat}</div>
      <h2>No messages yet</h2><p>Say hello to the room.</p>
    </div>`;   // static template, no user data
  els.messages.appendChild(box);
}

/* append one live message (and a divider if its day just changed) */
function appendLive(m) {
  if (!feedReady) {
    streamBuffer.push(m);
    return;
  }
  if (seenIds.has(m.id)) return;
  seenIds.add(m.id);
  state.lastMsgId = Math.max(state.lastMsgId, Number(m.id));
  if (state.earliestId === 0) state.earliestId = Number(m.id);
  removeEmptyState();
  const prev = lastMessageNode();
  const needsDivider = !prev || dayKey(prev.dataset.day) !== dayKey(m.created_at);
  if (needsDivider) els.messages.appendChild(dividerFor(null, dayKey(m.created_at)));
  els.messages.appendChild(nodeFor(m));
  maybeAutoScroll();
}

function lastMessageNode() {
  const nodes = els.messages.childNodes;
  for (let i = nodes.length - 1; i >= 0; i--) {
    if (nodes[i] && nodes[i].dataset && nodes[i].dataset.id !== undefined) return nodes[i];
  }
  return null;
}

function prependEarlier(msgs) {
  if (msgs.length === 0) return;
  removeEmptyState();
  // Insert before the first real message so the "Load earlier" control stays on top.
  const first = firstMessageNode();
  const anchor = first;
  let nextDay = first ? first.dataset.day : null;
  for (const m of msgs) {
    if (seenIds.has(m.id)) continue;
    seenIds.add(m.id);
    state.earliestId = state.earliestId === 0
      ? Number(m.id)
      : Math.min(state.earliestId, Number(m.id));
    const d = dayKey(m.created_at);
    if (nextDay === null || nextDay !== d) {
      els.messages.insertBefore(dividerFor(null, d), anchor || null);
    }
    nextDay = d;
    els.messages.insertBefore(nodeFor(m), anchor || null);
  }
  if (els.loadEarlierEl) {
    els.messages.insertBefore(els.loadEarlierEl, els.messages.firstChild);
  }
}

/* ─── message node factory ──────────────────────────────────────────── */
function nodeFor(m) {
  const node = m.kind === "system" ? makeSystemNode(m) : makeChatNode(m);
  node.dataset.id = m.id;
  node.dataset.day = dayKey(m.created_at);
  return node;
}

function makeChatNode(m) {
  const wrap = document.createElement("div");
  wrap.className = "msg" + (m.user === state.name ? " msg-self" : "");
  const av = document.createElement("span");
  av.className = "avatar";
  av.textContent = initial(m.user);
  av.style.background = avatarColor(m.user);
  const body = document.createElement("div");
  body.className = "msg-body";
  const head = document.createElement("div");
  head.className = "msg-head";
  const author = document.createElement("span");
  author.className = "msg-author";
  author.textContent = m.user;
  author.style.color = m.user === state.name ? undefined : avatarColor(m.user);
  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = m.time;
  time.title = m.created_at;
  head.append(author, time);
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = m.text;               // textContent = safe
  body.append(head, bubble);
  wrap.append(av, body);
  return wrap;
}

function makeSystemNode(m) {
  const sys = document.createElement("div");
  sys.className = "sys";
  const txt = document.createElement("span");
  txt.className = "sys-text";
  txt.textContent = m.text;                  // textContent = safe
  sys.appendChild(txt);
  return sys;
}

function dividerFor(isoOrNull, prevDay) {
  const key = isoOrNull ? dayKey(isoOrNull) : prevDay;
  const d = document.createElement("div");
  d.className = "date-divider";
  d.dataset.day = key;
  d.textContent = renderDay(key);
  return d;
}

/* ─── presence ──────────────────────────────────────────────────────── */
function renderPresence(online, pendingCount) {
  els.memberList.innerHTML = "";
  els.memberCount.textContent = online.length;
  const sorted = [...online].sort((a, b) =>
    (b.is_admin ? 1 : 0) - (a.is_admin ? 1 : 0) ||
    a.name.localeCompare(b.name)
  );
  for (const u of sorted) {
    const li = document.createElement("li");
    li.className = "member" + (u.name === state.name ? " is-self" : "");
    const av = document.createElement("span");
    av.className = "avatar";
    av.textContent = initial(u.name);
    av.style.background = avatarColor(u.name);
    const nm = document.createElement("span");
    nm.className = "member-name";
    nm.textContent = u.name;                  // textContent = safe
    const dot = document.createElement("span");
    dot.className = "presence-dot on";
    li.append(av, nm, dot);
    if (u.is_admin) {
      const chip = document.createElement("span");
      chip.className = "role-chip";
      chip.textContent = "Mod";
      li.insertBefore(chip, dot);
    }
    if (state.isAdmin && !u.is_admin && u.name !== state.name) {
      const kick = document.createElement("button");
      kick.className = "icon-btn danger member-kick";
      kick.textContent = "✕";
      kick.title = `Remove ${u.name}`;
      kick.setAttribute("aria-label", `Remove ${u.name}`);
      kick.dataset.target = u.name;           // safe: value read from server, kept in dataset
      kick.addEventListener("click", () => confirmKick(u.name));
      li.insertBefore(kick, dot);
    }
    els.memberList.appendChild(li);
  }
  if (pendingCount != null && state.isAdmin) {
    state.pendingCount = pendingCount;
    updatePendingBadge();
  }
}

function updatePendingBadge() {
  els.pendingBadge.hidden = state.pendingCount === 0;
  els.pendingBadge.textContent = state.pendingCount;
  els.memberCount.classList.toggle("hot", state.pendingCount > 0);
}
function updatePendingFromData(pending) {
  if (!pending) return;
  renderRequestList(pending);
}

function renderRequestList(pending) {
  els.requestList.innerHTML = "";
  els.requestsEmpty.hidden = pending.length > 0;
  for (const r of pending) {
    const li = document.createElement("li");
    li.className = "request";
    const info = document.createElement("div");
    info.className = "request-info";
    const name = document.createElement("div");
    name.className = "request-name";
    name.textContent = r.name;                // textContent = safe
    const tm = document.createElement("div");
    tm.className = "request-time";
    tm.textContent = givenTime(r.requested_at);
    info.append(name, tm);
    const actions = document.createElement("div");
    actions.className = "request-actions";
    const approve = document.createElement("button");
    approve.className = "btn btn-primary btn-sm";
    approve.textContent = "Approve";
    approve.addEventListener("click", () => moderate("POST", "/api/approve", r.name, "✓ Approved"));
    const reject = document.createElement("button");
    reject.className = "btn btn-ghost btn-sm";
    reject.textContent = "Decline";
    reject.addEventListener("click", () => moderate("POST", "/api/reject", r.name, "Request declined"));
    actions.append(approve, reject);
    li.append(info, actions);
    els.requestList.appendChild(li);
  }
}

async function moderate(method, path, name, okMsg) {
  const { ok, data } = await api(method, path, { name });
  if (ok) {
    toast(okMsg, "ok");
    refreshModeration();
  } else {
    toast(errText(data, "Action failed"), "err");
  }
}

async function refreshModeration() {
  const res = await fetch("/api/messages?after=" + (state.lastMsgId || 0));
  if (res.ok) {
    const d = await res.json();
    updatePendingFromData(d.pending);
    state.pendingCount = d.pending ? d.pending.length : 0;
    updatePendingBadge();
  }
}

/* ─── SSE ───────────────────────────────────────────────────────────── */
let evtSource = null;
function openStream() {
  if (evtSource) { evtSource.close(); }
  evtSource = new EventSource("/api/stream");
  evtSource.addEventListener("messages", (e) => {
    const msgs = JSON.parse(e.data);
    msgs.forEach((m) => appendLive(m));
  });
  evtSource.addEventListener("presence", (e) => {
    const p = JSON.parse(e.data);
    renderPresence(p.online, p.pending);
    if (p.pending != null && state.isAdmin) {
      state.pendingCount = p.pending;
      updatePendingBadge();
    }
  });
  evtSource.addEventListener("cleared", () => {
    els.messages.innerHTML = "";
    seenIds = new Set();
    streamBuffer = [];
    state.lastMsgId = 0;
    state.earliestId = 0;
    renderEmpty();
    maybeShowLoadEarlier(false);
  });
  evtSource.addEventListener("denied", async () => {
    evtSource.close();
    feedReady = false;
    streamBuffer = [];
    els.app.hidden = true;
    els.gate.hidden = false;
    closeRail();
    try {
      const b = await (await fetch("/api/bootstrap")).json();
      state.csrf = b.csrf || state.csrf || "";
      state.status = "rejected";
      state.isAdmin = false;
      state.name = "";
    } catch (_) { /* keep prior csrf if bootstrap fails */ }
    showGateStatus("rejected", true);
    toast("You were removed from the room.", "err");
    els.message.value = "";
  });
  evtSource.onopen = () => setConnected(true);
  evtSource.onerror = () => setConnected(false);
}

function setConnected(connected) {
  state.connected = connected;
  els.connDot.classList.toggle("on", connected);
  els.stageStatus.textContent = connected
    ? "Connected · LAN only · no internet required"
    : "Reconnecting…";
}

/* ─── composing & sending ───────────────────────────────────────────── */
function autosize() {
  els.message.style.height = "auto";
  els.message.style.height = Math.min(els.message.scrollHeight, 160) + "px";
  if (els.message.value) {
    els.counter.textContent = `${els.message.value.length} / 1000`;
    els.counter.classList.toggle("warn", els.message.value.length > 900);
  } else {
    els.counter.textContent = "0 / 1000";
    els.counter.classList.remove("warn");
  }
  const canSend = els.message.value.trim().length > 0;
  els.sendBtn.disabled = !canSend;
}
els.message.addEventListener("input", autosize);
els.message.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); els.composer.requestSubmit(); }
});
els.composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = els.message.value.trim();
  if (!text) return;
  const { ok, data } = await api("POST", "/api/send", { text });
  if (ok) {
    els.message.value = "";
    autosize();
  } else if (data && data.error) {
    toast(data.error, "err");
  }
});

/* ─── moderator actions ─────────────────────────────────────────────── */
function confirmDialog(title, text) {
  return new Promise((resolve) => {
    els.confirmTitle.textContent = title;
    els.confirmText.textContent = text;
    els.confirmDlg.hidden = false;
    const done = (val) => {
      els.confirmDlg.hidden = true;
      els.confirmOk.removeEventListener("click", ok);
      els.confirmCancel.removeEventListener("click", cancel);
      resolve(val);
    };
    const ok = () => done(true);
    const cancel = () => done(false);
    els.confirmOk.addEventListener("click", ok);
    els.confirmCancel.addEventListener("click", cancel);
  });
}

async function confirmKick(name) {
  const yes = await confirmDialog(
    `Remove ${name}?`,
    `${name} will be disconnected and their name blocked from joining again.`
  );
  if (!yes) return;
  const { ok, data } = await api("POST", "/api/kick", { name });
  toast(ok ? `${name} was removed.` : errText(data, "Couldn't remove member."), ok ? "ok" : "err");
}

els.clearBtn.addEventListener("click", async () => {
  const yes = await confirmDialog(
    "Clear the room?",
    "Every message will be deleted. This can't be undone."
  );
  if (!yes) return;
  const { ok } = await api("POST", "/api/clear", {});
  if (ok) toast("Room cleared.", "ok");
});

els.signOutBtn.addEventListener("click", async () => {
  await api("POST", "/api/logout", {});
  evtSource && evtSource.close();
  location.reload();
});

/* requests sheet */
els.requestsBtn.addEventListener("click", () => {
  els.requestsSheet.hidden = false;
  els.scrim.hidden = false;
  refreshModeration();
});
els.closeRequests.addEventListener("click", closeSheet);
els.scrim.addEventListener("click", closeSheet);
function closeSheet() {
  els.requestsSheet.hidden = true;
  els.scrim.hidden = true;
}

/* theme + responsive rail */
els.themeToggle.addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  applyTheme(next);
});

function openRail() {
  els.rail.classList.add("open");
  els.railScrim.classList.add("open");
  els.railToggle.setAttribute("aria-expanded", "true");
}
function closeRail() {
  els.rail.classList.remove("open");
  els.railScrim.classList.remove("open");
  els.railToggle.setAttribute("aria-expanded", "false");
}
els.railToggle.addEventListener("click", () => {
  if (els.rail.classList.contains("open")) closeRail();
  else openRail();
});
els.railClose.addEventListener("click", closeRail);
els.railScrim.addEventListener("click", closeRail);

/* jump-to-bottom */
els.scroller.addEventListener("scroll", updateJumpVisibility, { passive: true });
els.jumpBtn.addEventListener("click", () => scrollToBottom(true));

/* ─── helpers: colors, dates, scroll ────────────────────────────────── */
function initial(name) { return (name.trim()[0] || "?").toUpperCase(); }

const PALETTE = [
  "#6366f1", "#0891b2", "#0d9488", "#059669", "#d97706",
  "#dc2626", "#db2777", "#7c3aed", "#2563eb", "#ea580c",
];
function hashOf(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function avatarColor(name) { return PALETTE[hashOf(name) % PALETTE.length]; }

function dayKey(iso) {
  if (!iso) return "";
  return iso.slice(0, 10);
}
function givenTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function scrollToBottom(smooth) {
  els.scroller.scrollTo({ top: els.scroller.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}
function isNearBottom() {
  return els.scroller.scrollHeight - els.scroller.scrollTop - els.scroller.clientHeight < 90;
}
function maybeAutoScroll() {
  if (isNearBottom()) scrollToBottom(false);
  updateJumpVisibility();
}
function updateJumpVisibility() {
  if (!els.jumpWrap) return;
  els.jumpWrap.classList.toggle("hidden", isNearBottom());
}
function removeEmptyState() {
  const e = els.messages.querySelector(".empty-chat");
  if (e) e.remove();
}
function firstMessageNode() {
  const nodes = els.messages.childNodes;
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i] && nodes[i].dataset && nodes[i].dataset.id !== undefined) return nodes[i];
  }
  return null;
}
function maybeShowLoadEarlier(show) {
  if (!show) {
    if (els.loadEarlierEl) { els.loadEarlierEl.remove(); els.loadEarlierEl = null; }
    return;
  }
  if (els.loadEarlierEl) return;
  els.loadEarlierEl = document.createElement("button");
  els.loadEarlierEl.className = "load-earlier";
  els.loadEarlierEl.textContent = "Load earlier messages";
  els.loadEarlierEl.addEventListener("click", loadEarlier);
  els.messages.insertBefore(els.loadEarlierEl, els.messages.firstChild);
}
async function loadEarlier() {
  if (!state.earliestId) return;
  const res = await fetch(`/api/messages?before=${state.earliestId}&limit=100`);
  if (!res.ok) return;
  const data = await res.json();
  const beforeScroll = els.scroller.scrollHeight;
  const firstBefore = state.earliestId;
  prependEarlier(data.messages);
  state.maybeMore = data.more_before;
  if (state.earliestId === firstBefore || !data.messages.length) state.maybeMore = false;
  maybeShowLoadEarlier(state.maybeMore);
  // preserve the user's scroll anchor
  els.scroller.scrollTop += els.scroller.scrollHeight - beforeScroll;
}

/* ─── start ─────────────────────────────────────────────────────────── */
initTheme();
boot().catch(() => {
  els.views.join.hidden = false;
  toast("Can't reach the server.", "err");
});