import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import stream_observability as module
from app.ros_media import RosMediaAdapter
from app.stores import MediaStore, SpatialStore


def report(**overrides):
    value = dict(
        client_id="a" * 32, session_id="b" * 32, sequence=1, reference="ingress",
        window_ms=5000, observed_ms=5000, missing_ms=0, stale_ms=1000,
        hidden_ms=0, unobserved_ms=0, max_gap_ms=1300, uncertainty_max_ms=40,
        frames_loaded=16, unique_frames=15, request_errors=0, report_errors=0,
        metadata_errors=0,
        age=dict(samples=2, mean_ms=125, p95_ms=200, max_ms=200, histogram=[1, 0, 1] + [0] * 12),
        detail_age_ms=[],
    )
    value.update(overrides)
    return value


@pytest.fixture
def api(monkeypatch):
    store = module.StreamDiagnostics(persist=False)
    monkeypatch.setattr(module, "diagnostics", store)
    monkeypatch.setenv("HAZARD_GUARD_STREAM_DIAGNOSTICS", "basic")
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app), store


def test_api_accepts_bounded_report_and_does_not_accept_free_text(api):
    client, store = api
    assert client.post("/api/v1/stream-observability/reports", json=report()).status_code == 202
    result = client.get("/api/v1/stream-observability").json()
    assert result["clients"][0]["report_state"] == "reporting"
    invalid = report(token="secret-never-echo")
    response = client.post("/api/v1/stream-observability/reports", json=invalid)
    assert response.status_code == 422
    assert "secret-never-echo" not in response.text
    assert len(store.clients) == 1


@pytest.mark.parametrize("payload", [
    report(window_ms=-1), report(age=dict(samples=0, mean_ms=0, p95_ms=None, max_ms=None, histogram=[0] * 15)),
    report(observed_ms=8000), report(unique_frames=99), report(client_id="../../escape"),
    report(detail_age_ms=[1] * 51), report(uncertainty_max_ms=float("inf")),
])
def test_invalid_reports_rejected(api, payload):
    client, _ = api
    assert client.post("/api/v1/stream-observability/reports", content=json.dumps(payload)).status_code == 422


def test_large_body_and_off_mode(api, monkeypatch):
    client, _ = api
    assert client.post("/api/v1/stream-observability/reports", content="x" * 8193).status_code == 413
    monkeypatch.setenv("HAZARD_GUARD_STREAM_DIAGNOSTICS", "off")
    assert client.post("/api/v1/stream-observability/reports", json=report()).status_code == 404


def test_rate_sequence_caps_report_missing_and_expiry(monkeypatch):
    now = [0]
    store = module.StreamDiagnostics(persist=False, clock=lambda: now[0], max_clients=1)
    assert store.accept(module.BrowserReport(**report()))
    assert not store.accept(module.BrowserReport(**report(sequence=2)))
    now[0] = 5
    assert not store.accept(module.BrowserReport(**report()))
    assert store.accept(module.BrowserReport(**report(sequence=2, detail_age_ms=[5])))
    assert store.snapshot()["clients"][0]["detail_age_ms"] == []
    assert not store.accept(module.BrowserReport(**report(client_id="c" * 32)))
    now[0] = 21
    assert store.snapshot()["clients"][0]["report_state"] == "report_missing"
    now[0] = 306
    assert store.snapshot()["clients"] == []
    assert store.accept(module.BrowserReport(**report(client_id="c" * 32)))


def test_missing_is_not_zero_latency(api):
    client, _ = api
    value = report(session_id=None, reference="unavailable", missing_ms=5000, stale_ms=0,
                   age=dict(samples=0, mean_ms=None, p95_ms=None, max_ms=None, histogram=[0] * 15))
    assert client.post("/api/v1/stream-observability/reports", json=value).status_code == 202
    assert client.get("/api/v1/stream-observability").json()["clients"][0]["age"]["p95_ms"] is None


