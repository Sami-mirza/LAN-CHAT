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
import subprocess
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
    ssl_group = parser.add_mutually_exclusive_group()
    ssl_group.add_argument(
        "--ssl",
        "--https",
        dest="use_ssl",
        action="store_true",
        help="serve over HTTPS with a self-signed certificate (required for "
        "browser microphone access on LAN origins)",
    )
    parser.add_argument(
        "--cert",
        default=None,
        metavar="PATH",
        help="PEM certificate to use with --ssl (default: auto-generate into certs/)",
    )
    parser.add_argument(
        "--key",
        default=None,
        metavar="PATH",
        help="PEM private key to use with --ssl (default: auto-generate into certs/)",
    )
    return parser.parse_args()


def _ensure_self_signed_cert(cert_path, key_path, san_host):
    """Return (cert_path, key_path) usable as a Flask `ssl_context`.

    If explicit paths were given, validate and use them. Otherwise generate
    a self-signed PEM pair with the system `openssl` into ``certs/``. The
    certificate includes a Subject Alternative Name covering localhost and the
    detected LAN IP so modern browsers will let the user click through the
    one-time "not private" warning.
    """
    if cert_path or key_path:
        if not (cert_path and key_path):
            sys.exit("Both --cert and --key are required together.")
        for name, p in (("--cert", cert_path), ("--key", key_path)):
            if not os.path.isfile(p):
                sys.exit(f"{name} file not found: {p}")
        return cert_path, key_path

    cert_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "selfsigned.crt")
    key_path = os.path.join(cert_dir, "selfsigned.key")

    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return cert_path, key_path

    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "825",
                "-subj",
                "/CN=LAN Chat",
                "-addext",
                f"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{san_host}",
                "-keyout",
                key_path,
                "-out",
                cert_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(
            "openssl was not found — cannot generate a self-signed certificate.\n"
            "  · install openssl (apt install openssl), or\n"
            "  · provide an existing cert with --cert and --key."
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(
            "Failed to generate a self-signed certificate.\n"
            + (exc.stderr or "").strip()
        )
    return cert_path, key_path


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
        use_ssl=args.use_ssl,
    )
    cfg.db = DB(cfg.db_path)

    local_ip = get_local_ip()
    if cfg.use_ssl:
        cfg.cert_path, cfg.key_path = _ensure_self_signed_cert(
            args.cert, args.key, local_ip
        )

    app = create_app(cfg)
    routes.start_sweeper()

    scheme = "https" if cfg.use_ssl else "http"
    listen = f"{scheme}://{local_ip}:{args.port}"
    # Each interior row is ` │  <label> <value:<42>│` so every line is exactly
    # 60 chars wide and the box borders line up (also for https URLs, which
    # are one char longer than http ones).
    def row(label: str, value: str) -> str:
        return f"  │  {label:<10}{value:<42}│"

    banner = (
        "\n"
        "  ┌────────────────────────────────────────────────────────┐\n"
        "  │                   LAN CHAT SERVER                      │\n"
        "  ├────────────────────────────────────────────────────────┤\n"
        f"{row('Room', cfg.room_name)}\n"
        f"{row('Listen', listen)}\n"
        f"{row('Database', cfg.db_path)}\n"
        f"{row('Approvals', 'moderator-gated (password required)')}\n"
        "  ├────────────────────────────────────────────────────────┤\n"
        f"  │  Share the Listen URL with anyone on the LAN — they    │\n"
        f"  │  join by name and wait for you to approve them.        │\n"
        f"  │  Press Ctrl+C to stop.                                 │\n"
        "  └────────────────────────────────────────────────────────┘\n"
    )
    if cfg.use_ssl:
        banner += (
            "  HTTPS enabled (self-signed cert). On first visit each browser\n"
            "  will warn about the certificate — click Advanced → Proceed so\n"
            "  the page becomes secure and the microphone is allowed.\n"
        )
    print(banner)

    ssl_context = (cfg.cert_path, cfg.key_path) if cfg.use_ssl else None
    app.run(host=args.host, port=args.port, debug=False, threaded=True, ssl_context=ssl_context)


if __name__ == "__main__":
    main()