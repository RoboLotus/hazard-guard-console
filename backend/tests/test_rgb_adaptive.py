import asyncio
from dataclasses import replace
import json
import time

import pytest

from app.rgb_adaptive import AdaptivePolicy, AdaptiveRgbSession, Observation, Profile, SharedEncoder
from app.rgb_adaptive_transport import AdaptiveHub, avc_codec


GOOD = Observation(30, 30, 100, 3, 20_000, 5)
PRESSURE = replace(GOOD, ack_ms=200, age_ms=280)


def test_sustained_pressure_switches_but_not_one_spike():
    p = AdaptivePolicy()
    assert not p.observe(PRESSURE, True, 0)
    assert not p.observe(PRESSURE, True, 1)  # Same window cannot multiply votes.
    assert not p.observe(PRESSURE, True, 2)
    assert p.observe(PRESSURE, True, 4)
    assert p.profile.codec == 'h264'
    assert p.trial is not None
    p.observe(replace(GOOD, bytes_per_frame=5000), True, 12)
    assert p.trial is None
    assert p.events[-1]['reason'] == 'h264_trial_accepted'


@pytest.mark.parametrize('cpu,available', [(None, True), (70, True), (30, False)])
def test_no_unjustified_h264_trial(cpu, available):
    p = AdaptivePolicy()
    for t in [0, 2, 4]:
        p.observe(replace(PRESSURE, cpu=cpu), available, t)
    assert p.profile.codec == 'jpeg'
    assert p.profile.quality == 70


@pytest.mark.parametrize('sample,reason', [
    (replace(GOOD, cpu=90), 'cpu_or_encoder_budget'),
    (replace(GOOD, age_ms=700), 'h264_trial_freshness_regression'),
    (replace(GOOD, bytes_per_frame=19000), 'h264_trial_no_byte_saving'),
])
def test_h264_trial_rolls_back_and_cools_down(sample, reason):
    p = AdaptivePolicy()
    for t in [0, 2, 4]:
        p.observe(PRESSURE, True, t)
    assert p.observe(sample, True, 12)
    assert p.profile.codec == 'jpeg'
    assert p.events[-1]['reason'] == reason
    for t in [22, 24, 26]:
        p.observe(PRESSURE, True, t)
    assert p.profile.codec == 'jpeg'


def test_cpu_safety_and_slow_recovery():
    p = AdaptivePolicy()
    p.observe(replace(GOOD, cpu=90), True, 0)
    assert p.profile.fps == 5
    for t in range(2, 20, 2):
        p.observe(GOOD, True, t)
    assert p.profile.fps == 5
    p.observe(GOOD, True, 20)
    assert p.profile.fps == 8
    for t in range(22, 42, 2):
        p.observe(GOOD, True, t)
    assert p.profile.fps == 10


def test_client_decode_pressure_does_not_select_h264():
    p = AdaptivePolicy()
    for t in [0, 2, 4]:
        p.observe(replace(PRESSURE, decode_ms=150), True, t)
    assert p.profile.codec == 'jpeg' and p.profile.fps == 8


def test_idle_and_bounded_session():
    s = AdaptiveRgbSession()
    s.submit(object())
    assert s.thread is None
    for i in range(16):
        s.add_client(str(i), False)
    with pytest.raises(ValueError):
        s.add_client('17', True)
    s.evaluate(99)
    assert s.policy.profile.fps == 5  # Works without ACK samples.
    for i in range(16):
        s.remove_client(str(i))
    assert s.current is s.pending is None
    s.close()


def test_latest_worker_encodes_real_jpeg_and_stops():
    np = pytest.importorskip('numpy')
    s = AdaptiveRgbSession()
    s.add_client('a', False)
    for _ in range(20):
        s.submit(np.zeros((480, 640, 3), np.uint8))
    deadline = time.monotonic() + 2
    while s.latest() is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert s.latest()['data'].startswith(b'\xff\xd8')
    assert s.snapshot()['pending_frames'] <= 1
    s.close()
    assert not s.thread.is_alive()
    assert s.latest() is None


def test_real_h264_key_and_delta_decoder_recovery():
    av = pytest.importorskip('av')
    np = pytest.importorskip('numpy')
    encoder = SharedEncoder()
    if not encoder.h264_available():
        pytest.skip('libx264 unavailable')
    frames = []
    for sequence in range(1, 5):
        data, key = encoder.encode(np.full((480, 640, 3), sequence * 40, np.uint8),
                                   Profile(codec='h264'), 1, sequence, force_key=sequence == 4)
        frames.append((data, key))
    assert frames[0][1] and not frames[1][1] and frames[3][1]
    assert avc_codec(frames[0][0]).startswith('avc1.')
    decoder = av.CodecContext.create('h264', 'r')
    for data, _ in frames[:2]:
        decoded = decoder.decode(av.Packet(data))
        assert len(decoded) == 1 and decoded[0].width == 640
    # Frame 3 is deliberately lost. Fresh decoder can start directly at key 4.
    recovered = av.CodecContext.create('h264', 'r').decode(av.Packet(frames[3][0]))
    assert len(recovered) == 1
    assert abs(float(recovered[0].to_ndarray(format='bgr24').mean()) - 160) < 5
    data, key = encoder.encode(np.zeros((480, 640, 3), np.uint8),
                              Profile(codec='h264', bitrate=400_000), 2, 5)
    assert key and avc_codec(data)


