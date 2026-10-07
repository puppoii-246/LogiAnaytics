"""
Event Manager

Receives raw protocol messages (or parsed Events), applies business rules,
and updates Application State.
"""

from __future__ import annotations

from app_state import ApplicationState
from logger import get_logger
from protocol_parser import Event, EventType, ProtocolError, parse


def handle_raw(raw: str | bytes, state: ApplicationState) -> None:
    """Parse a raw message and apply it to state. Safe against malformed input."""
    logger = get_logger()
    if isinstance(raw, bytes):
        try:
            raw_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            logger.error("Invalid UTF-8 in protocol message: %r", raw)
            state.increment_error_count(repr(raw))
            return
    else:
        raw_text = raw

    logger.debug("Raw protocol: %r", raw_text)

    try:
        event = parse(raw_text)
    except ProtocolError as exc:
        logger.error("Malformed protocol: %s | raw=%r", exc, raw_text)
        state.increment_error_count(raw_text)
        return

    if event is None:
        # Silent no-op (-1)
        return

    logger.info("Parsed event: %s", event)
    handle_event(event, state)


def handle_event(event: Event, state: ApplicationState) -> None:
    """Apply a parsed event to application state."""
    logger = get_logger()

    match event.type:
        case EventType.TOKEN_GENERATED:
            ok = state.apply_token_generated(event.group_id, event.token, event.raw)
            if not ok:
                logger.warning(
                    "TOKEN_GENERATED for unknown group %s | raw=%r",
                    event.group_id,
                    event.raw,
                )
                state.increment_error_count(event.raw)
                return
            logger.info(
                "State: group %s last_generated=%s total=%s",
                event.group_id,
                event.token,
                event.token,
            )

        case EventType.NEXT | EventType.CALL:
            ok = state.apply_counter_event(
                group_id=event.group_id,
                counter_id=event.counter_id,
                token=event.token,
                event_type=event.type,
                raw=event.raw,
                remaining=event.remaining,
            )
            if not ok:
                logger.warning(
                    "%s for unknown group/counter %s/%s | raw=%r",
                    event.type.value,
                    event.group_id,
                    event.counter_id,
                    event.raw,
                )
                state.increment_error_count(event.raw)
                return
            logger.info(
                "State: group %s counter %s token=%s event=%s",
                event.group_id,
                event.counter_id,
                event.token,
                event.type.value,
            )

        case EventType.RESET:
            ok = state.apply_reset(event.group_id, event.raw)
            if not ok:
                logger.warning(
                    "RESET for unknown group %s | raw=%r",
                    event.group_id,
                    event.raw,
                )
                state.increment_error_count(event.raw)
                return
            logger.info("State: group %s reset", event.group_id)
