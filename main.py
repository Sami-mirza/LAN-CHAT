

import sys
import os

_DEPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deps')
if os.path.isdir(_DEPS_DIR):
    sys.path.insert(0, _DEPS_DIR)

import socket
import argparse
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# ─── Data Stores ────────────────────────────────────────────────────────────
messages = []
users = {}             # IP -> {name, last_seen}
name_registry = {}     # name_lower -> IP
banned_names = set()
join_requests = {}     # IP -> {name, status, timestamp}
ADMIN_IP = None
ROOM_NAME = "LAN Chat"

# ─── HTML Frontend ──────────────────────────────────────────────────────────
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ room_name }} — LAN Chat</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            color: #eee;
            padding: 15px;
        }
        .container {
            width: 100%;
            max-width: 720px;
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            overflow: hidden;
            box-shadow: 0 25px 50px rgba(0,0,0,0.3);
            position: relative;
            display: flex;
            flex-direction: column;
            max-height: 95vh;
        }
        .header {
            background: linear-gradient(90deg, #0f3460, #533483);
            padding: 16px 20px;
            text-align: center;
            flex-shrink: 0;
        }
        .header h1 { font-size: 1.3rem; margin-bottom: 3px; }
        .header .status {
            font-size: 0.75rem;
            color: #a0d2eb;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }
        .status-dot {
            width: 7px; height: 7px;
            background: #4ecca3;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

        /* ─── Admin Bar ─── */
        .admin-bar {
            display: none;
            padding: 8px 16px;
            background: rgba(241, 196, 15, 0.08);
            border-bottom: 1px solid rgba(241, 196, 15, 0.12);
            font-size: 0.8rem;
            color: #f1c40f;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            flex-shrink: 0;
        }
        .admin-bar.show { display: flex; }
        .admin-bar .sep { color: rgba(241,196,15,0.3); }
        .admin-bar button, .admin-bar .toggle-btn {
            background: rgba(241, 196, 15, 0.12);
            border: 1px solid rgba(241, 196, 15, 0.25);
            color: #f1c40f;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.72rem;
            font-family: inherit;
        }
        .admin-bar button:hover, .admin-bar .toggle-btn:hover {
            background: rgba(241, 196, 15, 0.22);
        }
        .admin-bar .toggle-btn.active {
            background: rgba(241, 196, 15, 0.3);
            border-color: rgba(241, 196, 15, 0.5);
        }
        .badge {
            background: #ff6b6b;
            color: #fff;
            border-radius: 50%;
            width: 16px;
            height: 16px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.6rem;
            font-weight: 700;
            margin-left: 3px;
        }

        /* ─── Drawers (stack below admin bar, full width) ─── */
        .drawer {
            display: none;
            background: rgba(0,0,0,0.25);
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding: 10px 16px;
            max-height: 180px;
            overflow-y: auto;
            flex-shrink: 0;
        }
        .drawer.show { display: block; }
        .drawer h4 {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .drawer-pending h4 { color: #ff6b6b; }
        .drawer-online h4 { color: #4ecca3; }
        .drawer ul { list-style: none; }
        .drawer li {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            font-size: 0.82rem;
        }
        .drawer li:last-child { border-bottom: none; }
        .drawer .row-left {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .drawer .dot { color: #4ecca3; font-size: 0.5rem; }
        .drawer .admin-tag {
            background: linear-gradient(90deg, #f1c40f, #e67e22);
            color: #1a1a2e;
            font-size: 0.55rem;
            padding: 1px 4px;
            border-radius: 3px;
            font-weight: 700;
        }
        .drawer .btn-sm {
            padding: 3px 8px;
            border: none;
            border-radius: 4px;
            font-size: 0.65rem;
            cursor: pointer;
            font-weight: 600;
        }
        .btn-approve { background: #4ecca3; color: #1a1a2e; }
        .btn-reject  { background: #ff6b6b; color: #fff; }
        .btn-kick    { background: #ff6b6b; color: #fff; }
        .drawer .empty { color: #666; font-style: italic; font-size: 0.8rem; text-align: center; padding: 8px 0; }

        .info-bar {
            padding: 8px 16px;
            background: rgba(0,0,0,0.15);
            font-size: 0.72rem;
            color: #aaa;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }

        .chat-box {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            scroll-behavior: smooth;
            min-height: 200px;
        }
        .message {
            margin-bottom: 10px;
            animation: fadeIn 0.25s ease;
        }
        @keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        .msg-header {
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 2px;
        }
        .msg-user {
            font-weight: 600;
            font-size: 0.82rem;
        }
        .msg-time { font-size: 0.62rem; color: #888; }
        .msg-body {
            background: rgba(255,255,255,0.06);
            padding: 7px 11px;
            border-radius: 10px;
            border-left: 3px solid #533483;
            word-wrap: break-word;
            line-height: 1.4;
            font-size: 0.88rem;
        }
        .system-msg {
            text-align: center;
            color: #777;
            font-size: 0.75rem;
            font-style: italic;
            margin: 6px 0;
        }
        .empty-state {
            text-align: center;
            color: #555;
            padding: 50px 20px;
            font-size: 0.9rem;
        }

        .input-area {
            padding: 12px 16px;
            background: rgba(0,0,0,0.2);
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }
        .input-area input {
            flex: 1;
            padding: 9px 13px;
            border: none;
            border-radius: 9px;
            background: rgba(255,255,255,0.1);
            color: #fff;
            font-size: 0.88rem;
            outline: none;
        }
        .input-area input::placeholder { color: #888; }
        .input-area button {
            padding: 9px 18px;
            border: none;
            border-radius: 9px;
            background: linear-gradient(90deg, #533483, #0f3460);
            color: #fff;
            font-weight: 600;
            cursor: pointer;
            font-size: 0.82rem;
        }
        .input-area button:hover { opacity: 0.9; }
        .input-area button:disabled { opacity: 0.4; cursor: not-allowed; }

        /* ─── Overlays ─── */
        .overlay {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(22, 33, 62, 0.98);
            z-index: 100;
            display: none;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            padding: 30px;
        }
        .overlay.show { display: flex; }
        .overlay h2 {
            font-size: 1.5rem;
            margin-bottom: 8px;
            background: linear-gradient(90deg, #4ecca3, #a0d2eb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .overlay p {
            color: #888;
            margin-bottom: 18px;
            font-size: 0.88rem;
            max-width: 360px;
            line-height: 1.5;
        }
        .input-group {
            display: flex;
            gap: 8px;
            width: 100%;
            max-width: 360px;
        }
        .input-group input {
            flex: 1;
            padding: 11px 14px;
            border: 2px solid rgba(255,255,255,0.1);
            border-radius: 9px;
            background: rgba(255,255,255,0.05);
            color: #fff;
            font-size: 0.9rem;
            outline: none;
        }
        .input-group input:focus { border-color: #533483; }
        .input-group button {
            padding: 11px 20px;
            border: none;
            border-radius: 9px;
            background: linear-gradient(90deg, #533483, #0f3460);
            color: #fff;
            font-weight: 600;
            font-size: 0.85rem;
            cursor: pointer;
        }
        .input-group button:disabled { opacity: 0.5; cursor: not-allowed; }
        .error-text {
            color: #ff6b6b;
            margin-top: 8px;
            font-size: 0.82rem;
            min-height: 16px;
        }
        .avatar-preview {
            width: 65px;
            height: 65px;
            border-radius: 50%;
            background: linear-gradient(135deg, #533483, #0f3460);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.6rem;
            margin-bottom: 14px;
        }
        .spinner {
            width: 32px;
            height: 32px;
            border: 3px solid rgba(255,255,255,0.1);
            border-top-color: #4ecca3;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 14px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .rejected-icon { font-size: 2.2rem; margin-bottom: 8px; }

        @media (max-width: 500px) {
            .container { max-height: 100vh; border-radius: 0; }
            body { padding: 0; }
            .chat-box { min-height: 150px; }
            .header h1 { font-size: 1.1rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Overlays -->
        <div class="overlay" id="requestOverlay">
            <div class="avatar-preview" id="reqAvatar">👤</div>
            <h2>Request to Join</h2>
            <p>Enter your name to send a join request to the admin. You'll chat once approved.</p>
            <div class="input-group">
                <input type="text" id="reqName" placeholder="Your name" maxlength="20" autocomplete="off" autofocus>
                <button id="reqBtn" onclick="sendRequest()">Send</button>
            </div>
            <div class="error-text" id="reqError"></div>
        </div>
        <div class="overlay" id="waitingOverlay">
            <div class="spinner"></div>
            <h2>Waiting for Approval</h2>
            <p>Your request was sent to the admin.<br>You'll auto-enter once approved.</p>
        </div>
        <div class="overlay" id="rejectedOverlay">
            <div class="rejected-icon">❌</div>
            <h2>Request Rejected</h2>
            <p>Your join request was declined.<br>You can try a different name.</p>
            <div class="input-group" style="margin-top:12px;">
                <input type="text" id="retryName" placeholder="Try another name" maxlength="20" autocomplete="off">
                <button onclick="retryRequest()">Retry</button>
            </div>
            <div class="error-text" id="retryError"></div>
        </div>

        <div class="header">
            <h1>💬 {{ room_name }}</h1>
            <div class="status">
                <span class="status-dot"></span>
                <span>LAN Only — No Internet Required</span>
            </div>
        </div>

        <!-- Admin Bar -->
        <div class="admin-bar" id="adminBar">
            <span> Admin</span>
            <span class="sep">|</span>
            <button class="toggle-btn" id="btnPending" onclick="toggleDrawer('pending')">
                 Requests <span class="badge" id="badgePending" style="display:none;">0</span>
            </button>
            <button class="toggle-btn" id="btnOnline" onclick="toggleDrawer('online')">
                 Online <span class="badge" id="badgeOnline" style="display:none;">0</span>
            </button>
            <span class="sep">|</span>
            <button onclick="clearChat()"> Clear</button>
        </div>

        <!-- Pending Drawer -->
        <div class="drawer drawer-pending" id="drawerPending">
            <h4>⏳ Pending Join Requests</h4>
            <ul id="pendingList"></ul>
        </div>

        <!-- Online Drawer -->
        <div class="drawer drawer-online" id="drawerOnline">
            <h4>👥 Online Users</h4>
            <ul id="onlineList"></ul>
        </div>

        <div class="info-bar">
            <span id="conn-status">🟢 Connected</span>
            <span id="myNameDisplay" style="color:#4ecca3; font-weight:600;"></span>
        </div>

        <div class="chat-box" id="chatBox">
            <div class="empty-state">
                <p style="font-size:1.1rem; margin-bottom:6px;">👋</p>
                <p>No messages yet. Say something!</p>
            </div>
        </div>

        <div class="input-area">
            <input type="text" id="message" placeholder="Type a message..." maxlength="500" autocomplete="off">
            <button id="sendBtn" onclick="sendMessage()">Send</button>
        </div>
    </div>

    <script>
        const chatBox = document.getElementById('chatBox');
        const msgInput = document.getElementById('message');
        const reqNameInput = document.getElementById('reqName');
        const retryNameInput = document.getElementById('retryName');
        const requestOverlay = document.getElementById('requestOverlay');
        const waitingOverlay = document.getElementById('waitingOverlay');
        const rejectedOverlay = document.getElementById('rejectedOverlay');
        const reqBtn = document.getElementById('reqBtn');
        const reqError = document.getElementById('reqError');
        const retryError = document.getElementById('retryError');
        const adminBar = document.getElementById('adminBar');
        const drawerPending = document.getElementById('drawerPending');
        const drawerOnline = document.getElementById('drawerOnline');
        const btnPending = document.getElementById('btnPending');
        const btnOnline = document.getElementById('btnOnline');
        const badgePending = document.getElementById('badgePending');
        const badgeOnline = document.getElementById('badgeOnline');
        const sendBtn = document.getElementById('sendBtn');
        let lastCount = 0;
        let myName = localStorage.getItem('lan_chat_name') || '';
        let isAdmin = false;
        let inChat = false;
        let activeDrawer = null;

        reqNameInput.addEventListener('input', () => {
            const val = reqNameInput.value.trim();
            document.getElementById('reqAvatar').textContent = val ? val[0].toUpperCase() : '👤';
            reqError.textContent = '';
        });
        reqNameInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendRequest(); });
        retryNameInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') retryRequest(); });
        msgInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

        function toggleDrawer(which) {
            if (which === 'pending') {
                const show = !drawerPending.classList.contains('show');
                drawerPending.classList.toggle('show', show);
                drawerOnline.classList.remove('show');
                btnPending.classList.toggle('active', show);
                btnOnline.classList.remove('active');
                activeDrawer = show ? 'pending' : null;
            } else {
                const show = !drawerOnline.classList.contains('show');
                drawerOnline.classList.toggle('show', show);
                drawerPending.classList.remove('show');
                btnOnline.classList.toggle('active', show);
                btnPending.classList.remove('active');
                activeDrawer = show ? 'online' : null;
            }
        }

        async function checkStatus() {
            try {
                const res = await fetch('/check_status');
                const data = await res.json();
                if (data.status === 'admin') {
                    isAdmin = true;
                    myName = data.name || 'Admin';
                    localStorage.setItem('lan_chat_name', myName);
                    await doRegister(myName);
                    enterChat(myName);
                } else if (data.status === 'approved') {
                    const nameToUse = myName || data.name || '';
                    if (nameToUse) {
                        const ok = await doRegister(nameToUse);
                        if (ok) { myName = nameToUse; localStorage.setItem('lan_chat_name', myName); enterChat(myName); }
                        else requestOverlay.classList.add('show');
                    } else requestOverlay.classList.add('show');
                } else if (data.status === 'pending') {
                    waitingOverlay.classList.add('show');
                } else if (data.status === 'rejected') {
                    rejectedOverlay.classList.add('show');
                } else {
                    requestOverlay.classList.add('show');
                }
            } catch (e) {
                document.getElementById('conn-status').textContent = '🔴 Disconnected';
            }
        }

        async function doRegister(name) {
            try {
                const res = await fetch('/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                const data = await res.json();
                return data.ok === true;
            } catch (e) { return false; }
        }

        async function sendRequest() {
            const name = reqNameInput.value.trim();
            if (!name) { reqError.textContent = 'Enter a name.'; return; }
            if (name.length < 2) { reqError.textContent = 'Min 2 chars.'; return; }
            if (!/^[a-zA-Z0-9_\s]+$/.test(name)) { reqError.textContent = 'Letters, numbers, spaces, underscores only.'; return; }
            reqBtn.disabled = true; reqBtn.textContent = '...';
            try {
                const res = await fetch('/request_join', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                const data = await res.json();
                if (data.ok) {
                    requestOverlay.classList.remove('show');
                    waitingOverlay.classList.add('show');
                    myName = name; localStorage.setItem('lan_chat_name', name);
                } else {
                    reqError.textContent = data.reason || 'Failed.';
                    reqBtn.disabled = false; reqBtn.textContent = 'Send';
                }
            } catch (e) {
                reqError.textContent = 'Server error.';
                reqBtn.disabled = false; reqBtn.textContent = 'Send';
            }
        }

        async function retryRequest() {
            const name = retryNameInput.value.trim();
            if (!name) { retryError.textContent = 'Enter a name.'; return; }
            if (name.length < 2) { retryError.textContent = 'Min 2 chars.'; return; }
            if (!/^[a-zA-Z0-9_\s]+$/.test(name)) { retryError.textContent = 'Invalid chars.'; return; }
            try {
                const res = await fetch('/request_join', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                const data = await res.json();
                if (data.ok) {
                    rejectedOverlay.classList.remove('show');
                    waitingOverlay.classList.add('show');
                    myName = name; localStorage.setItem('lan_chat_name', name);
                } else { retryError.textContent = data.reason || 'Failed.'; }
            } catch (e) { retryError.textContent = 'Server error.'; }
        }

        function enterChat(name) {
            inChat = true;
            requestOverlay.classList.remove('show');
            waitingOverlay.classList.remove('show');
            rejectedOverlay.classList.remove('show');
            document.getElementById('myNameDisplay').textContent = 'You: ' + name;
            if (isAdmin) adminBar.classList.add('show');
            msgInput.focus();
            fetchMessages();
        }

        async function sendMessage() {
            const text = msgInput.value.trim();
            if (!text) return;
            sendBtn.disabled = true;
            try {
                const res = await fetch('/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text})
                });
                if (res.ok) { msgInput.value = ''; fetchMessages(); }
                else { const d = await res.json(); if (d.error) alert(d.error); }
            } catch (e) {} finally { sendBtn.disabled = false; msgInput.focus(); }
        }

        async function kickUser(targetName) {
            if (!isAdmin) return;
            if (!confirm('Kick "' + targetName + '"?')) return;
            try {
                await fetch('/kick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({target: targetName})
                });
                fetchMessages();
            } catch (e) {}
        }
        async function approveUser(name) {
            if (!isAdmin) return;
            try {
                await fetch('/approve', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                fetchAdminData();
            } catch (e) {}
        }
        async function rejectUser(name) {
            if (!isAdmin) return;
            try {
                await fetch('/reject', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                fetchAdminData();
            } catch (e) {}
        }
        async function clearChat() {
            if (!isAdmin) return;
            if (!confirm('Clear all messages?')) return;
            try { await fetch('/clear', {method: 'POST'}); lastCount = 0; fetchMessages(); }
            catch (e) {}
        }

        async function fetchMessages() {
            if (!inChat) return;
            try {
                const res = await fetch('/messages');
                const data = await res.json();
                renderMessages(data.messages);
                updateOnlineDrawer(data.online_users || []);
                document.getElementById('conn-status').textContent = '🟢 Connected';
            } catch (e) { document.getElementById('conn-status').textContent = '🔴 Disconnected'; }
        }
        async function fetchAdminData() {
            if (!isAdmin) return;
            try {
                const res = await fetch('/admin_data');
                const data = await res.json();
                updatePendingDrawer(data.pending || []);
            } catch (e) {}
        }

        function updatePendingDrawer(pending) {
            const list = document.getElementById('pendingList');
            if (pending.length === 0) {
                list.innerHTML = '<li class="empty">No pending requests</li>';
                badgePending.style.display = 'none';
            } else {
                badgePending.textContent = pending.length;
                badgePending.style.display = 'inline-flex';
                list.innerHTML = pending.map(p => `
                    <li>
                        <span class="row-left"><span class="dot">●</span>${escapeHtml(p.name)}</span>
                        <span>
                            <button class="btn-sm btn-approve" onclick="approveUser('${escapeHtml(p.name)}')">✓ Approve</button>
                            <button class="btn-sm btn-reject" onclick="rejectUser('${escapeHtml(p.name)}')">✗ Reject</button>
                        </span>
                    </li>
                `).join('');
            }
        }
        function updateOnlineDrawer(usersList) {
            const list = document.getElementById('onlineList');
            if (usersList.length === 0) {
                list.innerHTML = '<li class="empty">No users online</li>';
                badgeOnline.style.display = 'none';
            } else {
                badgeOnline.textContent = usersList.length;
                badgeOnline.style.display = 'inline-flex';
                list.innerHTML = usersList.map(u => {
                    const adminTag = u.is_admin ? '<span class="admin-tag">ADMIN</span>' : '';
                    const kickBtn = (isAdmin && !u.is_admin) ? `<button class="btn-sm btn-kick" onclick="kickUser('${escapeHtml(u.name)}')">Kick</button>` : '';
                    return `<li>
                        <span class="row-left"><span class="dot">●</span>${escapeHtml(u.name)}${adminTag}</span>
                        ${kickBtn}
                    </li>`;
                }).join('');
            }
        }

        function renderMessages(msgs) {
            if (msgs.length === 0) { chatBox.innerHTML = '<div class="empty-state"><p style="font-size:1.1rem;margin-bottom:6px;">👋</p><p>No messages yet. Say something!</p></div>'; lastCount = 0; return; }
            if (msgs.length === lastCount) return;
            lastCount = msgs.length;
            chatBox.innerHTML = '';
            msgs.forEach(m => {
                if (m.type === 'system') {
                    chatBox.innerHTML += `<div class="system-msg">${escapeHtml(m.text)}</div>`;
                } else {
                    const isMe = m.user === myName;
                    const color = isMe ? '#4ecca3' : stringToColor(m.user);
                    chatBox.innerHTML += `
                        <div class="message">
                            <div class="msg-header">
                                <span class="msg-user" style="color:${color}">${escapeHtml(m.user)}${isMe ? ' (You)' : ''}</span>
                                <span class="msg-time">${m.time}</span>
                            </div>
                            <div class="msg-body">${escapeHtml(m.text)}</div>
                        </div>`;
                }
            });
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        function stringToColor(str) {
            let hash = 0;
            for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
            return '#' + (hash & 0x00FFFFFF).toString(16).padStart(6, '0');
        }
        function escapeHtml(text) {
            const div = document.createElement('div'); div.textContent = text; return div.innerHTML;
        }

        checkStatus();
        setInterval(() => {
            if (!inChat) checkStatus();
            else fetchMessages();
            if (isAdmin) fetchAdminData();
        }, 2000);
    </script>
</body>
</html>
"""

# ─── Server Logic ───────────────────────────────────────────────────────────

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

def is_admin_ip(ip):
    return ip == ADMIN_IP or ip == "127.0.0.1"

def is_name_taken(name, exclude_ip=None):
    key = name.lower().strip()
    if key in name_registry:
        return name_registry[key] != exclude_ip
    for req_ip, req in join_requests.items():
        if req_ip != exclude_ip and req["status"] == "pending" and req["name"].lower() == key:
            return True
    return False

def add_system_message(text):
    messages.append({
        "user": "System",
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
        "type": "system"
    })
    if len(messages) > 200:
        messages.pop(0)

def remove_user(ip, reason=""):
    global users, name_registry
    if ip in users:
        name = users[ip]["name"]
        del users[ip]
        key = name.lower()
        if key in name_registry and name_registry[key] == ip:
            del name_registry[key]
        msg = f"{name} was removed"
        if reason: msg += f" ({reason})"
        msg += "."
        add_system_message(msg)
        return name
    return None

# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_PAGE, room_name=ROOM_NAME)

@app.route("/check_status")
def check_status():
    ip = get_client_ip()
    if is_admin_ip(ip):
        return jsonify({"status": "admin", "name": "Admin"})
    if ip in join_requests:
        req = join_requests[ip]
        return jsonify({"status": req["status"], "name": req["name"]})
    return jsonify({"status": "new"})

@app.route("/request_join", methods=["POST"])
def request_join():
    ip = get_client_ip()
    if is_admin_ip(ip):
        return jsonify({"ok": True})
    data = request.get_json()
    name = data.get("name", "").strip()[:20]
    if not name or len(name) < 2:
        return jsonify({"ok": False, "reason": "Name must be at least 2 characters."})
    if not all(c.isalnum() or c in ' _' for c in name):
        return jsonify({"ok": False, "reason": "Invalid characters."})
    if name.lower() in banned_names:
        return jsonify({"ok": False, "reason": f'"{name}" is banned.'})
    if is_name_taken(name, exclude_ip=ip):
        return jsonify({"ok": False, "reason": f'"{name}" is taken.'})
    if ip in join_requests and join_requests[ip]["status"] == "rejected":
        del join_requests[ip]
    join_requests[ip] = {"name": name, "status": "pending", "timestamp": datetime.now()}
    return jsonify({"ok": True})

@app.route("/register", methods=["POST"])
def register():
    ip = get_client_ip()
    data = request.get_json()
    name = data.get("name", "").strip()[:20]
    if not is_admin_ip(ip):
        if ip not in join_requests or join_requests[ip]["status"] != "approved":
            return jsonify({"ok": False, "reason": "Not approved yet."})
    if not name or len(name) < 2:
        return jsonify({"ok": False, "reason": "Name too short."})
    if not all(c.isalnum() or c in ' _' for c in name):
        return jsonify({"ok": False, "reason": "Invalid characters."})
    if is_name_taken(name, exclude_ip=ip):
        return jsonify({"ok": False, "reason": f'"{name}" is taken.'})
    if ip in users:
        old_name = users[ip]["name"]
        old_key = old_name.lower()
        if old_key in name_registry and name_registry[old_key] == ip:
            del name_registry[old_key]
        if old_name.lower() != name.lower():
            add_system_message(f"{old_name} changed to {name}.")
    else:
        suffix = " (Admin)" if is_admin_ip(ip) else ""
        add_system_message(f"{name}{suffix} joined.")
    users[ip] = {"name": name, "last_seen": datetime.now()}
    name_registry[name.lower()] = ip
    return jsonify({"ok": True, "is_admin": is_admin_ip(ip)})

@app.route("/messages")
def get_messages():
    ip = get_client_ip()
    if ip in users:
        users[ip]['last_seen'] = datetime.now()
    now = datetime.now()
    for user_ip in list(users.keys()):
        if (now - users[user_ip]['last_seen']).seconds > 300:
            remove_user(user_ip, "timed out")
    online_users = []
    for u_ip, info in users.items():
        online_users.append({"name": info['name'], "is_admin": is_admin_ip(u_ip)})
    return jsonify({"messages": messages, "online_users": online_users})

@app.route("/send", methods=["POST"])
def send_message():
    ip = get_client_ip()
    if ip not in users:
        return jsonify({"error": "Not registered. Please refresh and rejoin."}), 403
    data = request.get_json()
    text = data.get("text", "").strip()[:500]
    if not text:
        return jsonify({"error": "Empty message"}), 400
    messages.append({
        "user": users[ip]['name'], "text": text,
        "time": datetime.now().strftime("%H:%M"), "type": "chat"
    })
    if len(messages) > 200: messages.pop(0)
    return jsonify({"success": True})

@app.route("/admin_data")
def admin_data():
    ip = get_client_ip()
    if not is_admin_ip(ip):
        return jsonify({"error": "Admin only"}), 403
    pending = []
    for req_ip, req in join_requests.items():
        if req["status"] == "pending":
            pending.append({"name": req["name"], "ip": req_ip, "time": req["timestamp"].strftime("%H:%M")})
    return jsonify({"pending": pending})

@app.route("/approve", methods=["POST"])
def approve():
    ip = get_client_ip()
    if not is_admin_ip(ip): return jsonify({"error": "Admin only"}), 403
    data = request.get_json()
    target_name = data.get("name", "").strip().lower()
    target_ip = None
    for req_ip, req in join_requests.items():
        if req["status"] == "pending" and req["name"].lower() == target_name:
            target_ip = req_ip; break
    if not target_ip: return jsonify({"error": "Not found"}), 404
    join_requests[target_ip]["status"] = "approved"
    add_system_message(f"{join_requests[target_ip]['name']} was approved.")
    return jsonify({"success": True})

@app.route("/reject", methods=["POST"])
def reject():
    ip = get_client_ip()
    if not is_admin_ip(ip): return jsonify({"error": "Admin only"}), 403
    data = request.get_json()
    target_name = data.get("name", "").strip().lower()
    target_ip = None
    for req_ip, req in join_requests.items():
        if req["status"] == "pending" and req["name"].lower() == target_name:
            target_ip = req_ip; break
    if not target_ip: return jsonify({"error": "Not found"}), 404
    join_requests[target_ip]["status"] = "rejected"
    add_system_message(f"{join_requests[target_ip]['name']} was rejected.")
    return jsonify({"success": True})

@app.route("/kick", methods=["POST"])
def kick_user():
    ip = get_client_ip()
    if not is_admin_ip(ip): return jsonify({"error": "Admin only"}), 403
    data = request.get_json()
    target_name = data.get("target", "").strip().lower()
    target_ip = None
    for u_ip, info in users.items():
        if info['name'].lower() == target_name: target_ip = u_ip; break
    if not target_ip: return jsonify({"error": "User not found"}), 404
    if is_admin_ip(target_ip): return jsonify({"error": "Cannot kick admin"}), 403
    banned_names.add(target_name.lower())
    if target_ip in join_requests: join_requests[target_ip]["status"] = "rejected"
    remove_user(target_ip, "kicked by admin")
    return jsonify({"success": True})

@app.route("/clear", methods=["POST"])
def clear_chat():
    ip = get_client_ip()
    if not is_admin_ip(ip): return jsonify({"error": "Admin only"}), 403
    messages.clear()
    add_system_message("Chat cleared by admin.")
    return jsonify({"success": True})

# ─── Helpers ────────────────────────────────────────────────────────────────

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LAN Chat Server")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--room", type=str, default="LAN Chat")
    args = parser.parse_args()

    ROOM_NAME = args.room
    ADMIN_IP = get_local_ip()

    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 60)
    print("      💬  LAN CHAT SERVER — CLEAN UI  💬")
    print("=" * 60)
    print(f"  Room Name : {ROOM_NAME}")
    print(f"  Your IP   : {ADMIN_IP}")
    print(f"  Port      : {args.port}")
    print("-" * 60)
    print(f"  ➜  http://{ADMIN_IP}:{args.port}")
    print("-" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    messages.append({
        "user": "System",
        "text": f"Welcome to {ROOM_NAME}! New users need approval.",
        "time": datetime.now().strftime("%H:%M"),
        "type": "system"
    })

    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)