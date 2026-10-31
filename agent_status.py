"""Small, dependency-free Agent status normalization helpers used by E-INK."""

from __future__ import annotations

import time
from typing import Any, Mapping


def format_agent_number(value: Any) -> str:
    if value is None or value == "":
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def normalize_agent_event(
    event: Mapping[str, Any] | None, *, now: float | None = None
) -> dict[str, Any]:
    source = dict(event or {})
    timestamp = float(
        source.get("updatedAt", source.get("timestamp", now if now is not None else time.time()))
        or 0
    )
    state = str(source.get("state", source.get("status", "idle")) or "idle").lower()
    provider = str(source.get("provider") or source.get("agentProvider") or "").strip()
    agent_name = str(source.get("agentName") or source.get("name") or "").strip()
    agent_version = str(source.get("agentVersion") or source.get("version") or "").strip()
    if not provider:
        probe = f"{agent_name} {source.get('model') or ''}".lower()
        provider = (
            "gemini"
            if "gemini" in probe
            else (
                "chatgpt"
                if "chatgpt" in probe or "gpt" in probe
                else "codex" if "codex" in probe else ""
            )
        )
    if not agent_name:
        agent_name = {"gemini": "Gemini", "chatgpt": "ChatGPT", "codex": "Codex"}.get(
            provider, "AI Agent"
        )
    return {
        **source,
        "provider": provider,
        "agentName": agent_name,
        "agentVersion": agent_version,
        "state": state,
        "status": str(source.get("status", state) or state),
        "updatedAt": timestamp,
        "timestamp": timestamp,
        "agent_active": state not in {"idle", "done", "completed", "failed", "error"},
    }


def is_agent_active(status: Mapping[str, Any] | None, *, now: float | None = None) -> bool:
    if not status:
        return False
    if "agent_active" in status:
        return bool(status["agent_active"])
    state = str(status.get("state", status.get("status", "idle")) or "idle").lower()
    return state not in {"idle", "done", "completed", "failed", "error"}


def read_codex_status(force: bool = False) -> dict[str, Any]:
    """Return an empty Agent status snapshot (no cloud Codex/ChatGPT client).

    Keeps the Agent layout path stable. BLE display and other modules do not
    depend on cloud usage telemetry.
    """
    _ = force
    return {
        "source": "unavailable",
        "authenticated": False,
        "accounts": [],
        "sessions": {"items": [], "cli_alive": False, "web_count": 0},
        "tokens": {},
        "generated_at": int(time.time()),
    }
