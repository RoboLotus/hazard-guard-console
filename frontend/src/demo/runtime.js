// Installed by the Demo entry only. Existing pages keep their API contracts,
// but reads resolve locally and writes never reach a backend.
let recording = null;
export const getRecording = () => recording;
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

export function recordedRead(data, path) {
  const m = data.manifest;
  const spatialContext = { ready: false, editable: false, registration_ready: false, message: '저장 자료 시연 · 읽기 전용',
    map_session_id: m.session, world_id: m.world, frame_id: 'map', map_signature: m.fingerprint };
  const session = { id: m.session, world_id: m.world, name: '실측 저장 지도', status: 'saved',
    cloud_ready: true, available: true, active: true, cloud_frame_id: 'map', created_at: m.recordedAt, updated_at: m.recordedAt };
  const map = { map_id: m.session, frame_id: 'map', width: m.map.width, height: m.map.height,
    resolution: m.map.resolution, origin_x: m.map.origin[0], origin_y: m.map.origin[1] };
  const responses = {
    '/api/v1/media/status': { source: 'recorded', stale: true, rgb: { available: false }, thermal: { available: false },
      map: { available: true, recorded: true, width: m.map.width, height: m.map.height, metadata: map } },
    '/api/v1/system/mode': { mode: 'idle', state: 'disabled', control_enabled: false, navigation_ready: false,
      map_available: true, active_world_id: m.world, active_map_session_id: m.session, deployment_target: 'recorded',
      message: '저장 자료 시연 · 실제 로봇 제어 불가' },
    '/api/v1/system/maps': { sessions: [session] },
    '/api/v1/system/worlds': { worlds: [{ id: m.world, name: '실측 저장 지도' }] },
    '/api/v1/settings/equipment': { schema_version: 2, frame_id: 'map', world_id: m.world,
      map_session_id: m.session, equipment: m.equipment, spatial_context: spatialContext, readonly: true },
    '/api/v1/settings/equipment/history': { history: [], revisions: [] },
    '/api/v1/navigation/route/config': { route: null, spatial_context: spatialContext },
    '/api/v1/navigation/status': { state: 'idle', available: false },
    '/api/v1/navigation/route/status': { state: 'idle', control_enabled: false },
    '/api/v1/events/statuses': { map_id: m.session, statuses: [] },
    '/api/v1/incidents': { incidents: [], battery: { expected: 3, connected: 0, available_for_drop: 0, beacons: [], stale: true } },
    '/api/v1/rosbag/status': { state: 'offline', recording: false, control_enabled: false, recording_control_enabled: false },
    '/api/v1/rosbag/sessions': { sessions: [] },
    '/api/v1/performance/reports': { reports: [] },
  };
  return Object.hasOwn(responses, path) ? responses[path] : undefined;
}

export function createRecordedFetch(data, nativeFetch, origin) {
  return async (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), origin);
    const signal = init.signal || request?.signal;
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const method = (init.method || request?.method || 'GET').toUpperCase();
    if (method !== 'GET' || url.origin !== origin) {
      return json({ detail: '저장 자료 시연에서는 실제 제어·설정 변경을 할 수 없습니다.' }, 403);
    }
    if (url.pathname === '/api/v1/media/map') return nativeFetch('/demo-data/map.png', { signal });
    if (/^\/(api|ws)(\/|$)/.test(url.pathname)) {
      const body = recordedRead(data, url.pathname);
      return body === undefined ? json({ detail: '저장 자료에 없는 기능입니다. 실물 연결 없음.' }, 503) : json(body);
    }
    return nativeFetch(input, init);
  };
}

export function installRecordedDemo(data) {
  recording = data;
  window.fetch = createRecordedFetch(data, window.fetch.bind(window), window.location.origin);
}
