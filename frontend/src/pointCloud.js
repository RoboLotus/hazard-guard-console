export const POINT_CLOUD_HEADER_BYTES = 24;
export const POINT_CLOUD_RECORD_BYTES = 16;
export const THERMAL_STATE_RECORD_BYTES = 48;
// Robot-side stationary refresh is 5 s. Leave room for sensor/TF scheduling
// and the 5 s status poll so a healthy stationary layer does not flicker stale.
export const THERMAL_CLOUD_FRESH_MS = 15000;

function finiteNumber(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function timestampMs(value) {
  if (value instanceof Date) {
    const parsed = value.getTime();
    return Number.isFinite(parsed) ? parsed : null;
  }
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Build the display state for the post-mapping thermal layer.
 *
 * The WebSocket packet is an authoritative cumulative snapshot. This helper
 * deliberately describes that snapshot; it never merges point arrays in the
 * browser. New backend metadata is preferred when available, while the
 * original point-cloud status response remains a supported fallback.
 */
export function resolveThermalLayerPresentation(
  apiStatus = {},
  streamStatus = {},
  nowMs = Date.now(),
) {
  const observedVoxelCount = Math.max(0, Math.trunc(finiteNumber(
    apiStatus.observed_voxel_count,
    apiStatus.voxel_count,
    streamStatus.pointCount,
    apiStatus.point_count,
    0,
  )));
  const hasObservationTimestamp = Object.prototype.hasOwnProperty.call(
    apiStatus,
    "last_observation_at",
  );
  let updatedAtMs = timestampMs(apiStatus.last_observation_at);
  if (!hasObservationTimestamp) {
    const streamUpdatedAtMs = timestampMs(streamStatus.updatedAt);
    updatedAtMs = Math.max(
      streamUpdatedAtMs || 0,
      timestampMs(apiStatus.updated_at) || 0,
    ) || null;
    const ageSec = finiteNumber(apiStatus.age_sec);
    if (!updatedAtMs && ageSec !== null) {
      updatedAtMs = nowMs - Math.max(0, ageSec) * 1000;
    }
  }
  const elapsedMs = updatedAtMs === null
    ? null
    : Math.max(0, nowMs - updatedAtMs);
  const staleAfterMs = Math.max(
    1000,
    (finiteNumber(apiStatus.stale_after_sec) ?? (
      THERMAL_CLOUD_FRESH_MS / 1000
    )) * 1000,
  );
  const stale = elapsedMs === null
    ? (typeof apiStatus.stale === "boolean" ? apiStatus.stale : true)
    : elapsedMs >= staleAfterMs;
  const fixedMapAvailable = typeof apiStatus.fixed_map_available === "boolean"
    ? apiStatus.fixed_map_available
    : observedVoxelCount > 0 ? true : null;
  const matchRatio = finiteNumber(apiStatus.match_ratio);

  return {
    cumulative: apiStatus.cumulative !== false,
    observedVoxelCount,
    fixedMapAvailable,
    hasObservationTimestamp,
    updatedAtMs,
    elapsedMs,
    staleAfterMs,
    stale,
    matchRatio: matchRatio === null ? null : Math.min(1, Math.max(0, matchRatio)),
    rejectedObservationCount: Math.max(0, Math.trunc(finiteNumber(
      apiStatus.rejected_observation_count,
      0,
    ))),
    persistedAtMs: timestampMs(apiStatus.persisted_at),
    sessionId: apiStatus.session_id || null,
  };
}

export function formatThermalLayerAge(updatedAtMs, nowMs = Date.now()) {
  if (!Number.isFinite(updatedAtMs)) return "갱신 대기";
  const seconds = Math.max(0, Math.floor((nowMs - updatedAtMs) / 1000));
  if (seconds < 2) return "방금 전";
  if (seconds < 60) return `${seconds}초 전`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 전`;
}

export function replacePointCloudGeometrySnapshot(
  geometry,
  positionAttribute,
  colorAttribute,
) {
  geometry.setAttribute("position", positionAttribute);
  geometry.setAttribute("color", colorAttribute);
  geometry.computeBoundingSphere();
}

const textDecoder = new TextDecoder("ascii");
const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

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
  if (version !== 1 && version !== 2 && version !== 3) {
    throw new Error(`지원하지 않는 3D 지도 버전입니다: ${version}`);
  }
  const flags = view.getUint8(5);
  const frameIdBytes = version === 2 ? view.getUint16(6, true) : 0;
  const sequence = view.getUint32(8, true);
  const pointCount = view.getUint32(12, true);
  const timestampMs = Number(view.getBigUint64(16, true));
  const recordStart = POINT_CLOUD_HEADER_BYTES + frameIdBytes;
  const recordBytes = version === 3
    ? THERMAL_STATE_RECORD_BYTES
    : POINT_CLOUD_RECORD_BYTES;
  const requiredBytes = recordStart + pointCount * recordBytes;
  if (byteLength < requiredBytes) {
    throw new Error("3D 지도 포인트 데이터가 완전하지 않습니다.");
  }

  let frameId = null;
  if (frameIdBytes) {
    try {
      frameId = utf8Decoder.decode(
        new Uint8Array(buffer, byteOffset + POINT_CLOUD_HEADER_BYTES, frameIdBytes),
      );
    } catch {
      throw new Error("3D 지도 좌표계 정보를 해석하지 못했습니다.");
    }
  }

  const positions = new Float32Array(pointCount * 3);
  const colors = new Float32Array(pointCount * 3);
  const temperatures = version === 3 ? new Float32Array(pointCount) : null;
  const confidences = version === 3 ? new Float32Array(pointCount) : null;
  const thermalKinds = version === 3 ? new Uint8Array(pointCount) : null;
  const voxelKeys = version === 3 ? new Int32Array(pointCount * 3) : null;
  let thermalSequence = null;
  let recordOffset = recordStart;
  for (let index = 0; index < pointCount; index += 1) {
    const target = index * 3;
    positions[target] = view.getFloat32(recordOffset, true);
    positions[target + 1] = view.getFloat32(recordOffset + 4, true);
    positions[target + 2] = view.getFloat32(recordOffset + 8, true);
    colors[target] = view.getUint8(recordOffset + 12) / 255;
    colors[target + 1] = view.getUint8(recordOffset + 13) / 255;
    colors[target + 2] = view.getUint8(recordOffset + 14) / 255;
    if (version === 3) {
      temperatures[index] = view.getFloat32(recordOffset + 16, true);
      confidences[index] = view.getFloat32(recordOffset + 20, true);
      thermalKinds[index] = view.getUint8(recordOffset + 24);
      voxelKeys[target] = view.getInt32(recordOffset + 28, true);
      voxelKeys[target + 1] = view.getInt32(recordOffset + 32, true);
      voxelKeys[target + 2] = view.getInt32(recordOffset + 36, true);
      const recordSequence = view.getFloat64(recordOffset + 40, true);
      if (!Number.isSafeInteger(recordSequence) || recordSequence < 0) {
        throw new Error("열화상 snapshot sequence가 유효하지 않습니다.");
      }
      thermalSequence ??= recordSequence;
      if (thermalSequence !== recordSequence) {
        throw new Error("열화상 snapshot sequence가 일관되지 않습니다.");
      }
    }
    recordOffset += recordBytes;
  }

  return {
    version,
    sequence,
    pointCount,
    timestampMs,
    frameId,
    colorAvailable: Boolean(flags & 1),
    positions,
    colors,
    temperatures,
    confidences,
    thermalKinds,
    voxelKeys,
    thermalSequence,
  };
}
