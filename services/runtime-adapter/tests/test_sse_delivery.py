from __future__ import annotations

import asyncio
import queue

from app.main import _AsyncSubscriberBridge


def test_many_idle_sse_subscribers_do_not_starve_new_events() -> None:
    async def scenario() -> None:
        subscribers = [queue.Queue() for _ in range(24)]
        bridges = [_AsyncSubscriberBridge(subscriber) for subscriber in subscribers]
        try:
            for index, subscriber in enumerate(subscribers):
                subscriber.put({"sequence": index + 1})
            delivered = await asyncio.wait_for(
                asyncio.gather(*(bridge.get() for bridge in bridges)), timeout=1.0,
            )
            assert [event["sequence"] for event in delivered if event is not None] == list(range(1, 25))
        finally:
            for bridge in bridges:
                bridge.close()

    asyncio.run(scenario())
