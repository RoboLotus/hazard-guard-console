export const POINT_CLOUD_HEADER_BYTES = 24;
export const POINT_CLOUD_RECORD_BYTES = 16;

const textDecoder = new TextDecoder("ascii");

export function parsePointCloudPacket(payload) {
  const buffer = payload instanceof ArrayBuffer ? payload : payload.buffer;
  const byteOffset = payload instanceof ArrayBuffer ? 0 : payload.byteOffset;
  const byteLength = payload.byteLength;
  if (byteLength < POINT_CLOUD_HEADER_BYTES) {
    throw new Error("3D 지도 패킷 헤더가 손상되었습니다.");
  }

  const view = new DataView(buffer, byteOffset, byteLength);
  const magic = textDecoder.decode(new Uint8Array(buffer, byteOffset, 4));
  if (magic !== "HGPC") throw new Error("지원하지 않는 3D 지도 패킷입니다.");

  const version = view.getUint8(4);
  if (version !== 1) throw new Error(`지원하지 않는 3D 지도 버전입니다: ${version}`);
  const flags = view.getUint8(5);
  const sequence = view.getUint32(8, true);
  const pointCount = view.getUint32(12, true);
  const timestampMs = Number(view.getBigUint64(16, true));
  const requiredBytes = POINT_CLOUD_HEADER_BYTES + pointCount * POINT_CLOUD_RECORD_BYTES;
  if (byteLength < requiredBytes) {
    throw new Error("3D 지도 포인트 데이터가 완전하지 않습니다.");
  }

  const positions = new Float32Array(pointCount * 3);
  const colors = new Float32Array(pointCount * 3);
  let recordOffset = POINT_CLOUD_HEADER_BYTES;
  for (let index = 0; index < pointCount; index += 1) {
    const target = index * 3;
    positions[target] = view.getFloat32(recordOffset, true);
    positions[target + 1] = view.getFloat32(recordOffset + 4, true);
    positions[target + 2] = view.getFloat32(recordOffset + 8, true);
    colors[target] = view.getUint8(recordOffset + 12) / 255;
    colors[target + 1] = view.getUint8(recordOffset + 13) / 255;
    colors[target + 2] = view.getUint8(recordOffset + 14) / 255;
    recordOffset += POINT_CLOUD_RECORD_BYTES;
  }

  return {
    sequence,
    pointCount,
    timestampMs,
    colorAvailable: Boolean(flags & 1),
    positions,
    colors,
  };
}
