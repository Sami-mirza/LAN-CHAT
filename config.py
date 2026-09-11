"""Application configuration for LAN Chat.

All runtime knobs live here so routes and entry points never hard-code
paths, ports, or secrets. Secrets come from CLI flags or environment
variables; nothing sensitive is stored in source control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_PORT = 5000
DEFAULT_ADMIN_PASSWORD = "admin"  # replaced via --admin-password / env


def _resolve_admin_password(value: Optional[str]) -> str:
    """Precedence: CLI flag > LAN_CHAT_ADMIN_PASSWORD env > default."""
    return value or os.environ.get("LAN_CHAT_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    room_name: str = "LAN Chat"
    db_path: str = "data/lan-chat.db"
    admin_password: str = DEFAULT_ADMIN_PASSWORD
    # minimum seconds between one session's sends (anti-spam)
    rate_limit_seconds: float = 1.0

    # Runtime bindings (resolved after construction, not constructor args)
    db: Optional[object] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.admin_password = _resolve_admin_password(self.admin_password)