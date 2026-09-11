"""LAN Chat server — entry point.

Run from this directory:

    python main.py [--port 5000] [--room "Engineering"] [--admin-password secret]

Features a fully offline mode: if a vendored `deps/` folder exists (created by
`bundle_deps.py`), Flask is loaded straight from it, so the server needs no
internet at all. Otherwise the system Python environment is used.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys

# ── offline bootstrap: prefer the vendored deps/ folder if present ─────────
_DEPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deps")
if os.path.isdir(_DEPS_DIR) and _DEPS_DIR not in sys.path:
    sys.path.insert(0, _DEPS_DIR)


def get_local_ip() -> str:
    """Best-effort LAN-facing IP (connect a UDP socket; it never sends data)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lan-chat",
        description="Self-hosted, approval-gated chat for a local network.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="port to listen on (default: 5000)")
    parser.add_argument("--room", default="LAN Chat", help="room / channel name (default: 'LAN Chat')")
    parser.add_argument("--db", default="data/lan-chat.db", help=f"path to the SQLite database file")
    parser.add_argument(
        "--admin-password",
        default="",
        help="moderator password (falls back to $LAN_CHAT_ADMIN_PASSWORD, then 'admin')",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="minimum seconds between sends per session (default: 1.0; use 0 to disable)",
    )
    return parser.parse_args()


def _test_venv() -> None:
    """Import the pieces we need so failures surface with a friendly message."""
    try:
        import flask  # noqa: F401
    except ImportError:
        sys.exit(
            "Flask is not installed.\n"
            "  · online:   python bundle_deps.py   (vendors Flask into ./deps for offline use)\n"
            "  · or:       pip install -r requirements.txt"
        )


def main() -> None:
    args = parse_args()
    from config import Config
    from db import DB
    from app import create_app
    import routes

    _test_venv()

    cfg = Config(
        host=args.host,
        port=args.port,
        room_name=args.room,
        db_path=args.db,
        admin_password=args.admin_password,
        rate_limit_seconds=max(0.0, args.rate),
    )
    cfg.db = DB(cfg.db_path)

    app = create_app(cfg)
    routes.start_sweeper()

    local_ip = get_local_ip()
    banner = f"""
  ┌────────────────────────────────────────────────────────┐
  │                   LAN CHAT SERVER                      │
  ├────────────────────────────────────────────────────────┤
  │  Room        {cfg.room_name:<38}│
  │  Listen      http://{local_ip}:{args.port:<30}│
  │  Database    {cfg.db_path:<38}│
  │  Approvals   moderator-gated (password required)      │
  ├────────────────────────────────────────────────────────┤
  │  Share the Listen URL with anyone on the LAN — they    │
  │  join by name and wait for you to approve them.        │
  │  Press Ctrl+C to stop.                                 │
  └────────────────────────────────────────────────────────┘
"""
    print(banner)

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()