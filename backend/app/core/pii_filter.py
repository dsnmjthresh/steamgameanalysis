"""PII detection and redaction for memory content.

Detects and redacts common PII patterns including emails, phone numbers,
IP addresses, API keys, and Bearer tokens from text before it is stored
in persistent memory.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
# Chinese mobile numbers: 1[3-9]XXXXXXXXX
_PHONE_CN_RE = re.compile(r"(?<!\d)(1[3-9]\d{1,2})\d{4}(\d{4})(?!\d)")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# API key / secret / token patterns
_API_KEY_RE = re.compile(
    r"(?:(?:sk|pk|api[_-]?key|secret|token)[=:]\s*)?"
    r"[a-zA-Z0-9_-]{20,64}",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+[a-zA-Z0-9._~+/=-]{10,}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_pii(text: str) -> bool:
    """Check whether *text* contains any detectable PII."""
    return bool(
        _EMAIL_RE.search(text)
        or _PHONE_CN_RE.search(text)
        or _IPV4_RE.search(text)
        or _API_KEY_RE.search(text)
        or _BEARER_RE.search(text)
    )


def filter_pii(text: str) -> str:
    """Replace all detectable PII with redaction markers.

    Returns a new string with PII replaced by placeholders such as
    ``[EMAIL_REDACTED]``.  The original *text* is not modified.
    """
    # Order matters: Bearer before API_KEY so Bearer tokens aren't
    # consumed by the looser API_KEY pattern.
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = _PHONE_CN_RE.sub(r"\1****\2", text)
    text = _IPV4_RE.sub("[IP_REDACTED]", text)
    text = _BEARER_RE.sub("[TOKEN_REDACTED]", text)
    text = _API_KEY_RE.sub("[KEY_REDACTED]", text)
    return text
