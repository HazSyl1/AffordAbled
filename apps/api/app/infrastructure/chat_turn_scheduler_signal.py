from __future__ import annotations

import asyncio

_wakeup_event: asyncio.Event | None = None
_status_waiters: dict[str, set[asyncio.Event]] = {}


def install_chat_turn_scheduler_wakeup(event: asyncio.Event) -> None:
    global _wakeup_event
    _wakeup_event = event


def clear_chat_turn_scheduler_wakeup(event: asyncio.Event) -> None:
    global _wakeup_event
    if _wakeup_event is event:
        _wakeup_event = None


def wake_chat_turn_scheduler() -> None:
    """Prompt the local durable-chat worker to claim a newly queued turn."""
    if _wakeup_event is not None:
        _wakeup_event.set()


def publish_chat_turn_status(turn_id: str) -> None:
    """Wake local SSE subscribers after a durable chat job changes state."""
    for waiter in list(_status_waiters.get(turn_id, set())):
        waiter.set()


async def wait_for_chat_turn_status(turn_id: str, *, timeout_seconds: float) -> bool:
    """Wait for a local state change; the caller still rechecks the database."""
    waiter = asyncio.Event()
    _status_waiters.setdefault(turn_id, set()).add(waiter)
    try:
        await asyncio.wait_for(waiter.wait(), timeout=max(0.1, timeout_seconds))
        return True
    except TimeoutError:
        return False
    finally:
        subscribers = _status_waiters.get(turn_id)
        if subscribers is not None:
            subscribers.discard(waiter)
            if not subscribers:
                _status_waiters.pop(turn_id, None)
