import * as THREE from "three";

export const HGTD_PROTOCOL_VERSION = 1;
export const STATIC_THERMAL_DELTA = 1;
export const DYNAMIC_DELTA = 2;
const HGTD_HEADER_BYTES = 28;
const STATIC_RECORD_BYTES = 12;
const DYNAMIC_RECORD_BYTES = 20;
const DYNAMIC_DELETE_BYTES = 12;
const decoder = new TextDecoder("utf-8", { fatal: true });

function safeUint64(view, offset, label) {
  const value = Number(view.getBigUint64(offset, true));
  if (!Number.isSafeInteger(value)) throw new Error(`${label}가 너무 큽니다.`);
  return value;
}

export function parseThermalDelta(payload) {
  const buffer = payload instanceof ArrayBuffer ? payload : payload.buffer;
  const byteOffset = payload instanceof ArrayBuffer ? 0 : payload.byteOffset;
  const byteLength = payload.byteLength;
  if (byteLength < HGTD_HEADER_BYTES) throw new Error("HGTD header가 손상되었습니다.");
  const view = new DataView(buffer, byteOffset, byteLength);
  if (view.getUint32(0, false) !== 0x48475444) throw new Error("HGTD magic이 일치하지 않습니다.");
  const protocolVersion = view.getUint16(4, true);
  if (protocolVersion !== HGTD_PROTOCOL_VERSION) throw new Error(`지원하지 않는 HGTD 버전입니다: ${protocolVersion}`);
  const packetType = view.getUint8(6);
  if (packetType !== STATIC_THERMAL_DELTA && packetType !== DYNAMIC_DELTA) throw new Error("지원하지 않는 HGTD packet type입니다.");
  if (view.getUint8(7) !== 0) throw new Error("지원하지 않는 HGTD flags입니다.");
  const sequence = safeUint64(view, 8, "sequence");
  const baseSequence = safeUint64(view, 16, "base_sequence");
  if (sequence !== baseSequence + 1) throw new Error("HGTD sequence가 연속 형식이 아닙니다.");
  const sessionBytes = view.getUint16(24, true);
  const fingerprintBytes = view.getUint16(26, true);
  let offset = HGTD_HEADER_BYTES;
  if (offset + sessionBytes + fingerprintBytes > byteLength) throw new Error("HGTD metadata가 손상되었습니다.");
  const sessionId = decoder.decode(new Uint8Array(buffer, byteOffset + offset, sessionBytes));
  offset += sessionBytes;
  const geometryFingerprint = decoder.decode(new Uint8Array(buffer, byteOffset + offset, fingerprintBytes));
  offset += fingerprintBytes;
  let createdCount = 0;
  let updatedCount = 0;
  let deletedCount = 0;
  let recordsOffset;
  if (packetType === STATIC_THERMAL_DELTA) {
    if (offset + 4 > byteLength) throw new Error("HGTD static count가 없습니다.");
    updatedCount = view.getUint32(offset, true);
    recordsOffset = offset + 4;
    offset = recordsOffset + updatedCount * STATIC_RECORD_BYTES;
  } else {
    if (offset + 12 > byteLength) throw new Error("HGTD dynamic count가 없습니다.");
    createdCount = view.getUint32(offset, true);
    updatedCount = view.getUint32(offset + 4, true);
    deletedCount = view.getUint32(offset + 8, true);
    recordsOffset = offset + 12;
    offset = recordsOffset + (createdCount + updatedCount) * DYNAMIC_RECORD_BYTES + deletedCount * DYNAMIC_DELETE_BYTES;
  }
  if (offset !== byteLength) throw new Error("HGTD record 길이가 일치하지 않습니다.");
  return {
    protocolVersion, packetType, sessionId, geometryFingerprint,
    sequence, baseSequence, createdCount, updatedCount, deletedCount,
    forEachStaticUpdate(callback) {
      for (let index = 0, at = recordsOffset; index < updatedCount; index += 1, at += STATIC_RECORD_BYTES) {
        callback(view.getUint32(at, true), view.getFloat32(at + 4, true), view.getFloat32(at + 8, true));
      }
    },
    forEachDynamicCreated(callback) {
      if (packetType !== DYNAMIC_DELTA) return;
      for (let index = 0, at = recordsOffset; index < createdCount; index += 1, at += DYNAMIC_RECORD_BYTES) {
        callback(view.getInt32(at, true), view.getInt32(at + 4, true), view.getInt32(at + 8, true), view.getFloat32(at + 12, true), view.getFloat32(at + 16, true));
      }
    },
    forEachDynamicUpdated(callback) {
      if (packetType !== DYNAMIC_DELTA) return;
      let at = recordsOffset + createdCount * DYNAMIC_RECORD_BYTES;
      for (let index = 0; index < updatedCount; index += 1, at += DYNAMIC_RECORD_BYTES) {
        callback(view.getInt32(at, true), view.getInt32(at + 4, true), view.getInt32(at + 8, true), view.getFloat32(at + 12, true), view.getFloat32(at + 16, true));
      }
    },
    forEachDynamicDeleted(callback) {
      if (packetType !== DYNAMIC_DELTA) return;
      let at = recordsOffset + (createdCount + updatedCount) * DYNAMIC_RECORD_BYTES;
      for (let index = 0; index < deletedCount; index += 1, at += DYNAMIC_DELETE_BYTES) {
        callback(view.getInt32(at, true), view.getInt32(at + 4, true), view.getInt32(at + 8, true));
      }
    },
  };
}

