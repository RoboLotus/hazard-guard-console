// Only fixed same-origin assets. There is deliberately no operational API client.
export async function loadRecording(signal) {
  const read = async (name, type = 'json') => {
    const response = await fetch(`/demo-data/${name}`, { signal, cache: 'no-store' });
    if (!response.ok) throw Error('저장 자료가 없습니다. DEMO.md의 자료 준비 명령을 실행하세요.');
    try { return await response[type](); }
    catch { throw Error('시연 자료를 읽지 못했습니다. 자료 준비 명령과 파일 구성을 확인하세요.'); }
  };
  const [manifest, rawPoints, rawColors, thermal] = await Promise.all([
    read('manifest.json'), read('points.bin', 'arrayBuffer'), read('colors.bin', 'arrayBuffer'), read('thermal.json'),
  ]);
  if (manifest.schema !== 1 || manifest.recorded !== true || manifest.frame !== 'map' ||
      !Number.isSafeInteger(manifest.pointCount) || manifest.pointCount <= 0 || manifest.pointCount > 500000 ||
      rawPoints.byteLength !== manifest.pointCount * 12 || rawColors.byteLength !== manifest.pointCount * 3) {
    throw Error('지도 형식 또는 점 개수가 일치하지 않습니다. 자료를 다시 변환하세요.');
  }
  const points = new Float32Array(rawPoints), colors = new Uint8Array(rawColors);
  const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
  const map = manifest.map;
  if (!map || !Number.isFinite(map.resolution) || map.resolution <= 0 || !vector(map.origin) ||
      !Number.isSafeInteger(map.width) || map.width <= 0 || !Number.isSafeInteger(map.height) || map.height <= 0 ||
      !Number.isFinite(manifest.voxel) || manifest.voxel <= 0 ||
      !Number.isFinite(manifest.temperatureMin) || !Number.isFinite(manifest.temperatureMax) ||
      manifest.temperatureMin > manifest.temperatureMax || !Array.isArray(manifest.equipment) ||
      manifest.equipment.some(row => !row || (row.roi && (!vector(row.roi.min) || !vector(row.roi.max)))) ||
      (manifest.savedPose && !['x', 'y', 'yaw'].every(key => Number.isFinite(manifest.savedPose[key])))) {
    throw Error('유효하지 않은 지도 메타데이터입니다.');
  }
  if (!points.every(Number.isFinite) || !Array.isArray(thermal.indices) || !Array.isArray(thermal.temperatures) ||
      thermal.indices.length !== manifest.observedCount || thermal.indices.length !== thermal.temperatures.length ||
      new Set(thermal.indices).size !== thermal.indices.length ||
      thermal.indices.some(i => !Number.isSafeInteger(i) || i < 0 || i >= manifest.pointCount) ||
      !thermal.temperatures.every(Number.isFinite)) throw Error('유효하지 않은 지도·온도 데이터입니다.');
  return { manifest, points, colors, thermal };
}

// ROS map origin can contain yaw. PGM row zero is at the top of the image.
export function mapPixel(x, y, map) {
  const [ox, oy, yaw] = map.origin;
  const dx = x - ox, dy = y - oy;
  return [(Math.cos(yaw) * dx + Math.sin(yaw) * dy) / map.resolution,
    map.height - (-Math.sin(yaw) * dx + Math.cos(yaw) * dy) / map.resolution];
}

export function heatColor(value, min, max) {
  const t = Math.max(0, Math.min(1, (value - min) / Math.max(.001, max - min)));
  const stops = [[.1, .35, .8], [.03, .8, .8], [1, .85, .16], [1, .18, .12]];
  const i = Math.min(2, Math.floor(t * 3)), f = t * 3 - i;
  return stops[i].map((v, c) => v + (stops[i + 1][c] - v) * f);
}
