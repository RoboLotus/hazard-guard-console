"""Opt-in RGB display encoding and freshness-first policy.

Thresholds are hypotheses to validate,
not a claim that ACK turnaround measures available network bandwidth.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import math
import statistics
import threading
import time
import uuid


@dataclass(frozen=True)
class Profile:
    codec: str = "jpeg"
    fps: int = 10
    quality: int = 82
    bitrate: int = 800_000


@dataclass(frozen=True)
class Observation:
    # System average over all logical cores, NOT process one-core percent.
    cpu: float | None
    ack_ms: float
    age_ms: float
    decode_ms: float
    bytes_per_frame: float
    encode_ms: float


class AdaptivePolicy:
    """One decision per measured window, asymmetric recovery, bounded history."""
    def __init__(self, mode="auto", clock=time.monotonic):
        if mode not in {"auto", "jpeg", "h264"}:
            raise ValueError("mode must be auto, jpeg, or h264")
        self.mode, self.clock = mode, clock
        self.profile = Profile(codec="h264" if mode == "h264" else "jpeg")
        self.epoch = 1
        self.changed_at = -math.inf
        self.last_window = -math.inf
        self.blocked_until = 0.0
        self.bad = self.good = 0
        self.trial = None
        self.accepted_ack = None
        self.events = deque(maxlen=100)

    def change(self, profile, reason, now):
        if profile == self.profile:
            return False
        self.events.append({"at": now, "reason": reason, "from": asdict(self.profile),
                            "to": asdict(profile), "epoch": self.epoch + 1})
        self.profile = profile
        self.epoch += 1
        self.changed_at = now
        self.bad = self.good = 0
        return True

    def fallback(self, reason, now=None):
        now = self.clock() if now is None else now
        self.trial = None
        self.accepted_ack = None
        self.blocked_until = now + 60
        return self.change(Profile(fps=5, quality=70), reason, now)

    def observe(self, sample: Observation, h264_available: bool, now=None):
        now = self.clock() if now is None else now
        values = [sample.ack_ms, sample.age_ms, sample.decode_ms,
                  sample.bytes_per_frame, sample.encode_ms]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("invalid measurement")
        if sample.cpu is not None and (not math.isfinite(sample.cpu) or not 0 <= sample.cpu <= 100):
            raise ValueError("invalid system CPU")
        if self.profile.codec == "h264" and not h264_available:
            return self.fallback("h264_unavailable", now)
        if now - self.last_window < 2:
            return False
        self.last_window = now
        p = self.profile
        overloaded = ((sample.cpu is not None and sample.cpu >= 85)
                      or sample.encode_ms >= 750 / p.fps)
        if overloaded:
            self.trial = None
            if p.codec == "h264":
                return self.fallback("cpu_or_encoder_budget", now)
            return self.change(replace(p, fps=5, quality=min(p.quality, 70)), "cpu_or_encoder_budget", now)
        if self.mode != "auto":
            return False  # Fixed comparison arm; safety fallback still active.
        if self.trial is not None:
            baseline, until = self.trial
            if sample.age_ms > max(500, baseline.age_ms * 1.2) or sample.decode_ms > 100:
                return self.fallback("h264_trial_freshness_regression", now)
            if now >= until:
                self.trial = None
                if sample.bytes_per_frame >= baseline.bytes_per_frame * .85:
                    return self.fallback("h264_trial_no_byte_saving", now)
                self.events.append({"at": now, "reason": "h264_trial_accepted", "epoch": self.epoch})
                self.accepted_ack = sample.ack_ms
            return False
        network_pressure = sample.ack_ms > 140 and sample.decode_ms < 60
        # A stable RTT is not proof of bandwidth saturation. After a successful
        # byte-saving trial, do not repeatedly reduce quality/FPS for that same
        # RTT while frames remain fresh. Deterioration re-enables adjustment.
        if (p.codec == "h264" and self.accepted_ack is not None
                and sample.ack_ms <= self.accepted_ack * 1.2 and sample.age_ms < 300):
            network_pressure = False
        unhealthy = network_pressure or sample.age_ms > 500 or sample.decode_ms > 100
        healthy = sample.ack_ms < 100 and sample.age_ms < 300 and sample.decode_ms < 50
        self.bad = self.bad + 1 if unhealthy else 0
        self.good = self.good + 1 if healthy else 0
        if self.bad >= 3 and now - self.changed_at >= 10:
            if (p.codec == "jpeg" and network_pressure and h264_available
                    and sample.cpu is not None and sample.cpu < 65 and now >= self.blocked_until):
                self.trial = (sample, now + 8)
                return self.change(replace(p, codec="h264", bitrate=800_000), "delivery_pressure_h264_trial", now)
            if p.codec == "h264" and p.bitrate > 400_000 and network_pressure:
                return self.change(replace(p, bitrate=400_000), "delivery_pressure_bitrate", now)
            if p.codec == "jpeg" and p.quality > 55 and network_pressure:
                return self.change(replace(p, quality=70 if p.quality > 70 else 55), "delivery_pressure_quality", now)
            return self.change(replace(p, fps=8 if p.fps > 8 else 5), "freshness_reduce_fps", now)
        if self.good >= 10 and now - self.changed_at >= 20:
            if p.fps < 10:
                return self.change(replace(p, fps=8 if p.fps < 8 else 10), "healthy_restore_fps", now)
            if p.codec == "jpeg" and p.quality < 82:
                return self.change(replace(p, quality=70 if p.quality < 70 else 82), "healthy_restore_quality", now)
            if p.codec == "h264" and p.bitrate < 800_000:
                return self.change(replace(p, bitrate=800_000), "healthy_restore_bitrate", now)
        return False


class SharedEncoder:
    """Single worker owns the codec context. New profile => new epoch/keyframe."""
    def __init__(self):
        self.context = None
        self.config = None

    @staticmethod
    def h264_available():
        try:
            import av
            return "libx264" in av.codecs_available
        except ImportError:
            return False

    def encode(self, bgr, profile, epoch, sequence, force_key=False):
        import cv2
        if bgr.shape != (480, 640, 3) or str(bgr.dtype) != "uint8":
            raise ValueError("explicit 640x480 uint8 BGR input required; no silent resize")
        if profile.codec == "jpeg":
            self.context = self.config = None
            ok, data = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, profile.quality])
            if not ok:
                raise RuntimeError("JPEG encode failed")
            return bytes(data), True
        import av
        config = (profile, epoch)
        if self.config != config:
            c = av.CodecContext.create("libx264", "w")
            c.width, c.height, c.pix_fmt = 640, 480, "yuv420p"
            c.time_base, c.framerate = Fraction(1, 90_000), Fraction(profile.fps, 1)
            c.thread_count, c.gop_size, c.max_b_frames = 2, profile.fps, 0
            c.bit_rate = profile.bitrate
            kbps = profile.bitrate // 1000
            c.options = {"preset": "ultrafast", "tune": "zerolatency", "profile": "baseline",
                         "level": "3.0", "x264-params":
                         f"keyint={profile.fps}:min-keyint=1:scenecut=0:repeat-headers=1:annexb=1:"
                         f"bframes=0:rc-lookahead=0:vbv-maxrate={kbps}:vbv-bufsize={kbps}"}
            c.open()
            self.context, self.config = c, config
            force_key = True
        frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
        # Nominal codec cadence follows the selected FPS. Profile changes reset
        # the context/epoch. Sensor ingress elapsed time is separate metadata.
        frame.pts, frame.time_base = round(sequence * 90_000 / profile.fps), Fraction(1, 90_000)
        if force_key:
            frame.pict_type = av.video.frame.PictureType.I
        packets = self.context.encode(frame)
        if len(packets) != 1:
            raise RuntimeError("zero-delay single access unit required")
        return bytes(packets[0]), bool(packets[0].is_keyframe)


class AdaptiveRgbSession:
    """One shared codec, latest input/output only, idle work suppressed.

    All connected viewers must support H264 to select it. Aggregate equal-weight
    per-view medians (not a guarantee for every individual slow viewer).
    No per-view encoder and no unbounded backlog.
    """
    def __init__(self, mode="auto", converter=lambda x: x, clock=time.monotonic, encoder=None):
        self.clock, self.converter = clock, converter
        self.policy = AdaptivePolicy(mode, clock)
        self.encoder = encoder or SharedEncoder()
        self.h264 = self.encoder.h264_available()
        self.session = uuid.uuid4().hex
        self.condition = threading.Condition(threading.RLock())
        self.pending = self.current = None
        self.clients = {}
        self.thread = None
        self.stopped = False
        self.sequence = 0
        self.force_key = False
        self.last_key_request = -math.inf
        self.last_evaluation = -math.inf
        self.encode_ms = 0.0
        self.cpu = None
        self.received = self.replaced = self.encoded = self.failures = self.expired = 0
        self.bytes_encoded = self.bytes_sent = self.acks = self.key_requests = 0
        self.last_error = None
        self.windows = deque(maxlen=300)
        self.key_times = deque(maxlen=100)

    def add_client(self, key, h264):
        with self.condition:
            if len(self.clients) >= 16:
                raise ValueError("viewer limit")
            if self.stopped:
                raise ValueError("session stopped")
            self.clients[key] = {"h264": bool(h264), "waiting": False, "samples": deque(maxlen=120)}
            if self.policy.profile.codec == "h264" and (not h264 or not self.h264):
                self.policy.fallback("viewer_decoder_unavailable")

    def remove_client(self, key):
        with self.condition:
            self.clients.pop(key, None)
            if not self.clients:
                self.pending = self.current = None

    def waiting(self, client, value):
        with self.condition:
            if client in self.clients:
                self.clients[client]["waiting"] = value
                self.condition.notify_all()

    def submit(self, frame, received=None):
        with self.condition:
            if self.stopped or not self.clients:
                return
            self.received += 1
            if self.pending is not None:
                self.replaced += 1
            self.pending = (frame, self.clock() if received is None else received)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="adaptive-rgb", daemon=True)
                self.thread.start()
            self.condition.notify()

    def request_key(self):
        with self.condition:
            now = self.clock()
            if now - self.last_key_request >= .25:
                self.force_key = True
                self.last_key_request = now
                self.key_requests += 1
                self.key_times.append(now)

    def _run(self):
        next_at = 0.0
        while True:
            with self.condition:
                while not self.stopped:
                    delay = next_at - self.clock()
                    ready = (self.policy.profile.codec != "h264"
                             or any(c["waiting"] for c in self.clients.values()))
                    if self.pending is not None and delay <= 0 and ready:
                        break
                    self.condition.wait(max(.001, delay) if self.pending is not None and ready else None)
                if self.stopped:
                    return
                (frame, received), self.pending = self.pending, None
                p, epoch = self.policy.profile, self.policy.epoch
                force, self.force_key = self.force_key, False
                self.sequence += 1
                sequence = self.sequence
            started = self.clock()
            next_at = started + 1 / p.fps
            if started - received > .5:
                with self.condition:
                    self.expired += 1
                continue
            try:
                encode_started = time.perf_counter()
                data, key = self.encoder.encode(self.converter(frame), p, epoch, sequence, force)
                encode_elapsed_ms = (time.perf_counter() - encode_started) * 1000
                finished = self.clock()
                with self.condition:
                    self.encode_ms = encode_elapsed_ms
                    self.encoded += 1
                    self.bytes_encoded += len(data)
                    if self.stopped or finished - received > .5 or epoch != self.policy.epoch or not self.clients:
                        self.expired += 1
                        continue
                    self.current = {"session": self.session, "epoch": epoch, "sequence": sequence,
                                    "codec": p.codec, "key": key, "received": received,
                                    "profile": asdict(p), "data": data}
            except Exception as exc:
                with self.condition:
                    self.failures += 1
                    self.last_error = type(exc).__name__
                    self.current = None
                    if p.codec == "h264":
                        # Disable for this session; restart explicitly after fixing capability.
                        self.h264 = False
                        self.policy.fallback("encoder_failure")

    def latest(self):
        with self.condition:
            item = self.current
            if (item is None or self.clock() - item["received"] > .5
                    or item["epoch"] != self.policy.epoch):
                return None
            return item

    def feedback(self, client, *, ack_ms, age_ms, decode_ms, frame_bytes, epoch=None):
        values = (ack_ms, age_ms, decode_ms, frame_bytes)
        if any(not math.isfinite(v) or not 0 <= v <= 16_000_000 for v in values):
            raise ValueError("invalid feedback")
        with self.condition:
            if client in self.clients:
                measured_epoch = self.policy.epoch if epoch is None else epoch
                self.clients[client]["samples"].append((self.clock(), measured_epoch, *values))
                self.acks += 1

    def evaluate(self, cpu=None):
        with self.condition:
            now = self.clock()
            self.cpu = cpu
            if now - self.last_evaluation < 2:
                return
            self.last_evaluation = now
            # Different-paced viewers can repeatedly lose H264 references with
            # latest-only delivery. Bound recovery churn instead of queuing old
            # GOPs or spending CPU endlessly generating keyframes.
            if (self.policy.profile.codec == "h264"
                    and sum(now - t <= 10 for t in self.key_times) >= 12):
                self.policy.fallback("reference_recovery_pressure", now)
                self.current = None
                self.key_times.clear()
                return
            rows = []
            for client in self.clients.values():
                samples = [s[2:] for s in client["samples"]
                           if now - s[0] <= 2.5 and s[1] == self.policy.epoch]
                if len(samples) >= 3:
                    rows.append([statistics.median(col) for col in zip(*samples)])
            if not rows:
                # CPU protection must also work when clients cannot acknowledge.
                if cpu is not None and cpu >= 85 and self.clients:
                    self.policy.fallback("cpu_without_feedback", now)
                    self.current = None
                return  # Missing input/observations are not network congestion.
            ack, age, decode, size = [statistics.median(col) for col in zip(*rows)]
            sample = Observation(cpu, ack, age, decode, size, self.encode_ms)
            capable = self.h264 and all(c["h264"] for c in self.clients.values())
            changed = self.policy.observe(sample, capable, now)
            self.windows.append({"at": now, **asdict(sample), "profile": asdict(self.policy.profile),
                                 "epoch": self.policy.epoch, "measured_viewers": len(rows)})
            if changed:
                self.current = None

    def snapshot(self):
        with self.condition:
            return {"session": self.session, "profile": asdict(self.policy.profile), "epoch": self.policy.epoch,
                    "mode": self.policy.mode, "h264_available": self.h264, "clients": len(self.clients),
                    "received": self.received, "replaced": self.replaced, "encoded": self.encoded,
                    "expired": self.expired, "failures": self.failures, "last_error": self.last_error,
                    "pending_frames": int(self.pending is not None), "bytes_encoded": self.bytes_encoded,
                    "bytes_sent": self.bytes_sent, "acks": self.acks, "key_requests": self.key_requests,
                    "system_cpu_percent": self.cpu, "encode_ms": self.encode_ms,
                    "events": list(self.policy.events), "windows": list(self.windows)}

    def close(self):
        with self.condition:
            self.stopped = True
            self.pending = self.current = None
            self.condition.notify_all()
        if self.thread:
            self.thread.join(2)
