from __future__ import annotations

import asyncio

_wakeup_event: asyncio.Event | None = None


def install_recurring_scheduler_wakeup(event: asyncio.Event) -> None:
    """Register the active in-process worker's interruptible wait."""
    global _wakeup_event
    _wakeup_event = event


def clear_recurring_scheduler_wakeup(event: asyncio.Event) -> None:
    global _wakeup_event
    if _wakeup_event is event:
        _wakeup_event = None


def wake_recurring_scheduler() -> None:
    """Ask the local worker to recompute the database's earliest due rule now."""
    if _wakeup_event is not None:
        _wakeup_event.set()
