"""Best-effort secret redaction for locally stored agent trajectories.

The store is local-first, but local does not mean safe: transcripts often
contain API keys, bearer tokens, passwords, or database URLs. Redaction runs
before hashing and writing, so secrets never enter the content-addressed store.

Set ``AGENT_MILESTONE_REDACT=0`` to disable redaction for a trusted archive.
"""

from __future__ import annotations

import os
import re
from typing import Any

_RULES = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED:openai_key]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "[REDACTED:github_token]"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"), "[REDACTED:github_token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws_key]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED:slack_token]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [REDACTED:token]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd|pwd)\b"
            r"\s*[:=]\s*['\"]?([^\s'\"<>]{6,})"
        ),
        lambda m: f"{m.group(1)}=[REDACTED:secret]",
    ),
    (
        re.compile(r"(?i)\b(?:postgres|mysql|redis|mongodb)://[^\s]+"),
        "[REDACTED:connection_string]",
    ),
]


def redact_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    for pattern, replacement in _RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact secrets in strings/lists/dicts."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


def redaction_enabled() -> bool:
    return os.getenv("AGENT_MILESTONE_REDACT", "1").strip().lower() not in {"0", "false", "no", "off"}


def redact_step(step: dict, *, enabled: bool | None = None) -> dict:
    if enabled is None:
        enabled = redaction_enabled()
    return redact_value(step) if enabled else dict(step)
