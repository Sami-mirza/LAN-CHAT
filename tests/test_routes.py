"""End-to-end tests for LAN Chat.

Each test runs against a fresh in-memory SQLite database through Flask's
test client, so nothing touches the developer's real data.
"""

from __future__ import annotations

import io
import os
import sys

import pytest

# make the project importable regardless of how pytest was invoked
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from db import DB  # noqa: E402

ADMIN_PW = "correct horse battery staple"


@pytest.fixture()
def client():
    cfg = Config(db_path=":memory:", admin_password=ADMIN_PW, rate_limit_seconds=0)
    cfg.db = DB(cfg.db_path)
    app = create_app(cfg)
    app.config["TESTING"] = True
    return app.test_client()


def boot(cl, admin=False, password=ADMIN_PW) -> dict:
    """Bootstrap a client, optionally signing in as moderator, returning state."""
    r = cl.get("/api/bootstrap")
    data = r.get_json()
    if admin and data["status"] != "active":
        csrf = data["csrf"]
        res = cl.post("/api/admin_login", json={"password": password},
                      headers={"X-CSRF": csrf})
        assert res.status_code == 200
        data = cl.get("/api/bootstrap").get_json()
    return data


def csrf(cl) -> str:
    return cl.get("/api/bootstrap").get_json()["csrf"]


def user_joins(cl, name: str):
    token = csrf(cl)
    r = cl.post("/api/request_join", json={"name": name}, headers={"X-CSRF": token})
    assert r.status_code == 200, r.get_json()


# ── smoke: page + assets ───────────────────────────────────────────────────
def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"LAN" in r.data or b"lan" in r.data


def test_static_assets_served(client):
    for path in ("/static/style.css", "/static/app.js"):
        r = client.get(path)
        assert r.status_code == 200, path


# ── onboarding flow ────────────────────────────────────────────────────────
def make_mod(client, password=ADMIN_PW):
    """A second, independent client that signs in as moderator."""
    mod = client.application.test_client()
    st = mod.get("/api/bootstrap").get_json()
    r = mod.post("/api/admin_login", json={"password": password},
                 headers={"X-CSRF": st["csrf"]})
    assert r.status_code == 200, r.get_json()
    return mod


def test_join_approve_active_flow(client):
    alice = client.get("/api/bootstrap").get_json()
    assert alice["status"] == "new" and alice["csrf"]

    user_joins(client, "Alice")
    st = client.get("/api/bootstrap").get_json()
    assert st["status"] == "pending"

    # moderator approves (separate client so sids don't collide)
    mod = make_mod(client)
    r = mod.post("/api/approve", json={"name": "Alice"},
                 headers={"X-CSRF": csrf(mod)})
    assert r.status_code == 200

    assert client.get("/api/bootstrap").get_json()["status"] == "active"


def test_banned_name_rejected(client):
    mod = make_mod(client)
    user_joins(client, "Alice")
    mod.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(mod)})

    # moderator kicks Alice → Alice blocked from rejoining
    r = mod.post("/api/kick", json={"name": "Alice"}, headers={"X-CSRF": csrf(mod)})
    assert r.status_code == 200

    user_rejoin = client.post("/api/request_join", json={"name": "Alice"},
                              headers={"X-CSRF": csrf(client)})
    assert user_rejoin.status_code == 403  # banned


def test_duplicate_names_rejected(client):
    mod = make_mod(client)
    user_joins(client, "Alice")
    mod.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(mod)})

    # a fresh visitor (independent sid) tries the same name
    other = client.application.test_client()
    r = other.post("/api/request_join", json={"name": "alice"},
                   headers={"X-CSRF": csrf(other)})
    assert r.status_code == 409


# ── security ───────────────────────────────────────────────────────────────
def test_csrf_required_on_mutations(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})

    no_csrf = client.post("/api/send", json={"text": "hi"})
    assert no_csrf.status_code == 403


