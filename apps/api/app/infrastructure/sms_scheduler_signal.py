from __future__ import annotations

import asyncio

_wakeup_event: asyncio.Event | None = None


def install_sms_scheduler_wakeup(event: asyncio.Event) -> None:
    global _wakeup_event
    _wakeup_event = event


def clear_sms_scheduler_wakeup(event: asyncio.Event) -> None:
    global _wakeup_event
    if _wakeup_event is event:
        _wakeup_event = None


def wake_sms_scheduler() -> None:
    if _wakeup_event is not None:
        _wakeup_event.set()
