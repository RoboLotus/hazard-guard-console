"""Experiment-only pull-over-WebSocket: one frame in flight, no per-client queue."""
import asyncio
import json
import re
import struct


def cursor(text):
    if len(text) > 512:
        raise ValueError("oversized request")
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {"session", "after"}:
        raise ValueError("invalid keys")
    session, after = value["session"], value["after"]
    if not isinstance(session, str) or not re.fullmatch(r"(?:[a-f0-9]{32})?", session):
        raise ValueError("invalid session")
    if type(after) is not int or not 0 <= after <= 9007199254740991:
        raise ValueError("invalid sequence")
    return session, after


def packet(response):
    meta = json.dumps({"status": response.status_code, "headers": dict(response.headers)}, separators=(",", ":")).encode()
    return struct.pack("!I", len(meta)) + meta + response.body


async def serve_latest(ws, get_response):
    try:
        while True:
            session, after = cursor(await asyncio.wait_for(ws.receive_text(), 5))
            response = await get_response(session, after)
            # A slow receiver cannot grow a Python frame queue. Next frame is
            # selected only after a new client request following decode/display.
            await asyncio.wait_for(ws.send_bytes(packet(response)), 2)
    except (ValueError, asyncio.TimeoutError):
        await ws.close(code=1008)