class FakeSocket:
    def __init__(self, messages, origin='http://localhost:5173'):
        self.messages = iter(messages)
        self.headers = {'origin': origin}
        self.sent = []
        self.closed = False
    async def accept(self): pass
    async def close(self, code=None): self.closed = True
    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect
        try:
            return next(self.messages)
        except StopIteration:
            raise WebSocketDisconnect()
    async def send_bytes(self, value): self.sent.append(value)


def test_transport_rejects_origin_and_bad_ack_and_releases_client():
    s = AdaptiveRgbSession()
    h = AdaptiveHub(s, ['http://localhost:5173'])
    foreign = FakeSocket([], origin='http://untrusted')
    asyncio.run(h.serve(foreign))
    assert foreign.closed and not foreign.sent
    s.current = {'session': s.session, 'epoch': 1, 'sequence': 1, 'codec': 'jpeg',
                 'key': True, 'received': time.monotonic(), 'profile': {}, 'data': b'jpeg'}
    ws = FakeSocket([json.dumps({'h264': False}), '{}', json.dumps({'ack': {'token': 'wrong', 'decode_ms': 0}})])
    asyncio.run(h.serve(ws))
    assert len(ws.sent) == 1 and h.protocol_errors == 1
    assert not s.clients
    s.close()


def test_invalid_measurements():
    with pytest.raises(ValueError):
        AdaptivePolicy().observe(replace(GOOD, cpu=600), True)
    with pytest.raises(ValueError):
        AdaptivePolicy().observe(replace(GOOD, age_ms=float('nan')), True)


def test_live_transport_jpeg_h264_jpeg_same_connection():
    """Actual encoders + websocket + ACKs; policy inputs deterministic, not a load test."""
    pytest.importorskip('av')
    from fastapi.testclient import TestClient
    from scripts.rgb_adaptive_experiment import create_app
    app = create_app()
    s = app.state.session
    if not s.h264:
        pytest.skip('libx264 unavailable')
    def receive(ws, codec):
        for _ in range(30):
            payload = ws.receive_bytes()
            size = int.from_bytes(payload[:4], 'big')
            meta = json.loads(payload[4:4 + size])
            if meta['status'] == 200:
                if meta['codec'] == codec:
                    return meta, payload[4 + size:]
                ws.send_json({'ack': {'token': meta['token'], 'decode_ms': 1}})
            else:
                ws.send_json({})
        pytest.fail('requested codec never arrived')
    with TestClient(app) as client:
        with client.websocket_connect('/ws/bench/rgb-adaptive', headers={'origin': 'http://localhost:5173'}) as ws:
            ws.send_json({'h264': True})
            ws.send_json({})
            first, data = receive(ws, 'jpeg')
            assert data[:2] == b'\xff\xd8'
            with s.condition:
                now = time.monotonic()
                for offset in [-4, -2, 0]:
                    s.policy.observe(PRESSURE, True, now + offset)
                s.current = None
            ws.send_json({'ack': {'token': first['token'], 'decode_ms': 1}})
            second, data = receive(ws, 'h264')
            assert second['key'] and second['epoch'] > first['epoch']
            assert avc_codec(data) == second['codec_string']
            with s.condition:
                s.policy.observe(replace(GOOD, cpu=90), True, now + 3)
                s.current = None
            ws.send_json({'ack': {'token': second['token'], 'decode_ms': 1}})
            third, data = receive(ws, 'jpeg')
            assert third['epoch'] > second['epoch'] and data[:2] == b'\xff\xd8'
        assert not s.clients


def test_profile_fixed_arm_does_not_adapt_to_ack_pressure():
    for mode in ['jpeg', 'h264']:
        p = AdaptivePolicy(mode)
        for t in range(0, 40, 2):
            p.observe(PRESSURE, True, t)
        assert p.profile == Profile(codec=mode)


def test_join_never_receives_delta_without_reference():
    s = AdaptiveRgbSession(mode='h264')
    s.h264 = True
    s.current = {'session': s.session, 'epoch': 1, 'sequence': 20, 'codec': 'h264',
                 'key': False, 'received': time.monotonic(), 'profile': {}, 'data': b'delta'}
    ws = FakeSocket([json.dumps({'h264': True}), '{}'])
    h = AdaptiveHub(s, ['http://localhost:5173'])
    asyncio.run(h.serve(ws))
    assert s.key_requests > 0
    for packet in ws.sent:
        n = int.from_bytes(packet[:4], 'big')
        assert json.loads(packet[4:4+n])['status'] != 200
    assert not s.clients
    s.close()


def test_old_codec_ack_does_not_pollute_new_trial():
    s = AdaptiveRgbSession()
    s.add_client('a', True)
    s.policy.change(Profile(codec='h264'), 'test', time.monotonic())
    for _ in range(5):
        s.feedback('a', ack_ms=200, age_ms=300, decode_ms=1, frame_bytes=20000, epoch=1)
    s.evaluate(30)
    assert len(s.windows) == 0
    s.close()
