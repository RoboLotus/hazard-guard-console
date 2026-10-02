"""Opt-in codec experiment helpers; no ROS, robot control, or production imports."""
from fractions import Fraction
import av
import cv2
import numpy as np

PROFILES = {
    'jpeg82': {'codec': 'jpeg', 'quality': 82},
    'h264_fast23': {'codec': 'h264', 'preset': 'ultrafast', 'crf': 23},
    'h264_vfast23': {'codec': 'h264', 'preset': 'veryfast', 'crf': 23},
    'h264_vfast28': {'codec': 'h264', 'preset': 'veryfast', 'crf': 28},
    'vp8_500': {'codec': 'vp8', 'bitrate': 500000},
    'vp8_1000': {'codec': 'vp8', 'bitrate': 1000000},
    'vp8_2000': {'codec': 'vp8', 'bitrate': 2000000},
}

class Encoder:
    def __init__(self, profile):
        self.spec = PROFILES[profile]
        self.codec = self.spec['codec']
        self.ctx = None
        if self.codec != 'jpeg':
            c = av.CodecContext.create('libx264' if self.codec == 'h264' else 'libvpx', 'w')
            c.width, c.height, c.pix_fmt = 640, 480, 'yuv420p'
            c.time_base, c.framerate = Fraction(1, 90000), Fraction(10, 1)
            c.thread_count, c.gop_size, c.max_b_frames = 2, 10, 0
            if self.codec == 'h264':
                c.options = {'preset': self.spec['preset'], 'tune': 'zerolatency',
                    'crf': str(self.spec['crf']), 'profile': 'baseline',
                    'x264-params': 'keyint=10:min-keyint=10:scenecut=0:repeat-headers=1:bframes=0:rc-lookahead=0'}
            else:
                c.bit_rate = self.spec['bitrate']
                c.options = {'deadline': 'realtime', 'cpu-used': '6', 'lag-in-frames': '0',
                    'error-resilient': '1', 'auto-alt-ref': '0'}
            c.open()
            self.ctx = c

    def encode(self, bgr, seq, force_key=False):
        if bgr.shape != (480, 640, 3):
            raise ValueError('640x480 bgr8 required; no implicit resizing')
        if self.codec == 'jpeg':
            ok, data = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not ok:
                raise RuntimeError('JPEG encode failed')
            return bytes(data), True
        f = av.VideoFrame.from_ndarray(bgr, format='bgr24')
        f.pts, f.time_base = seq * 9000, Fraction(1, 90000)
        if seq % 10 == 0 or force_key:
            f.pict_type = av.video.frame.PictureType.I
        packets = self.ctx.encode(f)
        if len(packets) != 1:
            raise RuntimeError(f'Expected one zero-delay packet, got {len(packets)}')
        return bytes(packets[0]), bool(packets[0].is_keyframe)

def packet(data, seq):
    p = av.Packet(data)
    p.pts = p.dts = seq * 9000
    p.time_base = Fraction(1, 90000)
    return p

def mark(bgr, seq):
    """Experiment frame ID strip, bottom 12px; not a real motion-quality test."""
    bgr = bgr.copy()
    value = (0xA5 << 24) | (seq & 0xFFFFFF)
    for bit in range(32):
        bgr[468:480, bit*16:(bit+1)*16] = 240 if value & (1 << (31-bit)) else 16
    return bgr

def quality(a, b):
    # Same decoded frame against exact uncompressed input; full image BGR PSNR,
    # luminance SSIM with 11x11 Gaussian sigma1.5 and valid interior crop.
    mse = float(np.mean((a.astype(np.float64)-b.astype(np.float64))**2))
    psnr = float(10*np.log10(255**2/mse)) if mse else 100.0
    x, y = [cv2.cvtColor(z, cv2.COLOR_BGR2GRAY).astype(np.float64) for z in (a,b)]
    ux, uy = [cv2.GaussianBlur(z,(11,11),1.5) for z in (x,y)]
    vx = cv2.GaussianBlur(x*x,(11,11),1.5)-ux*ux
    vy = cv2.GaussianBlur(y*y,(11,11),1.5)-uy*uy
    cov = cv2.GaussianBlur(x*y,(11,11),1.5)-ux*uy
    s = ((2*ux*uy+6.5025)*(2*cov+58.5225))/((ux*ux+uy*uy+6.5025)*(vx+vy+58.5225))
    return {'psnr_db': psnr, 'ssim_luma': float(s[5:-5,5:-5].mean())}