export function thermalDeltaAction(delta, state) {
  if (
    delta.sessionId !== state.sessionId
    || delta.geometryFingerprint !== state.geometryFingerprint
  ) return "SNAPSHOT_REQUIRED";
  return delta.baseSequence === state.sequence ? "APPLY" : "REPLAY_REQUIRED";
}

export function thermalRgb(temperature, minimum = 20, maximum = 40) {
  const value = Math.min(1, Math.max(0, (temperature - minimum) / Math.max(maximum - minimum, 1e-6)));
  const anchors = [[0, 0, 0, 1], [.25, 0, 1, 1], [.5, 0, 1, 0], [.75, 1, 1, 0], [1, 1, 0, 0]];
  for (let index = 1; index < anchors.length; index += 1) {
    if (value <= anchors[index][0]) {
      const low = anchors[index - 1]; const high = anchors[index];
      const mix = (value - low[0]) / (high[0] - low[0]);
      return [low[1] + (high[1] - low[1]) * mix, low[2] + (high[2] - low[2]) * mix, low[3] + (high[3] - low[3]) * mix];
    }
  }
  return [1, 0, 0];
}

function keyOf(x, y, z) { return `${x},${y},${z}`; }
function capacityFor(count) { let capacity = 16; while (capacity < count) capacity *= 2; return capacity; }
function attribute(array, itemSize) { return new THREE.BufferAttribute(array, itemSize).setUsage(THREE.DynamicDrawUsage); }
function mark(attributeValue, slots, itemSize) {
  if (!slots.length) return;
  const sorted = [...new Set(slots)].sort((a, b) => a - b);
  attributeValue.clearUpdateRanges();
  let start = sorted[0]; let previous = start;
  for (let index = 1; index <= sorted.length; index += 1) {
    const slot = sorted[index];
    if (slot === previous + 1) { previous = slot; continue; }
    attributeValue.addUpdateRange(start * itemSize, (previous - start + 1) * itemSize);
    start = slot; previous = slot;
  }
  attributeValue.needsUpdate = true;
}

export class ThermalGeometryBuffers {
  constructor(staticGeometry, dynamicGeometry, { temperatureMin = 20, temperatureMax = 40, dynamicVoxelSize = 0.05 } = {}) {
    this.staticGeometry = staticGeometry; this.dynamicGeometry = dynamicGeometry;
    this.temperatureMin = temperatureMin; this.temperatureMax = temperatureMax;
    this.dynamicVoxelSize = dynamicVoxelSize;
    this.staticIndexToSlot = new Map(); this.dynamicKeyToSlot = new Map(); this.freeSlots = [];
    this.dynamicActiveCount = 0; this.dynamicCapacity = 0;
  }

