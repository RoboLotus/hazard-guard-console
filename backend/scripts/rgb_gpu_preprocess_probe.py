"""Small stationary CUDA preprocessing screen; no robot controls or server.

The real input is BGR8, requiring NO color conversion in production.
An RGB fixture derived from the same frames tests an explicitly conditional
CPU-vs-CUDA conversion. Both retain the same CPU JPEG encoder and quality.
"""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics as stats
import sys
import time

import cv2
import numpy as np


def summary(xs):
    return {'mean': stats.mean(xs), 'median': stats.median(xs),
            'p95': sorted(xs)[math.ceil(len(xs)*.95)-1], 'max': max(xs)}


def capture(out):
    import rclpy
    from sensor_msgs.msg import Image
    from rclpy.qos import qos_profile_sensor_data
    from cv_bridge import CvBridge
    assert os.environ.get('ROS_DOMAIN_ID') == '162'
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    frames, metadata = [], []
    rclpy.init()
    node = rclpy.create_node('rgb_gpu_read_only_capture')
    bridge = CvBridge()
    begin = time.monotonic()
    def receive(msg):
        if time.monotonic()-begin < 2 or len(frames) >= 30:
            return
        image = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        assert image.shape == (480,640,3)
        frames.append(image.copy())
        metadata.append({'encoding': msg.encoding, 'step': msg.step,
                         'stamp_sec': msg.header.stamp.sec, 'stamp_ns': msg.header.stamp.nanosec})
    node.create_subscription(Image, '/ascamera_hp60c/camera_publisher/rgb0/image', receive, qos_profile_sensor_data)
    try:
        while len(frames)<30 and time.monotonic()-begin<15:
            rclpy.spin_once(node, timeout_sec=.1)
    finally:
        node.destroy_node(); rclpy.shutdown()
    if len(frames)!=30:
        raise RuntimeError(f'Expected 30 frames, got {len(frames)}')
    np.savez_compressed(out/'reference.npz', frames=np.stack(frames))
    cv2.imwrite(str(out/'reference.png'), frames[0])
    (out/'capture.json').write_text(json.dumps(metadata,indent=2))
    return frames


def main():
    out=Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    source = None
    if len(sys.argv)>2:
        source=Path(sys.argv[2])
        frames=list(np.load(source)['frames'][:30])
        assert len(frames)==30 and all(f.shape==(480,640,3) for f in frames)
        np.savez_compressed(out/'reference.npz',frames=np.stack(frames))
        cv2.imwrite(str(out/'reference.png'),frames[0])
        (out/'capture.json').write_text(json.dumps({'kind':'recorded real RGB, BGR arrays captured through CvBridge',
            'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}))
    else:
        frames=capture(out)
    assert cv2.cuda.getCudaEnabledDeviceCount()>0
    # Allocate CUDA context and device buffers before measurement.
    cv2.cuda.setDevice(0)
    stream=cv2.cuda_Stream()
    device=cv2.cuda_GpuMat()
    converted=cv2.cuda_GpuMat()
    rgb=[cv2.cvtColor(f,cv2.COLOR_BGR2RGB) for f in frames]
    params=[cv2.IMWRITE_JPEG_QUALITY,82]
    modes=['native_bgr_cpu_jpeg','rgb_cpu_convert_jpeg','rgb_cuda_convert_cpu_jpeg']
    def process(mode,i):
        nonlocal converted
        t=time.perf_counter(); c=time.process_time()
        if mode=='native_bgr_cpu_jpeg':
            bgr=frames[i]
        elif mode=='rgb_cpu_convert_jpeg':
            bgr=cv2.cvtColor(rgb[i],cv2.COLOR_RGB2BGR)
        else:
            device.upload(rgb[i],stream)
            converted=cv2.cuda.cvtColor(device,cv2.COLOR_RGB2BGR,dst=converted,stream=stream)
            # download without a stream is blocking; explicitly wait first.
            stream.waitForCompletion()
            bgr=converted.download()
        pre=(time.perf_counter()-t)*1000
        ok,encoded=cv2.imencode('.jpg',bgr,params)
        if not ok: raise RuntimeError('JPEG failed')
        elapsed=(time.perf_counter()-t)*1000
        cpu=(time.process_time()-c)*1000
        return bgr,encoded,pre,elapsed,cpu
    # Validate each path produces exactly the same pixels and JPEG bytes.
    for i in range(len(frames)):
        reference=process(modes[0],i)[1]
        for mode in modes[1:]:
            bgr,encoded,*_=process(mode,i)
            assert np.array_equal(frames[i],bgr),mode
            assert np.array_equal(reference,encoded),mode
    for mode in modes:
        _,jpeg,*_=process(mode,0)
        (out/(mode+'.jpg')).write_bytes(jpeg.tobytes())
    all_rows=[]
    # Rotate execution order to reduce fixed ordering bias. 5 repetitions/path.
    for repetition in range(5):
        order=modes[repetition%3:]+modes[:repetition%3]
        for mode in order:
            pre,elapsed,cpu=[],[],[]
            started=time.perf_counter(); process_started=time.process_time()
            for i in range(30):
                _,_,p,e,c=process(mode,i)
                pre.append(p);elapsed.append(e);cpu.append(c)
                time.sleep(max(0,started+(i+1)*.1-time.perf_counter()))
            wall=time.perf_counter()-started
            proc=time.process_time()-process_started
            row={'repeat':repetition+1,'mode':mode,'frames':30,'wall_s':wall,
                 'cpu_one_core_pct':proc/wall*100,'preprocess_ms':summary(pre),
                 'total_process_ms':summary(elapsed),'process_cpu_ms':summary(cpu),
                 'over_100ms':sum(x>100 for x in elapsed),
                 'frame_ms':elapsed,'frame_preprocess_ms':pre}
            all_rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if not k.startswith('frame_')}),flush=True)
            (out/'results.json').write_text(json.dumps(all_rows,indent=2))
    env={'cv2':cv2.__version__,'cv2_path':cv2.__file__,'cuda_devices':cv2.cuda.getCudaEnabledDeviceCount(),
         'threads':cv2.getNumThreads(),'dimensions':[640,480],'quality':82,'target_fps':10,
         'actual_input_encodings':sorted({m['encoding'] for m in json.loads((out/'capture.json').read_text())}) if source is None else None,
         'input_kind':'recorded real sensor BGR arrays' if source else 'live sensor',
         'fixture_sha256':hashlib.sha256((out/'reference.npz').read_bytes()).hexdigest(),
         'pixel_and_jpeg_equality':'30 frames, every path, passed',
         'scope':'GPU RGB-to-BGR preprocessing only; JPEG remains CPU; actual BGR input needs no conversion; no network or WebUI test'}
    (out/'environment.json').write_text(json.dumps(env,indent=2))
    (out/'opencv_build.txt').write_text(cv2.getBuildInformation())
    flat=[{'repeat':r['repeat'],'mode':r['mode'],'cpu_one_core_pct':r['cpu_one_core_pct'],
           'preprocess_mean_ms':r['preprocess_ms']['mean'],'total_mean_ms':r['total_process_ms']['mean'],
           'total_p95_ms':r['total_process_ms']['p95'],'cpu_mean_ms':r['process_cpu_ms']['mean'],
           'over_100ms':r['over_100ms']} for r in all_rows]
    with (out/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=flat[0]);w.writeheader();w.writerows(flat)


if __name__=='__main__':
    main()
