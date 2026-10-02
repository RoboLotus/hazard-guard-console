import asyncio
import json
import struct
import threading
import time

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.rgb_stream import LatestRgbWorker, RgbSocketHub, display_fps, fresh_rgb, parse_cursor
from app.stores import MediaStore


def test_latest_worker_replaces_pending_input_and_closes():
    entered, release = threading.Event(), threading.Event()
    seen = []
    def encode(value, metadata):
        seen.append((value, metadata))
        if value == 0:
            entered.set()
            release.wait(2)
    worker = LatestRgbWorker(encode, fps=30)
    try:
        worker.submit(0, {"received_monotonic": 10})
        assert entered.wait(1)
        for value in range(1, 100):
            worker.submit(value, {})
        release.set()
        deadline = time.monotonic() + 1
        while len(seen) < 2 and time.monotonic() < deadline:
            time.sleep(.005)
        assert [x[0] for x in seen] == [0, 99]
        assert worker.replaced == 98
        assert seen[0][1]["received_monotonic"] == 10
    finally:
        release.set()
        worker.close()
    worker.submit(100, {})
    assert not worker.thread.is_alive()
    assert worker.pending is None


def test_worker_rate_and_error_recovery():
    seen = []
    def encode(value, _):
        seen.append(time.monotonic())
        if len(seen) == 1:
            raise ValueError("test failure")
    worker = LatestRgbWorker(encode, fps=10)
    try:
        until = time.monotonic() + .35
        while time.monotonic() < until:
            worker.submit(1, {})
            time.sleep(.003)
        assert 2 <= len(seen) <= 4
        assert all(b - a >= .09 for a, b in zip(seen, seen[1:]))
        assert worker.errors == 1
    finally:
        worker.close()


def test_settings_staleness_and_cursor(monkeypatch):
    for bad in ["nan", "0", "999", "oops"]:
        monkeypatch.setenv("HAZARD_GUARD_RGB_DISPLAY_FPS", bad)
        assert display_fps() == 10
    assert not fresh_rgb(None)
    item = {"updated_monotonic": 9, "metadata": {"received_monotonic": 1}}
    assert not fresh_rgb(item, 10)  # Newly encoded old input is not live.
    assert fresh_rgb(item, 2)
    for value in ['{}', '[]', '{"session":"","after":true}', '{"session":"bad","after":1}']:
        with pytest.raises(ValueError):
            parse_cursor(value)


def socket_app():
    app, store, hub = FastAPI(), MediaStore(), RgbSocketHub(limit=1)
    @app.websocket("/ws/media/rgb")
    async def stream(ws: WebSocket):
        await hub.serve(ws, store)
    return TestClient(app), store, hub


def receive(ws):
    data = ws.receive_bytes()
    length = struct.unpack("!I", data[:4])[0]
    return json.loads(data[4:4 + length]), data[4 + length:]


def put(store, content=b"jpeg", metadata=None):
    store.update("rgb", content, "image/jpeg", width=640, height=480, source="ros:/rgb", metadata=metadata)


def test_socket_latest_duplicate_sensor_loss_session_recovery_and_off_diagnostics(monkeypatch):
    client, store, hub = socket_app()
    monkeypatch.setenv("HAZARD_GUARD_STREAM_DIAGNOSTICS", "off")
    with client.websocket_connect("/ws/media/rgb", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"session": "", "after": 0})
        assert receive(ws)[0]["status"] == 503
        put(store)
        ws.send_json({"session": "", "after": 0})
        meta, body = receive(ws)
        assert body == b"jpeg" and meta["headers"] == {}
        ws.send_json({"session": meta["session"], "after": meta["sequence"]})
        assert receive(ws)[0]["status"] == 204
        put(store, metadata={"received_monotonic": time.monotonic() - 3})
        ws.send_json({"session": "", "after": 0})
        assert receive(ws)[0]["status"] == 503
        put(store, b"restored")
        ws.send_json({"session": "f" * 32, "after": 999999})
        assert receive(ws)[1] == b"restored"
    assert hub.active == 0


def test_origin_limit_invalid_request_and_feature_flag(monkeypatch):
    client, store, hub = socket_app()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/media/rgb", headers={"origin": "https://evil.example"}):
            pass
    with client.websocket_connect("/ws/media/rgb", headers={"origin": "http://testserver"}) as ws:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/media/rgb", headers={"origin": "http://testserver"}):
                pass
        ws.send_text("[]")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
    assert hub.active == 0
    monkeypatch.setenv("HAZARD_GUARD_RGB_WS", "off")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/media/rgb", headers={"origin": "http://testserver"}):
            pass


def test_slow_socket_send_timeout_releases_slot():
    class WS:
        headers = {"origin": "http://local", "host": "local"}
        async def accept(self): pass
        async def receive_text(self): return '{"session":"","after":0}'
        async def send_bytes(self, _): raise asyncio.TimeoutError
        async def close(self, code): self.code = code
    hub, ws = RgbSocketHub(), WS()
    asyncio.run(hub.serve(ws, MediaStore()))
    assert ws.code == 1008 and hub.active == 0


def test_real_routes_http_stale_and_ws_share_store(monkeypatch):
    from app import main
    store = MediaStore()
    monkeypatch.setattr(main, "media_store", store)
    client = TestClient(main.app)
    put(store, metadata={"received_monotonic": time.monotonic() - 3})
    assert client.get("/api/v1/media/rgb").status_code == 503
    assert not client.get("/api/v1/media/status").json()["rgb"]["available"]
    put(store, b"same-shared-jpeg")
    assert client.get("/api/v1/media/rgb").content == b"same-shared-jpeg"
    with client.websocket_connect("/ws/media/rgb", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"session": "", "after": 0})
        assert receive(ws)[1] == b"same-shared-jpeg"
        assert client.get("/api/v1/media/rgb/pipeline").json()["websocket_clients"] == 1


def test_adapter_can_be_configured_after_close():
    from app.ros_media import RosMediaAdapter
    from app.stores import SpatialStore
    adapter = RosMediaAdapter(MediaStore(), SpatialStore(), lambda _: None)
    old = adapter._rgb_worker
    adapter.close()
    adapter.configure(cv_bridge=object(), tf_buffer=None, ros_time_type=None)
    assert adapter._rgb_worker is not old
    assert not adapter._rgb_worker.stopped
    adapter.close()