  bootstrap(cloud) {
    if (cloud.version !== 3) throw new Error("stable voxel metadata가 없는 legacy snapshot입니다.");
    const staticSlots = []; const dynamicRows = [];
    this.dynamicKeyToSlot.clear(); this.freeSlots = [];
    this.dynamicActiveCount = 0; this.dynamicCapacity = 0;
    for (const name of ["position", "color", "temperature", "confidence"]) this.dynamicGeometry.deleteAttribute(name);
    for (let index = 0; index < cloud.pointCount; index += 1) (cloud.thermalKinds[index] === 0 ? staticSlots : dynamicRows).push(index);
    const positions = new Float32Array(staticSlots.length * 3); const colors = new Float32Array(staticSlots.length * 3);
    const temperatures = new Float32Array(staticSlots.length); const confidence = new Float32Array(staticSlots.length);
    this.staticIndexToSlot.clear();
    staticSlots.forEach((source, slot) => {
      positions.set(cloud.positions.subarray(source * 3, source * 3 + 3), slot * 3);
      colors.set(cloud.colors.subarray(source * 3, source * 3 + 3), slot * 3);
      temperatures[slot] = cloud.temperatures[source]; confidence[slot] = cloud.confidences[source];
      this.staticIndexToSlot.set(cloud.voxelKeys[source * 3], slot);
    });
    this.staticGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.staticGeometry.setAttribute("color", attribute(colors, 3));
    this.staticGeometry.setAttribute("temperature", attribute(temperatures, 1));
    this.staticGeometry.setAttribute("confidence", attribute(confidence, 1));
    this.staticGeometry.computeBoundingSphere();
    this._allocateDynamic(capacityFor(dynamicRows.length));
    dynamicRows.forEach((source) => this._createDynamic(
      cloud.voxelKeys[source * 3], cloud.voxelKeys[source * 3 + 1], cloud.voxelKeys[source * 3 + 2],
      cloud.temperatures[source], cloud.confidences[source],
      cloud.positions.subarray(source * 3, source * 3 + 3), cloud.colors.subarray(source * 3, source * 3 + 3),
    ));
    return { staticCount: staticSlots.length, dynamicCount: dynamicRows.length, sequence: cloud.thermalSequence ?? 0 };
  }

