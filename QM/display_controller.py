"""
Display Controller (backend)

Builds a presentation model from Application State.
No UI framework dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app_state import ApplicationState


@dataclass(frozen=True, slots=True)
class CounterDisplay:
    id: int
    name: str
    token: str  # 4-digit zero-padded, or "----" if never called


@dataclass(frozen=True, slots=True)
class GroupDisplay:
    id: int
    name: str
    counters: List[CounterDisplay]


def format_token(token: Optional[int]) -> str:
    """Format a token for display. None → '----'."""
    if token is None:
        return "----"
    return f"{token:04d}"


def build_display_model(state: ApplicationState) -> List[GroupDisplay]:
    """
    Build the full display model for every configured group and counter.
    Order follows the state's group/counter insertion order (config order).
    """
    groups: List[GroupDisplay] = []
    for group in state.snapshot_groups().values():
        counters = [
            CounterDisplay(
                id=counter.id,
                name=counter.name,
                token=format_token(counter.current_token),
            )
            for counter in group.counters.values()
        ]
        groups.append(
            GroupDisplay(id=group.id, name=group.name, counters=counters)
        )
    return groups
