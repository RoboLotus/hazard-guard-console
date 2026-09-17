"""Shared pull/ACK transport for the experiment and opt-in production routes."""
import asyncio
import json
import math
import time
import uuid

from starlette.websockets import WebSocketDisconnect


def avc_codec(data):
    """Read profile/compatibility/level from an Annex-B SPS, not a guessed codec."""
    import re
    for part in re.split(b"\x00\x00\x01", data):
        if len(part) >= 4 and part[0] & 31 == 7:
            return "avc1." + part[1:4].hex().upper()
    return None


def pack(meta, data=b""):
    header = json.dumps(meta, separators=(",", ":"), allow_nan=False).encode()
    return len(header).to_bytes(4, "big") + header + data


class AdaptiveHub:
    def __init__(self, session, origins=(), origin_check=None):
        self.session, self.origins = session, set(origins)
        self.origin_check = origin_check
        self.timeouts = self.protocol_errors = 0

    async def serve(self, ws):
        # This is origin isolation, NOT authentication. Bind loopback by default.
        allowed = self.origin_check(ws) if self.origin_check else ws.headers.get("origin") in self.origins
        if not allowed:
            await ws.close(code=1008)
            return
        await ws.accept()
        client = uuid.uuid4().hex
        previous = None
        cursor = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 3)
            if len(raw) > 1024:
                raise ValueError("oversized hello")
            hello = json.loads(raw)
            if not isinstance(hello, dict) or set(hello) != {"h264"} or type(hello["h264"]) is not bool:
                raise ValueError("capability handshake required")
            self.session.add_client(client, hello["h264"])
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), 2)
                if len(raw) > 1024:
                    raise ValueError("oversized request")
                request = json.loads(raw)
                if not isinstance(request, dict) or set(request) - {"ack"}:
                    raise ValueError("invalid request")
                if previous is not None:
                    ack = request.get("ack")
                    if not isinstance(ack, dict) or ack.get("token") != previous["token"]:
                        raise ValueError("ACK must match the one outstanding frame")
                    decode = ack.get("decode_ms")
                    if type(decode) not in (int, float) or not math.isfinite(decode) or not 0 <= decode <= 2000:
                        raise ValueError("invalid decode time")
                    elapsed = (time.monotonic() - previous["sent"]) * 1000
                    self.session.feedback(client, ack_ms=elapsed,
                        age_ms=previous["age"] + elapsed, decode_ms=decode,
                        frame_bytes=previous["bytes"], epoch=previous["epoch"])
                    previous = None
                elif request.get("ack") is not None:
                    raise ValueError("unexpected ACK")

                deadline = time.monotonic() + .5
                frame = None
                self.session.waiting(client, True)
                while time.monotonic() < deadline:
                    candidate = self.session.latest()
                    if candidate:
                        identity = (candidate["epoch"], candidate["sequence"])
                        if identity != cursor:
                            gap = cursor is None or identity[0] != cursor[0] or identity[1] != cursor[1] + 1
                            if candidate["codec"] == "h264" and gap and not candidate["key"]:
                                self.session.request_key()
                            else:
                                frame = candidate
                                break
                    await asyncio.sleep(.005)
                if frame is None:
                    self.session.waiting(client, False)
                    status = 204 if self.session.latest() else 503
                    if status == 503:
                        cursor = None  # Receiver clears its decoder when input expires.
                    await asyncio.wait_for(ws.send_bytes(pack({"status": status})), .75)
                    continue
                sent = time.monotonic()
                self.session.waiting(client, False)
                age = (sent - frame["received"]) * 1000
                if age > 500:
                    cursor = None
                    await asyncio.wait_for(ws.send_bytes(pack({"status": 503})), .75)
                    continue
                token = uuid.uuid4().hex
                meta = {k: frame[k] for k in ("session", "epoch", "sequence", "codec", "key", "profile")}
                meta.update(status=200, token=token, age_ms=age)
                if frame["codec"] == "h264" and frame["key"]:
                    meta["codec_string"] = avc_codec(frame["data"])
                    if not meta["codec_string"]:
                        raise ValueError("keyframe lacks SPS")
                packet = pack(meta, frame["data"])
                previous = {"token": token, "sent": sent, "age": age, "bytes": len(frame["data"]), "epoch": frame["epoch"]}
                cursor = (frame["epoch"], frame["sequence"])
                await asyncio.wait_for(ws.send_bytes(packet), .75)
                with self.session.condition:
                    self.session.bytes_sent += len(packet)
        except (TimeoutError, asyncio.TimeoutError):
            self.timeouts += 1
        except (ValueError, TypeError, KeyError):
            self.protocol_errors += 1
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self.session.remove_client(client)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
