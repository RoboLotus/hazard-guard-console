"""Production integration without ROS/hardware or any motion publishers."""
from dataclasses import replace
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.rgb_adaptive import AdaptivePolicy, AdaptiveRgbSession, Observation, Profile
from app.rgb_adaptive_runtime import AdaptiveRgbRuntime
from app.ros_media import RosMediaAdapter
from app.stores import MediaStore, SpatialStore


@pytest.fixture
def adapter(monkeypatch):
    np = pytest.importorskip("numpy")
    monkeypatch.setenv("HAZARD_GUARD_RGB_ADAPTIVE", "on")
    monkeypatch.setenv("HAZARD_GUARD_RGB_ADAPTIVE_LOG", "off")
    a = RosMediaAdapter(MediaStore(), SpatialStore(), lambda error: pytest.fail(error))
    a.configure(cv_bridge=SimpleNamespace(imgmsg_to_cv2=lambda message, **kw: message.pixels),
                tf_buffer=None, ros_time_type=None)
    a._thermal_stream_seen = True  # Only RGB under test; no synthetic fallback.
    frame = SimpleNamespace(width=640, height=480, pixels=np.zeros((480, 640, 3), np.uint8))
    try:
        yield a, frame
    finally:
        a.close()


def until(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate()


def test_adaptive_idle_no_encoding_or_extra_legacy_work(adapter):
    a, frame = adapter
    a.on_rgb_image(frame)
    assert a.adaptive_rgb.media_status()["available"]
    assert a.adaptive_rgb.media_status()["adaptive"]
    assert a.adaptive_rgb.session.thread is None
    assert a._rgb_worker.thread is None
    assert a.media.get("rgb") is None
    a.adaptive_rgb.session.add_client("view", False)
    a.on_rgb_image(frame)
    until(lambda: a.adaptive_rgb.session.latest() is not None)
    assert a.adaptive_rgb.session.latest()["codec"] == "jpeg"
    assert a.media.get("rgb") is None
    a.adaptive_rgb.demand_legacy()
    a.on_rgb_image(frame)
    until(lambda: a.media.get("rgb") is not None)
    assert a.media.get("rgb")["content"].startswith(b"\xff\xd8")
    a.adaptive_rgb.legacy_until = 0
    assert not a.adaptive_rgb.needs_legacy()


def test_status_expires_and_restart_uses_new_epoch_namespace(adapter):
    a, frame = adapter
    a.on_rgb_image(frame)
    a.adaptive_rgb.input["received"] -= 3
    assert not a.adaptive_rgb.media_status()["available"]
    session_id = a.adaptive_rgb.session.session
    a.close()
    assert not a.adaptive_rgb.media_status()["available"]
    a.configure(cv_bridge=a._cv_bridge, tf_buffer=None, ros_time_type=None)
    a.on_rgb_image(frame)
    assert a.adaptive_rgb.session.session != session_id
    assert a.adaptive_rgb.media_status()["available"]


def test_unsupported_geometry_and_disabled_mode_preserve_legacy(adapter, monkeypatch):
    a, frame = adapter
    frame.width = 320
    frame.height = 240
    frame.pixels = frame.pixels[:240, :320]
    a.on_rgb_image(frame)
    until(lambda: a.media.get("rgb") is not None)
    assert not a.adaptive_rgb.media_status()["adaptive"]
    assert a.adaptive_rgb.session.thread is None
    monkeypatch.setenv("HAZARD_GUARD_RGB_ADAPTIVE", "off")
    legacy = AdaptiveRgbRuntime(lambda x: x)
    assert legacy.session is None and legacy.needs_legacy()
    assert legacy.media_status() is None
    legacy.close()


def test_thermal_source_preserved_and_not_advertised_as_adaptive(adapter):
    a, frame = adapter
    a._thermal_stream_seen = False
    a.on_rgb_image(frame)
    until(lambda: a.media.get("thermal") is not None)
    assert a.media.get("thermal")["source"] == "derived:rgb-colormap"
    assert a.media.get("rgb") is None  # No RGB consumers; only original thermal fallback runs.


def test_h264_waits_for_next_pull_instead_of_encoding_unusable_references():
    np = pytest.importorskip("numpy")
    class Encoder:
        @staticmethod
        def h264_available(): return True
        def encode(self, frame, *args): return b"frame", True
    s = AdaptiveRgbSession(mode="h264", encoder=Encoder())
    s.add_client("slow", True)
    try:
        s.submit(np.zeros((480, 640, 3), np.uint8))
        time.sleep(.12)
        assert s.encoded == 0
        s.waiting("slow", True)
        until(lambda: s.encoded == 1)
        s.waiting("slow", False)
        for i in range(20): s.submit(i)
        time.sleep(.15)
        assert s.encoded == 1 and s.snapshot()["pending_frames"] == 1
    finally:
        s.close()


def test_repeated_reference_recovery_falls_back_without_fifo():
    clock = [0.0]
    s = AdaptiveRgbSession(mode="h264", clock=lambda: clock[0])
    s.add_client("slow", True)
    for i in range(12):
        clock[0] = i * .3
        s.request_key()
    s.evaluate(20)
    assert s.policy.profile.codec == "jpeg"
    assert s.policy.events[-1]["reason"] == "reference_recovery_pressure"
    assert s.policy.blocked_until > clock[0]
    s.close()


def test_accepted_h264_does_not_penalize_stable_rtt_repeatedly():
    p = AdaptivePolicy()
    pressure = Observation(20, 200, 280, 2, 20000, 6)
    for t in [0, 2, 4]: p.observe(pressure, True, t)
    accepted = replace(pressure, bytes_per_frame=5000)
    p.observe(accepted, True, 12)
    for t in range(14, 46, 2): p.observe(accepted, True, t)
    assert p.profile == Profile(codec="h264")
    for t in [46, 48, 50]: p.observe(replace(accepted, ack_ms=350, age_ms=400), True, t)
    assert p.profile.bitrate == 400000


def test_actual_production_routes_stream_and_fallback_without_ros(adapter, monkeypatch):
    from app import main
    a, frame = adapter
    monkeypatch.setattr(main.ros_bridge, "_media_adapter", a)
    monkeypatch.setattr(main, "media_store", a.media)
    stop = threading.Event()
    def feed():
        while not stop.wait(.03): a.on_rgb_image(frame)
    thread = threading.Thread(target=feed, daemon=True)
    thread.start()
    # Do NOT enter app lifespan: the real bridge starts devices there.
    client = TestClient(main.app)
    try:
        until(lambda: a.adaptive_rgb.media_status() is not None)
        assert client.get("/api/v1/media/status").json()["rgb"]["adaptive"]
        assert client.get("/api/v1/media/rgb/adaptive").json()["enabled"]
        with client.websocket_connect("/ws/media/rgb/adaptive", headers={"origin": "http://testserver"}) as ws:
            ws.send_json({"h264": False})
            ws.send_json({})
            data = ws.receive_bytes()
            length = int.from_bytes(data[:4], "big")
            meta = json.loads(data[4:4 + length])
            assert meta["codec"] == "jpeg" and data[4 + length:][:2] == b"\xff\xd8"
            assert meta["age_ms"] < 500
        until(lambda: not a.adaptive_rgb.session.clients)
        snapshot = client.get("/api/v1/media/rgb")
        assert snapshot.status_code == 200 and snapshot.content[:2] == b"\xff\xd8"
        assert client.get("/api/v1/media/rgb/pipeline").json()["adaptive"]["encoded"] > 0
    finally:
        stop.set()
        thread.join(1)


def test_bad_hello_does_not_crash_or_leak_client():
    import asyncio
    from app.rgb_adaptive_transport import AdaptiveHub
    from test_rgb_adaptive import FakeSocket
    for value in ["null", "[]", "0", '"string"', 'x' * 1025]:
        s = AdaptiveRgbSession()
        hub = AdaptiveHub(s, ["http://localhost:5173"])
        ws = FakeSocket([value])
        asyncio.run(hub.serve(ws))
        assert ws.closed and not s.clients and hub.protocol_errors == 1
        s.close()


def test_disconnect_during_close_is_normal_on_jetson_starlette():
    import asyncio
    from starlette.websockets import WebSocketDisconnect
    from app.rgb_adaptive_transport import AdaptiveHub
    from test_rgb_adaptive import FakeSocket
    class DisconnectedSocket(FakeSocket):
        async def close(self, code=None):
            raise WebSocketDisconnect(1006)
    s = AdaptiveRgbSession()
    ws = DisconnectedSocket([json.dumps({"h264": False})])
    asyncio.run(AdaptiveHub(s, ["http://localhost:5173"]).serve(ws))
    assert not s.clients
    s.close()