def test_cannot_forge_system_message(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})

    r = client.post("/api/send", json={"text": "hack", "kind": "system"},
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 200
    rows = client.get("/api/messages").get_json()["messages"]
    user_rows = [m for m in rows if m["kind"] == "system"]
    assert all(m["user"] == "System" for m in user_rows)


def test_invalid_names_rejected(client):
    for bad in ("x", "", "<script>alert(1)</script>", "a" * 21):
        r = client.post("/api/request_join", json={"name": bad},
                        headers={"X-CSRF": csrf(client)})
        assert r.status_code == 400, bad


def test_xff_header_cannot_imply_admin(client):
    # X-Forwarded-For must never decide privileges; admin requires a password.
    r = client.post("/api/admin_login",
                    json={"password": "wrong"},
                    headers={"X-Forwarded-For": "127.0.0.1",
                             "X-CSRF": csrf(client)})
    assert r.status_code == 403


def test_moderator_only_routes(client):
    # a plain visitor (not approved) cannot moderate
    user_joins(client, "Alice")
    for path in ("/api/clear", "/api/approve", "/api/reject", "/api/kick"):
        r = client.post(path, json={})
        assert r.status_code == 403, path


def test_stdout_no_debug_flag(client):
    # sanity: app must never start with debug on
    assert client.application.debug is False


# ── messages ───────────────────────────────────────────────────────────────
def test_send_and_pagination(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})

    for i in range(5):
        r = client.post("/api/send", json={"text": f"msg {i}"},
                        headers={"X-CSRF": csrf(client)})
        assert r.status_code == 200

    data = client.get("/api/messages?after=0&limit=10").get_json()
    texts = [m["text"] for m in data["messages"] if m["kind"] == "chat"]
    assert texts == ["msg 0", "msg 1", "msg 2", "msg 3", "msg 4"]
    assert data["more_before"] is False


def test_empty_message_rejected(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})
    r = client.post("/api/send", json={"text": "   "}, headers={"X-CSRF": csrf(client)})
    assert r.status_code == 400


def test_overlong_message_truncated_rejected(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})
    r = client.post("/api/send", json={"text": "x" * 1001},
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 400


# ── persistence ────────────────────────────────────────────────────────────
def test_persistence_across_restart(tmp_path):
    db_path = str(tmp_path / "chat.db")
    cfg = Config(db_path=db_path, admin_password="pw", rate_limit_seconds=0)
    cfg.db = DB(cfg.db_path)
    app = create_app(cfg)
    app.config["TESTING"] = True
    cl = app.test_client()

    boot(cl, admin=True, password="pw")
    cl.post("/api/send", json={"text": "persist me"},
            headers={"X-CSRF": csrf(cl)})

    # new process reads the same file
    cfg2 = Config(db_path=db_path, admin_password="pw", rate_limit_seconds=0)
    cfg2.db = DB(cfg2.db_path)
    app2 = create_app(cfg2)
    app2.config["TESTING"] = True
    cl2 = app2.test_client()
    boot(cl2, admin=True, password="pw")
    rows = cl2.get("/api/messages").get_json()["messages"]
    assert any(m["text"] == "persist me" for m in rows)


# ── rate limiting ──────────────────────────────────────────────────────────
def test_rate_limit(client):
    cfg = Config(db_path=":memory:", admin_password="x", rate_limit_seconds=0.5)
    cfg.db = DB(cfg.db_path)
    app = create_app(cfg)
    app.config["TESTING"] = True
    cl = app.test_client()
    boot(cl, admin=True, password="x")
    r1 = cl.post("/api/send", json={"text": "a"}, headers={"X-CSRF": csrf(cl)})
    assert r1.status_code == 200
    r2 = cl.post("/api/send", json={"text": "b"}, headers={"X-CSRF": csrf(cl)})
    assert r2.status_code == 429

# ── regressions for previously broken flows ───────────────────────────────
def test_reject_leaves_waiter_as_rejected(client):
    user_joins(client, "Alice")
    assert client.get("/api/bootstrap").get_json()["status"] == "pending"
    mod = make_mod(client)
    r = mod.post("/api/reject", json={"name": "Alice"}, headers={"X-CSRF": csrf(mod)})
    assert r.status_code == 200
    st = client.get("/api/bootstrap").get_json()
    assert st["status"] == "rejected"


def test_cancel_join_withdraws_pending(client):
    token = csrf(client)
    assert client.post("/api/request_join", json={"name": "Bob"},
                       headers={"X-CSRF": token}).status_code == 200
    assert client.get("/api/bootstrap").get_json()["status"] == "pending"
    r = client.post("/api/cancel_join", json={}, headers={"X-CSRF": token})
    assert r.status_code == 200
    assert client.get("/api/bootstrap").get_json()["status"] == "new"


def test_kick_keeps_csrf_for_rejoin_with_new_name(client):
    """Kicked users must be able to retry without a full page refresh."""
    mod = make_mod(client)
    token = csrf(client)
    assert client.post("/api/request_join", json={"name": "Alice"},
                       headers={"X-CSRF": token}).status_code == 200
    mod.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(mod)})
    assert client.get("/api/bootstrap").get_json()["status"] == "active"

    assert mod.post("/api/kick", json={"name": "Alice"},
                    headers={"X-CSRF": csrf(mod)}).status_code == 200

    # Same pre-kick CSRF token must still work (session is kept on kick).
    banned = client.post("/api/request_join", json={"name": "Alice"},
                         headers={"X-CSRF": token})
    assert banned.status_code == 403
    ok = client.post("/api/request_join", json={"name": "Alicia"},
                     headers={"X-CSRF": token})
    assert ok.status_code == 200, ok.get_json()
    assert client.get("/api/bootstrap").get_json()["status"] == "pending"


