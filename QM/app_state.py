"""
Application State

Single source of truth for runtime queue state.
All updates go through methods on ApplicationState.

Counter/group changes are also announced through lightweight listener
callbacks (add_counter_listener / add_group_reset_listener) so a future
presentation layer (e.g. a PyQt6 UI) can react to exactly what changed
instead of re-reading and diffing the whole display model on every event.
This module has no UI framework dependency — listeners are plain callables.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from config_manager import DisplayConfig, GroupConfig
from logger import get_logger
from protocol_parser import EventType


@dataclass(slots=True)
class CounterState:
    id: int
    name: str
    current_token: Optional[int] = None  # None means never called (display as ----)
    last_event_type: Optional[EventType] = None
    last_updated: Optional[datetime] = None
    last_raw: Optional[str] = None
    status: str = "idle"


@dataclass(slots=True)
class GroupState:
    id: int
    name: str
    last_generated_token: Optional[int] = None
    total_tokens_generated: int = 0
    remaining: Optional[int] = None
    counters: Dict[int, CounterState] = field(default_factory=dict)


# Callback signatures for targeted change notifications.
CounterChangeListener = Callable[[int, int, CounterState], None]  # (group_id, counter_id, counter_snapshot)
GroupResetListener = Callable[[int], None]  # (group_id)


class ApplicationState:
    """Thread-safe application state. Initialize once from display configuration."""

    def __init__(self, display: DisplayConfig) -> None:
        self._lock = threading.Lock()
        self.error_count: int = 0
        self.last_raw_protocol: Optional[str] = None
        self.groups: Dict[int, GroupState] = {
            g.id: self._build_group(g) for g in display.groups
        }
        self._counter_listeners: List[CounterChangeListener] = []
        self._group_reset_listeners: List[GroupResetListener] = []

    @staticmethod
    def _build_group(group: GroupConfig) -> GroupState:
        counters = {
            c.id: CounterState(id=c.id, name=c.name) for c in group.counters
        }
        return GroupState(id=group.id, name=group.name, counters=counters)

    # ------------------------------------------------------------------
    # Mutations (return True if applied, False if target not found)
    # ------------------------------------------------------------------

    def apply_token_generated(self, group_id: int, token: int, raw: str) -> bool:
        with self._lock:
            group = self.groups.get(group_id)
            if group is None:
                return False
            group.last_generated_token = token
            group.total_tokens_generated = token
            self.last_raw_protocol = raw
            return True

    def apply_counter_event(
        self,
        group_id: int,
        counter_id: int,
        token: int,
        event_type: EventType,
        raw: str,
        remaining: Optional[int] = None,
    ) -> bool:
        """Update a single counter (NEXT or CALL). Notifies counter listeners on success."""
        with self._lock:
            group = self.groups.get(group_id)
            if group is None:
                return False
            counter = group.counters.get(counter_id)
            if counter is None:
                return False
            counter.current_token = token
            counter.last_event_type = event_type
            counter.last_updated = datetime.now(timezone.utc)
            counter.last_raw = raw
            counter.status = "active"
            if remaining is not None:
                group.remaining = remaining
            self.last_raw_protocol = raw
            snapshot = replace(counter)

        self._notify_counter_changed(group_id, counter_id, snapshot)
        return True

    def apply_reset(self, group_id: int, raw: str) -> bool:
        """Reset every counter in the given group. Other groups unchanged.
        Notifies group-reset listeners on success."""
        with self._lock:
            group = self.groups.get(group_id)
            if group is None:
                return False
            now = datetime.now(timezone.utc)
            for counter in group.counters.values():
                counter.current_token = None
                counter.last_event_type = EventType.RESET
                counter.last_updated = now
                counter.last_raw = raw
                counter.status = "idle"
            group.remaining = None
            self.last_raw_protocol = raw

        self._notify_group_reset(group_id)
        return True

    def increment_error_count(self, raw: Optional[str] = None) -> int:
        with self._lock:
            self.error_count += 1
            if raw is not None:
                self.last_raw_protocol = raw
            return self.error_count

    # ------------------------------------------------------------------
    # Change listeners (targeted notifications — no UI framework dependency)
    # ------------------------------------------------------------------

    def add_counter_listener(self, listener: CounterChangeListener) -> None:
        """Register a callback invoked as (group_id, counter_id, counter_snapshot)
        whenever a single counter is updated by a NEXT or CALL event."""
        self._counter_listeners.append(listener)

    def add_group_reset_listener(self, listener: GroupResetListener) -> None:
        """Register a callback invoked as (group_id) whenever a group is reset."""
        self._group_reset_listeners.append(listener)

    def _notify_counter_changed(self, group_id: int, counter_id: int, counter: CounterState) -> None:
        for listener in self._counter_listeners:
            try:
                listener(group_id, counter_id, counter)
            except Exception:
                get_logger().exception("counter_listener callback failed")

    def _notify_group_reset(self, group_id: int) -> None:
        for listener in self._group_reset_listeners:
            try:
                listener(group_id)
            except Exception:
                get_logger().exception("group_reset_listener callback failed")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_group(self, group_id: int) -> Optional[GroupState]:
        with self._lock:
            return self.groups.get(group_id)

    def get_counter(self, group_id: int, counter_id: int) -> Optional[CounterState]:
        with self._lock:
            group = self.groups.get(group_id)
            if group is None:
                return None
            return group.counters.get(counter_id)

    def snapshot_groups(self) -> Dict[int, GroupState]:
        """Return a shallow copy of the groups dict for safe iteration."""
        with self._lock:
            return dict(self.groups)
