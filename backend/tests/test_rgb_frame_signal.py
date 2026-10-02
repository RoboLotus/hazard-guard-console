import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from rgb_frame_signal import FrameSignal


def test_latest_only_session_change_stale_timeout_and_cancellation():
    async def run():
        signal = FrameSignal()
        item = {'stream_session': 'a', 'frame_sequence': 2, 'updated_monotonic': time.monotonic()}
        get = lambda: dict(item)
        assert (await signal.newer(get, 'a', 1))['frame_sequence'] == 2
        assert await signal.newer(get, 'a', 2, .01) is None
        assert (await signal.newer(get, 'old-session', 999))['frame_sequence'] == 2
        tasks = [asyncio.create_task(signal.newer(get, 'a', 2)) for _ in range(12)]
        await asyncio.sleep(.01)
        item['frame_sequence'] = 9  # intermediate frames are never queued
        await asyncio.to_thread(signal.notify)
        assert all(x['frame_sequence'] == 9 for x in await asyncio.gather(*tasks))
        pending = asyncio.create_task(signal.newer(get, 'a', 9))
        await asyncio.sleep(.01)
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        assert signal.waiters == 0
        item['updated_monotonic'] -= 10
        assert await signal.newer(get, 'different', 0) is None
    asyncio.run(run())
