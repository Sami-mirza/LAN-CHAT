"""HTTP routes + real-time push for LAN Chat.

Security model (replaces the original "trust this IP is the admin" design):
  * Identity is a signed, httpOnly cookie holding a random session id (sid);
    nothing security-sensitive is ever keyed on IP or X-Forwarded-For.
  * Every mutating endpoint requires a CSRF token matched to that sid.
  * Moderator privileges require logging in with the server's admin password.
  * Only server-generated rows may have kind == "system"; client-submitted
    messages are forced to kind == "chat".
  * All names/text are escaped on the client with DOM textContent (no
    innerHTML interpolation of user data anywhere).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from typing import List, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from config import Config
from db import DB

SID_COOKIE = "lan_chat_sid"
MAX_TEXT_LENGTH = 1000

# ─── module state (initialised by init_routes) ────────────────────────────
_app: Flask | None = None
_cfg: Config | None = None
_db: Optional[DB] = None
_admin_password_hash: Optional[bytes] = None

_notifier = threading.Condition()
_broadcast_seq = 0
_cleared_epoch = 0

# per-sid send throttling
_rate_lock = threading.Lock()
_last_send: dict[str, float] = {}


# ─── helpers ───────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_hex(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().encode("ascii")


def verify_admin_password(candidate: str) -> bool:
    if not _admin_password_hash:
        return False
    return hmac.compare_digest(sha256_hex(candidate), _admin_password_hash)


def broadcast(kind: str = "message") -> None:
    """Wake every SSE connection; call after any state mutation that must reach clients."""
    global _broadcast_seq
    with _notifier:
        _broadcast_seq += 1
        if kind == "clear":
            global _cleared_epoch
            _cleared_epoch += 1
        _notifier.notify_all()


def _mint_sid() -> str:
    sid = secrets.token_hex(24)
    _db.create_session(sid, secrets.token_hex(24))
    return sid


def _fresh_sid() -> str:
    """Return the request's effective sid, minting a valid one if the browser's
    cookie is missing or no longer known to the database (e.g. DB was wiped).
    The caller re-issues the cookie via _cookie_reply only when it differs."""
    sid = request.cookies.get(SID_COOKIE)
    if sid and _db and _db.exists_any_session(sid):
        return sid
    sid = secrets.token_hex(24)
    _db.create_session(sid, secrets.token_hex(24))
    return sid


def _cookie_reply(sid: str, payload: dict, status: int = 200) -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    if request.cookies.get(SID_COOKIE) != sid:
        resp.set_cookie(
            SID_COOKIE, sid, max_age=60 * 60 * 24 * 365, httponly=True, samesite="Lax"
        )
    return resp


def _require_csrf(sid: str) -> bool:
    sent = request.headers.get("X-CSRF", "")
    expected = _db.csrf_for(sid) if _db else None
    return bool(expected and hmac.compare_digest(sent, expected))


def _active_user(sid: str) -> Optional[dict]:
    return _db.get_user(sid) if _db else None


def _public_user_row(row: dict) -> dict:
    return {"name": row["name"], "is_admin": bool(row["is_admin"])}


def _serialize_message(row: dict) -> dict:
    return {
        "id": row["id"],
        "user": row["user"],
        "text": row["text"],
        "kind": row["kind"],
        "time": row["time"],
        "created_at": row["created_at"],
    }


def _broadcast_presence() -> None:
    broadcast("presence")


# ─── JSON-safe early_mut check ──────────────────────────────────────────────
def _is_json_object() -> Optional[dict]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# ─── routes ────────────────────────────────────────────────────────────────
def init_routes(app: Flask, cfg: Config) -> None:
    global _app, _cfg, _db, _admin_password_hash
    _app, _cfg, _db = app, cfg, cfg.db
    _admin_password_hash = sha256_hex(cfg.admin_password)
    app.secret_key = secrets.token_hex(32)
    app.config["RATE_LIMIT_SECONDS"] = cfg.rate_limit_seconds

    # ── page ────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        # index.html is a plain static shell; serve it straight from templates/
        return send_from_directory(app.template_folder, "index.html")

    # ── bootstrap: current client state + csrf (called on every load) ─────
    @app.get("/api/bootstrap")
    def api_bootstrap():
        sid = request.cookies.get(SID_COOKIE)
        if not sid or not _db.exists_any_session(sid):
            # First visit: mint a session now so every client has a working
            # CSRF token before it ever POSTs anything.
            sid = _mint_sid()
            resp = jsonify({
                "status": "new",
                "csrf": _db.csrf_for(sid),
                "room": _cfg.room_name,
            })
            resp.set_cookie(
                SID_COOKIE, sid, max_age=60 * 60 * 24 * 365, httponly=True, samesite="Lax"
            )
            return resp

        user = _active_user(sid)
        if user:
            _db.touch(sid)
            return jsonify({
                "status": "active",
                "is_admin": bool(user["is_admin"]),
                "name": user["name"],
                "csrf": _db.csrf_for(sid),
                "room": _cfg.room_name,
                "pending_count": len(_db.list_pending()) if user["is_admin"] else None,
            })

        req = _db.get_join_request(sid)
        if req:
            if req["status"] == "pending":
                return jsonify({"status": "pending", "csrf": _db.csrf_for(sid),
                                "room": _cfg.room_name})
            return jsonify({"status": "rejected", "banned": _db.is_banned(req["name"]),
                            "csrf": _db.csrf_for(sid), "room": _cfg.room_name})
        return jsonify({"status": "new", "csrf": _db.csrf_for(sid), "room": _cfg.room_name})

    # ── request to join ──────────────────────────────────────────────────
    @app.post("/api/request_join")
    def api_request_join():
        sid = _fresh_sid()
        if not _require_csrf(sid):
            return jsonify({"error": "Invalid security token. Refresh and try again."}), 403
        data = _is_json_object() or {}
        name = (data.get("name") or "").strip()
        if len(name) < 2 or len(name) > 20:
            return jsonify({"error": "Name must be 2–20 characters."}), 400
        if not all(c.isalnum() or c in " _-." for c in name):
            return jsonify({"error": "Letters, numbers, spaces and . – _ only."}), 400
        if _db.is_banned(name):
            return jsonify({"error": "That name is on the block list."}), 403
        if _db.name_is_taken(name, exclude_sid=sid):
            return jsonify({"error": "That name is already in use."}), 409

        _db.add_join_request(sid, name)
        _broadcast_presence()
        return _cookie_reply(sid, {"ok": True})

    # ── withdraw a join request (so nothing leaves you stuck "waiting") ──
    @app.post("/api/cancel_join")
    def api_cancel_join():
        sid = request.cookies.get(SID_COOKIE)
        if not sid or _db and _db.get_user(sid):
            # already in the room (approved) — nothing to withdraw
            return jsonify({"ok": True})
        if not _require_csrf(sid):
            return jsonify({"error": "Invalid security token. Refresh and try again."}), 403
        _db.cancel_join_request(sid)
        _broadcast_presence()
        return jsonify({"ok": True})

    # ── moderator login ──────────────────────────────────────────────────
    @app.post("/api/admin_login")
    def api_admin_login():
        sid = _fresh_sid()
        if not _require_csrf(sid):
            return jsonify({"error": "Invalid security token. Refresh and try again."}), 403
        data = _is_json_object() or {}
        password = (data.get("password") or "").strip()
        if not verify_admin_password(password):
            return jsonify({"error": "Incorrect password."}), 403
        name = _next_moderator_name(exclude_sid=sid)
        _db.add_user(sid, name, is_admin=True)
        # Drop any pending join request held by this sid so the moderator
        # doesn't leave a stale "waiting for approval" state behind (e.g.
        # they clicked Request to join by mistake before signing in).
        _db.cancel_join_request(sid)
        _db.add_system_message(f"{name} is in the room.")
        _broadcast_presence()
        return _cookie_reply(sid, {
            "ok": True,
            "is_admin": True,
            "name": name,
            "csrf": _db.csrf_for(sid),
        })

    # ── sign out ─────────────────────────────────────────────────────────
    @app.post("/api/logout")
    def api_logout():
        sid = request.cookies.get(SID_COOKIE)
        if sid and _db and _db.exists_any_session(sid) and not _require_csrf(sid):
            return jsonify({"error": "Invalid security token. Refresh and try again."}), 403
        if sid and _db:
            user = _db.get_user(sid)
            if user:
                name = _db.remove_user(sid)
                if name:
                    _db.add_system_message(f"{name} left the room.")
                    _broadcast_presence()
            _db.delete_session(sid)
        resp = jsonify({"ok": True})
        resp.delete_cookie(SID_COOKIE)
        return resp

    # ── messages (history / pagination) ──────────────────────────────────
    @app.get("/api/messages")
    def api_messages():
        sid = request.cookies.get(SID_COOKIE)
        user = _active_user(sid) if sid else None
        if not user:
            return jsonify({"error": "Not in the room."}), 403
        _db.touch(sid)

        after = request.args.get("after", type=int, default=0)
        before = request.args.get("before", type=int, default=None)
        limit = min(request.args.get("limit", type=int, default=100), 200)
        rows = _db.get_messages(after=after, before=before, limit=limit)

        payload = {
            "messages": [_serialize_message(r) for r in rows],
            "room": _cfg.room_name,
        }
        if rows:
            payload["earliest_id"] = rows[0]["id"]
            payload["more_before"] = _db.has_messages_before(rows[0]["id"])
        if user["is_admin"]:
            payload["pending"] = [
                {"name": r["name"], "requested_at": r["requested_at"]}
                for r in _db.list_pending()
            ]
        return jsonify(payload)

    # ── send a message ───────────────────────────────────────────────────
    @app.post("/api/send")
    def api_send():
        sid = request.cookies.get(SID_COOKIE)
        user = _active_user(sid) if sid else None
        if not user:
            return jsonify({"error": "Not in the room."}), 403
        if not _require_csrf(sid):
            return jsonify({"error": "Invalid security token. Refresh and try again."}), 403

        # rate limit (per session, wall-clock gap)
        min_gap = _app.config.get("RATE_LIMIT_SECONDS", 1.0)
        with _rate_lock:
            last = _last_send.get(sid, 0.0)
            now = time.time()
            if now - last < min_gap:
                return jsonify({"error": "Slow down — you're sending too fast."}), 429
            _last_send[sid] = now

        data = _is_json_object() or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Empty message."}), 400
        if len(text) > MAX_TEXT_LENGTH:
            return jsonify({"error": f"Message too long (max {MAX_TEXT_LENGTH})."}), 400

        _db.touch(sid)
        _db.add_message(user["name"], text, kind="chat")  # never trust client-set kind
        _broadcast_presence()
        return jsonify({"ok": True})

    # ── moderator actions ────────────────────────────────────────────────
    @app.post("/api/approve")
    def api_approve():
        return _moderator_action(
            action=_db.approve_join_request,
            msg_template="{name} joined the room.",
        )

    @app.post("/api/reject")
    def api_reject():
        return _moderator_action(
            action=_db.reject_join_request,
            msg_template="{name}'s request was declined.",
        )

    @app.post("/api/kick")
    def api_kick():
        sid, user = _moderator()
        if user is None:
            return jsonify({"error": "Moderator only."}), 403
        data = _is_json_object() or {}
        target_name = (data.get("name") or "").strip()
        if not target_name:
            return jsonify({"error": "Missing target."}), 400
        if target_name.lower() == user["name"].lower():
            return jsonify({"error": "You can't kick yourself."}), 400
        target = _find_user_by_name(target_name)
        if not target:
            return jsonify({"error": "No such user."}), 404
        if target["is_admin"]:
            return jsonify({"error": "Moderator can't be kicked."}), 403
        _db.ban_name(target_name)
        _db.remove_user(target["sid"])
        _db.add_system_message(f"{target['name']} was removed.")
        _broadcast_presence()
        return jsonify({"ok": True})

    @app.post("/api/clear")
    def api_clear():
        if not _moderator()[1]:
            return jsonify({"error": "Moderator only."}), 403
        _db.clear_messages()
        _db.add_system_message("The room was cleared.")
        broadcast("clear")
        return jsonify({"ok": True})

    # ── presence snapshot (used by SSE + light-weight clients) ───────────
    @app.get("/api/presence")
    def api_presence():
        sid = request.cookies.get(SID_COOKIE)
        user = _active_user(sid) if sid else None
        return jsonify({"online": [_public_user_row(u) for u in _db.list_online_users()]})

    # ── server-sent events (real-time push) ──────────────────────────────
    @app.get("/api/stream")
    def api_stream():
        sid = request.cookies.get(SID_COOKIE)
        user = _active_user(sid) if sid else None
        if not user:
            return jsonify({"error": "Not in the room."}), 403
        _db.touch(sid)
        _broadcast_presence()

        def gen():
            since_id = _db.get_last_message_id()
            epoch_at_connect = _cleared_epoch
            was_registered = True
            last_presence_json = ""
            last_presence_sent_at = 0.0

            while True:
                try:
                    with _notifier:
                        _notifier.wait(timeout=15)

                    # kicked / removed while connected → tell the client
                    current = _db.get_user(sid) if _db else None
                    if was_registered and current is None:
                        yield _sse("denied", json.dumps({"reason": "removed"}))
                        return
                    was_registered = current is not None
                    if current:
                        _db.touch(sid)

                    # history reset after a clear
                    if epoch_at_connect != _cleared_epoch:
                        epoch_at_connect = _cleared_epoch
                        since_id = 0
                        yield _sse("cleared", "{}")

                    rows = _db.get_messages(after=since_id, limit=200)
                    if rows:
                        since_id = rows[-1]["id"]
                        payload = [_serialize_message(r) for r in rows]
                        yield _sse("messages", json.dumps(payload))

                    # push presence when it changes (or ~every 30s as a heartbeat)
                    online = [_public_user_row(u) for u in _db.list_online_users()]
                    pres = json.dumps({
                        "online": online,
                        "pending": len(_db.list_pending()) if _db else 0,
                    })
                    now = time.time()
                    if pres != last_presence_json or now - last_presence_sent_at > 30:
                        last_presence_json = pres
                        last_presence_sent_at = now
                        yield _sse("presence", pres)

                    yield ": keep-alive\n\n"
                except GeneratorExit:
                    return
                except Exception:
                    try:
                        yield _sse("error", json.dumps({"message": "stream error"}))
                    except Exception:
                        return

        return Response(gen(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        })


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


# ─── shared moderator machinery ─────────────────────────────────────────────
def _moderator():
    """Return (sid, user) when the request is a verified moderator, else (sid, None)."""
    sid = request.cookies.get(SID_COOKIE) or ""
    user = _active_user(sid) if _db else None
    if not user or not user["is_admin"] or not _require_csrf(sid):
        return sid, None
    return sid, user


def _target_name() -> str:
    data = _is_json_object() or {}
    return (data.get("name") or data.get("target") or "").strip()


def _find_user_by_name(name: str) -> Optional[dict]:
    key = name.lower().strip()
    for u in _db.list_online_users():
        if u["name"].lower() == key:
            row = _db.get_user_by_name(u["name"])
            if row:
                return row
    return None


def _next_moderator_name(exclude_sid: Optional[str] = None) -> str:
    """Pick a unique display name so a second mod login doesn't displace the first."""
    base = "Moderator"
    if not _db.name_is_taken(base, exclude_sid=exclude_sid):
        return base
    n = 2
    while _db.name_is_taken(f"{base} {n}", exclude_sid=exclude_sid):
        n += 1
    return f"{base} {n}"


def _moderator_action(action, msg_template: str):
    """Run a moderator-only action and announce the outcome as a system message."""
    if not _moderator()[1]:
        return jsonify({"error": "Moderator only."}), 403
    name = _target_name()
    if not name:
        return jsonify({"error": "Missing target name."}), 400
    if not action(name):
        return jsonify({"error": "Nothing to do — no pending request by that name."}), 404
    _db.add_system_message(msg_template.format(name=name))
    _broadcast_presence()
    return jsonify({"ok": True})


# ─── sweeper thread: evict stale sessions so presence stays honest ──────────
def start_sweeper(interval_seconds: float = 20.0) -> threading.Thread:
    def loop():
        while True:
            time.sleep(interval_seconds)
            try:
                if not _db:
                    continue
                gone = _db.expire_stale_sessions()
                for name in gone:
                    _db.add_system_message(f"{name} left the room.")
                _broadcast_presence()
            except Exception:
                pass

    t = threading.Thread(target=loop, daemon=True, name="presence-sweeper")
    t.start()
    return t