def test_frame_metadata_atomic_and_not_tied_to_requests(monkeypatch):
    media = MediaStore()
    message = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=int(time.time()), nanosec=0)))
    meta = module.rgb_receive_metadata(message)
    media.update("rgb", b"frame1", "image/jpeg", width=1, height=1, source="ros:/rgb", metadata=meta)
    first = media.get("rgb")
    one = json.loads(module.frame_header(first)[module.HEADER])
    two = json.loads(module.frame_header(media.get("rgb"))[module.HEADER])
    assert one["n"] == two["n"]
    assert one["capture_age_ms"] is None  # Unix-looking timestamps are not proof.
    assert one["reference"] == "ingress"
    media.clear("rgb")
    media.update("rgb", b"frame2", "image/jpeg", width=1, height=1, source="ros:/rgb")
    assert media.get("rgb")["frame_sequence"] > first["frame_sequence"]
    assert first["content"] == b"frame1"
    assert MediaStore()._stream_session != first["stream_session"]
    monkeypatch.setenv("HAZARD_GUARD_STREAM_DIAGNOSTICS", "off")
    assert module.frame_header(first) == {}
    assert module.rgb_receive_metadata(message) == {}


def test_verified_stamp_and_invalid_ros_clock(monkeypatch):
    monkeypatch.setenv("HAZARD_GUARD_RGB_STAMP_CLOCK", "unix_verified")
    message = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=int(time.time()), nanosec=0)))
    media = MediaStore()
    media.update("rgb", b"x", "image/jpeg", width=1, height=1, source="ros:/rgb", metadata=module.rgb_receive_metadata(message))
    frame = json.loads(module.frame_header(media.get("rgb"))[module.HEADER])
    assert frame["capture_age_ms"] >= frame["age_ms"]
    message.header.stamp.sec = 0
    assert module.rgb_receive_metadata(message)["ros_stamp_ms"] is None
    message.header.stamp.nanosec = -1
    assert module.rgb_receive_metadata(message)["ros_stamp_ms"] is None


def test_rgb_adapter_preserves_stamp_and_pixels(monkeypatch):
    import cv2
    import numpy as np
    media = MediaStore()
    adapter = RosMediaAdapter(media, SpatialStore(), lambda e: pytest.fail(e))
    adapter._thermal_stream_seen = True
    adapter.configure(cv_bridge=SimpleNamespace(imgmsg_to_cv2=lambda *a, **k: np.full((8, 8, 3), 128, dtype=np.uint8)), tf_buffer=None, ros_time_type=None)
    adapter.on_rgb_image(SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=1))))
    deadline = time.monotonic() + 2
    while media.get("rgb") is None and time.monotonic() < deadline:
        time.sleep(0.005)
    adapter.close()
    stored = media.get("rgb")
    assert stored["metadata"]["ros_stamp_ms"] > 100000
    decoded = cv2.imdecode(np.frombuffer(stored["content"], np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (8, 8, 3)
    assert int(decoded.mean()) == 128


def test_writer_creates_only_bounded_structured_log(tmp_path):
    store = module.StreamDiagnostics(log_dir=tmp_path)
    try:
        assert store.accept(module.BrowserReport(**report()))
        path = tmp_path / "windows.jsonl"
        deadline = time.monotonic() + 2
        while (not path.exists() or path.stat().st_size == 0) and time.monotonic() < deadline:
            time.sleep(0.01)
        data = json.loads(path.read_text())
        assert data["client_id"] == "a" * 32
        assert "content" not in data and "token" not in data
    finally:
        store.close()
    assert not store.worker.is_alive()


def test_disk_error_cannot_break_report_acceptance(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("existing")
    store = module.StreamDiagnostics(log_dir=target)
    try:
        assert store.accept(module.BrowserReport(**report()))
        store.worker.join(timeout=2)
        assert store.snapshot()["write_errors"] == 1
        assert store.pending.maxsize == 128
    finally:
        store.close()