  _allocateDynamic(capacity) {
    const old = this.dynamicGeometry.getAttribute("position");
    const copy = (name, size, fill = 0) => { const next = new Float32Array(capacity * size); if (fill) next.fill(fill); const prior = this.dynamicGeometry.getAttribute(name); if (prior) next.set(prior.array); return next; };
    const positions = copy("position", 3, Number.NaN); const colors = copy("color", 3); const temperatures = copy("temperature", 1, Number.NaN); const confidence = copy("confidence", 1);
    this.dynamicGeometry.setAttribute("position", attribute(positions, 3)); this.dynamicGeometry.setAttribute("color", attribute(colors, 3));
    this.dynamicGeometry.setAttribute("temperature", attribute(temperatures, 1)); this.dynamicGeometry.setAttribute("confidence", attribute(confidence, 1));
    for (let slot = capacity - 1; slot >= this.dynamicCapacity; slot -= 1) this.freeSlots.push(slot);
    this.dynamicCapacity = capacity; this.dynamicGeometry.setDrawRange(0, capacity); this.dynamicGeometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), Infinity);
    old?.dispose?.();
  }

  _ensureDynamicSlot() { if (!this.freeSlots.length) this._allocateDynamic(Math.max(16, this.dynamicCapacity * 2)); return this.freeSlots.pop(); }
  _writeDynamic(slot, x, y, z, temperature, confidence, position = null, color = null, updatePosition = true) {
    const p = this.dynamicGeometry.getAttribute("position").array; const c = this.dynamicGeometry.getAttribute("color").array;
    const t = this.dynamicGeometry.getAttribute("temperature").array; const q = this.dynamicGeometry.getAttribute("confidence").array;
    const base = slot * 3; const size = this.dynamicVoxelSize;
    if (updatePosition) p.set(position || [(x + .5) * size, (y + .5) * size, (z + .5) * size], base);
    c.set(color || thermalRgb(temperature, this.temperatureMin, this.temperatureMax), base); t[slot] = temperature; q[slot] = confidence;
  }
  _createDynamic(x, y, z, temperature, confidence, position = null, color = null) {
    const key = keyOf(x, y, z); let slot = this.dynamicKeyToSlot.get(key);
    if (slot === undefined) { slot = this._ensureDynamicSlot(); this.dynamicKeyToSlot.set(key, slot); this.dynamicActiveCount += 1; }
    this._writeDynamic(slot, x, y, z, temperature, confidence, position, color); return slot;
  }

  apply(delta) {
    const staticSlots = []; let unknownStatic = false;
    if (delta.packetType === STATIC_THERMAL_DELTA) delta.forEachStaticUpdate((index) => { const slot = this.staticIndexToSlot.get(index); if (slot === undefined) unknownStatic = true; else staticSlots.push(slot); });
    if (unknownStatic) return { applied: false, reason: "STATIC_GEOMETRY_MISSING" };
    const staticColor = []; const staticScalar = [];
    if (delta.packetType === STATIC_THERMAL_DELTA) delta.forEachStaticUpdate((index, temperature, confidence) => {
      const slot = this.staticIndexToSlot.get(index); const colors = this.staticGeometry.getAttribute("color").array;
      colors.set(thermalRgb(temperature, this.temperatureMin, this.temperatureMax), slot * 3);
      this.staticGeometry.getAttribute("temperature").array[slot] = temperature; this.staticGeometry.getAttribute("confidence").array[slot] = confidence;
      staticColor.push(slot); staticScalar.push(slot);
    });
    const dynamicPosition = []; const dynamicColor = []; const dynamicScalar = [];
    delta.forEachDynamicCreated((x, y, z, temperature, confidence) => { const slot = this._createDynamic(x, y, z, temperature, confidence); dynamicPosition.push(slot); dynamicColor.push(slot); dynamicScalar.push(slot); });
    delta.forEachDynamicUpdated((x, y, z, temperature, confidence) => { const slot = this.dynamicKeyToSlot.get(keyOf(x, y, z)); if (slot === undefined) return; this._writeDynamic(slot, x, y, z, temperature, confidence, null, null, false); dynamicColor.push(slot); dynamicScalar.push(slot); });
    delta.forEachDynamicDeleted((x, y, z) => { const key = keyOf(x, y, z); const slot = this.dynamicKeyToSlot.get(key); if (slot === undefined) return; this.dynamicKeyToSlot.delete(key); this.dynamicActiveCount -= 1; this.freeSlots.push(slot); this.dynamicGeometry.getAttribute("position").array.fill(Number.NaN, slot * 3, slot * 3 + 3); this.dynamicGeometry.getAttribute("confidence").array[slot] = 0; dynamicPosition.push(slot); dynamicScalar.push(slot); });
    mark(this.staticGeometry.getAttribute("color"), staticColor, 3); mark(this.staticGeometry.getAttribute("temperature"), staticScalar, 1); mark(this.staticGeometry.getAttribute("confidence"), staticScalar, 1);
    mark(this.dynamicGeometry.getAttribute("position"), dynamicPosition, 3); mark(this.dynamicGeometry.getAttribute("color"), dynamicColor, 3); mark(this.dynamicGeometry.getAttribute("temperature"), dynamicScalar, 1); mark(this.dynamicGeometry.getAttribute("confidence"), dynamicScalar, 1);
    return { applied: true, staticUpdated: staticScalar.length, dynamicPositionUpdated: dynamicPosition.length, dynamicValueUpdated: dynamicScalar.length };
  }
}
