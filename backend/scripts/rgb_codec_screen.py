"""Bounded sensor capture (60 frames, ~53MiB RAM), identical-input codec screen."""
import os, sys, time, json, hashlib, statistics, math
from pathlib import Path
import av, cv2, numpy as np
import rclpy
from sensor_msgs.msg import Image
from rclpy.qos import qos_profile_sensor_data
from cv_bridge import CvBridge
from rgb_codec_core import Encoder, PROFILES, packet, quality

def main():
    assert os.environ.get('ROS_DOMAIN_ID') == '162' and os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    frames, stamps = [], []
    started = time.monotonic()
    rclpy.init(); node = rclpy.create_node('rgb_codec_static_capture')
    bridge = CvBridge()
    def cb(msg):
        now = time.monotonic()
        if now-started>3 and len(frames)<60 and (not stamps or now-stamps[-1] >= .095):
            a = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            assert a.shape == (480,640,3)
            frames.append(a.copy()); stamps.append(now)
    node.create_subscription(Image,'/ascamera_hp60c/camera_publisher/rgb0/image',cb,qos_profile_sensor_data)
    end = time.monotonic()+20
    while len(frames)<60 and time.monotonic()<end: rclpy.spin_once(node,timeout_sec=.2)
    node.destroy_node(); rclpy.shutdown()
    if len(frames)!=60: raise RuntimeError(f'Only {len(frames)} sensor frames')
    means=[float(f.mean()) for f in frames]
    if min(means)<5: raise RuntimeError(f'Black/startup frames detected: {means}')
    cv2.imwrite(str(out/'reference.png'),frames[30])
    # Small compressed raw sequence, not rosbag; all candidates see exact same frames.
    np.savez_compressed(out/'reference_60frames.npz',frames=np.stack(frames),stamps=stamps)
    results=[]
    for name in PROFILES:
        enc=Encoder(name); packets=[]; timings=[]; cpu=[]
        for i,f in enumerate(frames):
            t=time.perf_counter(); c=time.process_time()
            data,key=enc.encode(f,i); cpu.append((time.process_time()-c)*1000); timings.append((time.perf_counter()-t)*1000)
            packets.append((data,key))
        dec=av.CodecContext.create(enc.codec,'r') if enc.codec!='jpeg' else None
        qualities=[]
        for i,(data,key) in enumerate(packets):
            if dec:
                fs=dec.decode(packet(data,i))
                if len(fs)!=1: raise RuntimeError('decode buffered/missing frame')
                reconstructed=fs[0].to_ndarray(format='bgr24')
            else: reconstructed=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
            qualities.append(quality(frames[i],reconstructed))
            if i==30:
                cv2.imwrite(str(out/(name+'_decoded.png')),reconstructed)
                (out/(name+'_frame.bin')).write_bytes(data)
        stat=lambda a:dict(mean=statistics.mean(a),p95=sorted(a)[math.ceil(.95*len(a))-1],max=max(a))
        result={'profile':name,'settings':PROFILES[name],'frames':60,'encode_ms':stat(timings),
            'encode_cpu_ms':stat(cpu),'bytes_total':sum(len(x[0]) for x in packets),
            'payload_kib_s_at_10fps':sum(len(x[0]) for x in packets)/6/1024,
            'psnr_db':stat([x['psnr_db'] for x in qualities]),'ssim_luma':stat([x['ssim_luma'] for x in qualities]),
            'keyframes':[i for i,x in enumerate(packets) if x[1]],'per_frame':[{'encode_ms':timings[i],'bytes':len(packets[i][0]),**q} for i,q in enumerate(qualities)]}
        results.append(result); print(json.dumps({k:v for k,v in result.items() if k!='per_frame'}),flush=True)
    (out/'codec_screen.json').write_text(json.dumps({'av':av.__version__,'libraries':av.library_versions,'input_means':means,'capture_seconds':stamps[-1]-stamps[0],'results':results},indent=2))

if __name__=='__main__': main()
