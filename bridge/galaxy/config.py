# -*- coding: utf-8 -*-
"""Configuration for the standalone Galaxy bridge service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BridgeSettings:
    galaxy_host: str
    galaxy_port: int
    galaxy_username: str
    galaxy_password: str
    bridge_host: str = "0.0.0.0"
    bridge_port: int = 8080
    bridge_token: str = ""
    log_level: str = "info"
    reload: bool = False

    @classmethod
    def from_env(cls) -> "BridgeSettings":
        return cls(
            galaxy_host=(os.getenv("GALAXY_HOST", "") or "").strip(),
            galaxy_port=int((os.getenv("GALAXY_PORT", "0") or "0").strip() or "0"),
            galaxy_username=(os.getenv("GALAXY_USERNAME", "") or "").strip(),
            galaxy_password=os.getenv("GALAXY_PASSWORD", "") or "",
            bridge_host=(os.getenv("GALAXY_BRIDGE_HOST", "0.0.0.0") or "0.0.0.0").strip(),
            bridge_port=int((os.getenv("GALAXY_BRIDGE_PORT", "8080") or "8080").strip() or "8080"),
            bridge_token=(os.getenv("GALAXY_BRIDGE_TOKEN", "") or "").strip(),
            log_level=(os.getenv("GALAXY_BRIDGE_LOG_LEVEL", "info") or "info").strip().lower(),
            reload=_env_bool("GALAXY_BRIDGE_RELOAD", False),
        )

    def validate_sdk_env(self) -> None:
        missing = []
        if not self.galaxy_host:
            missing.append("GALAXY_HOST")
        if not self.galaxy_port:
            missing.append("GALAXY_PORT")
        if not self.galaxy_username:
            missing.append("GALAXY_USERNAME")
        if not self.galaxy_password:
            missing.append("GALAXY_PASSWORD")
        if missing:
            raise RuntimeError("Missing Galaxy bridge SDK config: " + ", ".join(missing))