def test_second_moderator_does_not_evict_first(client):
    mod1 = make_mod(client)
    name1 = mod1.get("/api/bootstrap").get_json()["name"]
    assert name1 == "Moderator"

    mod2 = make_mod(client)
    st2 = mod2.get("/api/bootstrap").get_json()
    assert st2["status"] == "active"
    assert st2["name"] == "Moderator 2"

    st1 = mod1.get("/api/bootstrap").get_json()
    assert st1["status"] == "active"
    assert st1["name"] == "Moderator"


def test_logout_requires_csrf(client):
    boot(client, admin=True)
    r = client.post("/api/logout", json={})
    assert r.status_code == 403
    r = client.post("/api/logout", json={}, headers={"X-CSRF": csrf(client)})
    assert r.status_code == 200
    assert client.get("/api/bootstrap").get_json()["status"] == "new"


def test_ban_is_ephemeral_across_restart(tmp_path):
    """Kicking blocks a name only for the current server run; after a restart
    the same name can join again (bans are in-memory, never persisted)."""
    db_path = str(tmp_path / "chat.db")
    cfg = Config(db_path=db_path, admin_password="pw", rate_limit_seconds=0)
    cfg.db = DB(cfg.db_path)
    app = create_app(cfg)
    app.config["TESTING"] = True
    cl = app.test_client()
    boot(cl, admin=True, password="pw")

    visitor = app.test_client()
    user_joins(visitor, "Sam")
    assert cl.post("/api/approve", json={"name": "Sam"},
                   headers={"X-CSRF": csrf(cl)}).status_code == 200
    assert cl.post("/api/kick", json={"name": "Sam"},
                   headers={"X-CSRF": csrf(cl)}).status_code == 200
    # within this run the name stays blocked
    assert visitor.post("/api/request_join", json={"name": "Sam"},
                        headers={"X-CSRF": csrf(visitor)}).status_code == 403

    # server "restart": same database file, fresh app instance
    cfg2 = Config(db_path=db_path, admin_password="pw", rate_limit_seconds=0)
    cfg2.db = DB(cfg2.db_path)
    app2 = create_app(cfg2)
    app2.config["TESTING"] = True
    cl2 = app2.test_client()
    boot(cl2, admin=True, password="pw")
    fresher = app2.test_client()
    assert fresher.post("/api/request_join", json={"name": "Sam"},
                        headers={"X-CSRF": csrf(fresher)}).status_code == 200


