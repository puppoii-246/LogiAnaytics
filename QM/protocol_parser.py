"""
Protocol Parser

Converts raw queue-protocol strings into typed Event objects.
No state updates, no logging, no networking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    TOKEN_GENERATED = "TOKEN_GENERATED"
    NEXT = "NEXT"
    CALL = "CALL"
    RESET = "RESET"


class ProtocolError(Exception):
    """Raised when a raw protocol string cannot be parsed."""


@dataclass(frozen=True)
class Event:
    type: EventType
    raw: str
    group_id: int
    counter_id: Optional[int] = None
    token: Optional[int] = None
    remaining: Optional[int] = None


def parse(raw: str | bytes) -> Event | None:
    """
    Parse a raw protocol message into an Event.

    Returns None for the silent no-op token-generation message (-1).
    Raises ProtocolError for malformed input.
    """
    text = _normalize(raw)

    if text == "-1":
        return None

    if not text:
        raise ProtocolError("Empty protocol message")

    match text[0]:
        case "W":
            return _parse_token_generated(text)
        case "#":
            return _parse_next(text)
        case "&":
            return _parse_call(text)
        case "$":
            return _parse_reset(text)
        case _:
            raise ProtocolError(f"Unknown protocol prefix: {text[0]!r} in {text!r}")


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _normalize(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"Invalid UTF-8 in protocol message: {exc}") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise ProtocolError(f"Protocol message must be str or bytes, got {type(raw).__name__}")
    return text.strip()


def _require_digits(value: str, field: str, raw: str) -> int:
    if not (value.isascii() and value.isdigit()):
        raise ProtocolError(f"Expected digits for {field}, got {value!r} in {raw!r}")
    return int(value)


def _payload_after_at(text: str, expected_len: int) -> tuple[str, str]:
    """Return (raw_normalized, payload) where payload is the expected_len chars after '@'."""
    at = text.find("@")
    if at < 0:
        raise ProtocolError(f"Missing '@' in protocol message: {text!r}")
    payload = text[at + 1 :]
    if len(payload) < expected_len:
        raise ProtocolError(
            f"Protocol payload too short after '@': need {expected_len} chars, "
            f"got {len(payload)} in {text!r}"
        )
    if len(payload) > expected_len:
        raise ProtocolError(
            f"Protocol payload too long after '@': need {expected_len} chars, "
            f"got {len(payload)} in {text!r}"
        )
    return text, payload


def _parse_token_generated(text: str) -> Event:
    # WGTTTT — 6 characters total
    if len(text) != 6:
        raise ProtocolError(
            f"TOKEN_GENERATED must be 6 characters (WGTTTT), got {len(text)}: {text!r}"
        )
    group_id = _require_digits(text[1], "group_id", text)
    token = _require_digits(text[2:6], "token", text)
    return Event(
        type=EventType.TOKEN_GENERATED,
        raw=text,
        group_id=group_id,
        token=token,
    )


def _parse_next(text: str) -> Event:
    # #…@GCCTTTTWGRRRR — 13 chars after '@'
    text, payload = _payload_after_at(text, 13)
    group_id = _require_digits(payload[0], "group_id", text)
    counter_id = _require_digits(payload[1:3], "counter_id", text)
    token = _require_digits(payload[3:7], "token", text)
    if payload[7] != "W":
        raise ProtocolError(f"NEXT expected 'W' before remaining count, got {payload[7]!r} in {text!r}")
    remaining_group = _require_digits(payload[8], "remaining_group", text)
    if remaining_group != group_id:
        raise ProtocolError(
            f"NEXT remaining group {remaining_group} does not match group {group_id} in {text!r}"
        )
    remaining = _require_digits(payload[9:13], "remaining", text)
    return Event(
        type=EventType.NEXT,
        raw=text,
        group_id=group_id,
        counter_id=counter_id,
        token=token,
        remaining=remaining,
    )


def _parse_call(text: str) -> Event:
    # &…@GCCTTTT — 7 chars after '@' (Recall treated identically)
    text, payload = _payload_after_at(text, 7)
    return Event(
        type=EventType.CALL,
        raw=text,
        group_id=_require_digits(payload[0], "group_id", text),
        counter_id=_require_digits(payload[1:3], "counter_id", text),
        token=_require_digits(payload[3:7], "token", text),
    )


def _parse_reset(text: str) -> Event:
    # $…@GCCTTTT — 7 chars after '@'
    # counter_id is parsed only to validate payload format; RESET always
    # clears the whole group, so counter_id is intentionally unused downstream.
    text, payload = _payload_after_at(text, 7)
    return Event(
        type=EventType.RESET,
        raw=text,
        group_id=_require_digits(payload[0], "group_id", text),
        counter_id=_require_digits(payload[1:3], "counter_id", text),
        token=_require_digits(payload[3:7], "token", text),
    )
