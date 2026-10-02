"""Experiment-only latest-frame notification. No frame queue or ROS dependency."""
import asyncio
import time


class FrameSignal:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.event = asyncio.Event()
        self.waiters = 0

    def notify(self):
        # Called by the ROS thread only after the encoded cache has been updated.
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.event.set)

    async def newer(self, get, session, after, timeout=1.0):
        deadline = time.monotonic() + timeout
        self.waiters += 1
        try:
            while True:
                # Clear before reading; a publisher between clear/read or
                # read/wait leaves the event set. All current waiters wake.
                self.event.clear()
                item = get()
                if item and time.monotonic() - item['updated_monotonic'] > 5:
                    return None
                if item and (item['stream_session'] != session or item['frame_sequence'] > after):
                    return item
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self.event.wait(), remaining)
                except asyncio.TimeoutError:
                    return None
        finally:
            self.waiters -= 1
