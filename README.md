# LAN Chat

A self-hosted, moderator-gated chat room for a **local network**. Runs with
**no internet connection** for anyone on the LAN — great for labs, offices,
events, or any environment where you want group chat without a third-party
service.

Built with Flask + vanilla JS, backed by **SQLite**, and delivered in real
time over **Server-Sent Events**.

---

## Features

| &nbsp; | 
| --- |
| ✅ **Approval-gated joining** — visitors pick a name and wait for the moderator to approve them |
| ✅ **Real-time messages** — SSE push, no polling, typing feels instant |
| ✅ **Moderator controls** — approve / decline joins, remove members, clear the room, block names |
| ✅ **Persistent history** — messages survive server restarts (SQLite) |
| ✅ **Online members list** — live presence with idle timeout |
| ✅ **Date-separated history** — paginated "load earlier", grouped by day |
| ✅ **Professional UI** — light & dark themes, responsive, accessible focus states |
| ✅ **Fully offline friendly** — vendored dependencies (`deps/`) mean zero downloads on the day |

## Quick start

Requires **Python 3.9+**.

```bash
# 1. (offline distribution only) bundle Flask once, with internet:
python bundle_deps.py

# 2. run the server:
python main.py

# 3. open the printed URL on any device on the same LAN.
```

To configure:

```bash
python main.py --port 5000 --room "Engineering" --admin-password "s3cr3t"
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--host` | `0.0.0.0` | Interface to bind |
| `--port` | `5000` | Listen port |
| `--room` | `LAN Chat` | Room name shown in the UI |
| `--db` | `data/lan-chat.db` | SQLite database location |
| `--admin-password` | env `LAN_CHAT_ADMIN_PASSWORD`, else `admin` | Moderator password |

The moderator password is **never stored** on disk — only its salted hash is
kept in memory. Anyone who signs in with it gains moderator controls in the
room.

### Installing Flask globally (instead of vendoring)

```bash
pip install -r requirements.txt
python main.py
```

## How joining works

1. A visitor opens the server URL and enters a display name.
2. The **moderator** (the person running the server) sees a pending request
   in the **Requests** panel.
3. Approve → the visitor is let in automatically; Reject → they can try a
   different name.
4. Moderators can **remove** members (name is then blocked) and **clear** the
   room from the header.

## Security notes

| Concern | How it's handled |
| --- | --- |
| Identity spoofing | Signed, httpOnly session cookie; **no trust in `X-Forwarded-For` or client IP** |
| CSRF | Per-session token required on every mutating request |
| XSS | Server validates names/messages; client renders **all** user data via `textContent` |
| Forged system messages | `kind` is set server-side only; client input can never be a system message |
| Flooding | Per-session send rate limit (`--rate` interval) |
| Admin password | Only an in-memory salted hash compared in constant time |

> **Deployment caveat:** the built-in Flask dev server is fine for LAN-scale
> use. For heavy public deployments, front LAN Chat with a production WSGI
> server and a reverse proxy on HTTPS.

## Project layout

```
main.py           entry point, CLI flags, offline bootstrap
app.py            Flask application factory
config.py         Configuration dataclass
db.py             SQLite persistence layer
routes.py         HTTP routes, security checks, SSE broadcast
templates/        index.html (static shell — no server-side templating)
static/           style.css (design system), app.js (client logic)
tests/            pytest suite
bundle_deps.py    vendors Flask into ./deps for offline use
requirements.txt  pinned Python dependencies
```

## Development

```bash
pip install -r requirements.txt
pytest -q
```

## License

[MIT](License)