def test_initial_history_returns_newest_page(client):
    """after=0 must load the latest messages, not the oldest ones."""
    boot(client, admin=True)
    for i in range(12):
        assert client.post("/api/send", json={"text": f"m{i}"},
                           headers={"X-CSRF": csrf(client)}).status_code == 200
    data = client.get("/api/messages?after=0&limit=5").get_json()
    chats = [m["text"] for m in data["messages"] if m["kind"] == "chat"]
    assert chats == ["m7", "m8", "m9", "m10", "m11"]
    assert data["more_before"] is True
    older = client.get(
        f"/api/messages?before={data['earliest_id']}&limit=5"
    ).get_json()
    older_chats = [m["text"] for m in older["messages"] if m["kind"] == "chat"]
    assert "m6" in older_chats or "m0" in older_chats


# ── @mention support ───────────────────────────────────────────────────────
def test_users_endpoint_lists_online_users(client):
    mod = make_mod(client)
    user_joins(client, "Alice")
    assert mod.post("/api/approve", json={"name": "Alice"},
                    headers={"X-CSRF": csrf(mod)}).status_code == 200
    user_joins(client, "Bob")

    data = client.get("/api/users").get_json()
    assert "Alice" in data["users"]
    assert "Moderator" in data["users"]      # the online mod is listed too
    assert "Bob" not in data["users"]        # still pending → not listed


def test_users_endpoint_requires_room_member(client):
    # a visitor who never joined has no session user → 403
    r = client.get("/api/users")
    assert r.status_code == 403


def test_mention_text_round_trips(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    r = client.post("/api/send", json={"text": "Hey @Alice, check this!"},
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 200
    msgs = client.get("/api/messages").get_json()["messages"]
    assert any(m["text"] == "Hey @Alice, check this!" for m in msgs)


# ── voice messages ─────────────────────────────────────────────────────────
def test_send_and_retrieve_voice(client):
    user_joins(client, "Alice")
    mod = make_mod(client)
    assert mod.post("/api/approve", json={"name": "Alice"},
                    headers={"X-CSRF": csrf(mod)}).status_code == 200

    audio = b"\x1a\x45\xdf\xa3" + b"x" * 500  # fake webm blob, >100 bytes
    r = client.post("/api/send-voice",
                    data={"audio": (io.BytesIO(audio), "voice.webm"),
                          "duration": "3.2"},
                    content_type="multipart/form-data",
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 200, r.get_json()

    msgs = client.get("/api/messages").get_json()["messages"]
    voice_rows = [m for m in msgs if m["kind"] == "voice"]
    assert len(voice_rows) == 1
    assert voice_rows[0]["has_audio"] is True

    mid = voice_rows[0]["id"]
    got = client.get(f"/api/voice/{mid}")
    assert got.status_code == 200
    assert got.data == audio


def test_voice_fetch_rejects_non_voice_message(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})
    client.post("/api/send", json={"text": "plain text"},
                headers={"X-CSRF": csrf(client)})
    text_row = client.get("/api/messages").get_json()["messages"][-1]
    assert client.get(f"/api/voice/{text_row['id']}").status_code == 404


def test_voice_requires_audio(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})
    r = client.post("/api/send-voice",
                    data={"duration": "3.2"},
                    content_type="multipart/form-data",
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 400


def test_voice_too_short_rejected(client):
    user_joins(client, "Alice")
    boot(client, admin=True)
    client.post("/api/approve", json={"name": "Alice"}, headers={"X-CSRF": csrf(client)})
    r = client.post("/api/send-voice",
                    data={"audio": (io.BytesIO(b"\x00"), "voice.webm"),
                          "duration": "0.1"},
                    content_type="multipart/form-data",
                    headers={"X-CSRF": csrf(client)})
    assert r.status_code == 400
