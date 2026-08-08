import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  DownloadSimple,
  Eye,
  FloppyDisk,
  PencilSimple,
  Stack,
  Stop,
} from "@phosphor-icons/react";
import { CollapsibleCard } from "./Common.jsx";

const difficultyLabels = {
  easy: "쉬움",
  medium: "보통",
  hard: "어려움",
  development: "개발용",
  unrated: "미분류",
};

function formatSessionTime(value) {
  if (!value) return "시간 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatBytes(value) {
  if (!value) return "0 MB";
  const megabytes = value / 1024 / 1024;
  return `${megabytes.toFixed(megabytes >= 10 ? 0 : 1)} MB`;
}

export default function SimulationMapManager({
  systemMode,
  onSystemModeUpdate,
  onSaveSystemMap,
  onSaveAndStop,
  onSaveImage,
  onSelect3dSession,
  selected3dSession,
  notify,
}) {
  const [worlds, setWorlds] = useState([]);
  const [draftWorldId, setDraftWorldId] = useState("");
  const [sessions, setSessions] = useState([]);
  const [draftSessionId, setDraftSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const activeWorldId = systemMode?.active_world_id || "facility_map";
  const activeWorld = useMemo(
    () => worlds.find((world) => world.id === activeWorldId),
    [worlds, activeWorldId],
  );
  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === draftSessionId),
    [sessions, draftSessionId],
  );
  const modeActive = ["starting", "running", "stopping", "external"].includes(
    systemMode?.state,
  );
  const externalSimulation = systemMode?.simulation_state === "external"
    && !systemMode?.simulation_managed;
  const environmentLocked = modeActive || externalSimulation;
  const visibleSessions = useMemo(
    () => sessions.filter((session) => showArchived || !session.archived || session.active),
    [sessions, showArchived],
  );

  const refreshWorlds = async () => {
    const response = await fetch("/api/v1/system/worlds", { cache: "no-store" });
    if (!response.ok) throw new Error("환경 목록을 불러오지 못했습니다.");
    const result = await response.json();
    setWorlds(result.worlds || []);
    setDraftWorldId((current) => current || result.active_world_id || "");
  };

  const refreshSessions = async (worldId = activeWorldId) => {
    if (!worldId) return;
    const response = await fetch(
      `/api/v1/system/maps?world_id=${encodeURIComponent(worldId)}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error("저장 지도 목록을 불러오지 못했습니다.");
    const result = await response.json();
    const next = result.sessions || [];
    setSessions(next);
    setDraftSessionId((current) => {
      const currentSession = next.find((session) => session.id === current);
      if (
        currentSession
        && currentSession.available
        && (!currentSession.archived || showArchived || currentSession.active)
      ) return current;
      return next.find((session) => session.active)?.id
        || next.find((session) => session.available && !session.archived)?.id
        || next.find((session) => session.available)?.id
        || "";
    });
  };

  useEffect(() => {
    void refreshWorlds().catch(() => setWorlds([]));
  }, []);

  useEffect(() => {
    setDraftWorldId(activeWorldId);
    void refreshSessions(activeWorldId).catch(() => setSessions([]));
  }, [activeWorldId, systemMode?.mapping_session_id, systemMode?.map_available]);

  useEffect(() => {
    if (showArchived || !selectedSession?.archived || selectedSession.active) return;
    setDraftSessionId(
      sessions.find((session) => session.active)?.id
      || sessions.find((session) => session.available && !session.archived)?.id
      || "",
    );
  }, [showArchived, selectedSession?.id, selectedSession?.archived, selectedSession?.active]);

  const applyWorld = async () => {
    if (!draftWorldId || draftWorldId === activeWorldId) return;
    const selected = worlds.find((world) => world.id === draftWorldId);
    if (!window.confirm(
      `'${selected?.label || draftWorldId}' 환경으로 전환할까요? 기존 웨이포인트는 환경별로 분리 보관됩니다.`,
    )) return;
    setBusy(true);
    try {
      const response = await fetch("/api/v1/system/world", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ world_id: draftWorldId }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "환경을 전환하지 못했습니다.");
      onSystemModeUpdate(result);
      await refreshWorlds();
      await refreshSessions(draftWorldId);
      notify(result.message);
    } catch (error) {
      setDraftWorldId(activeWorldId);
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  const activateMap = async () => {
    if (!draftSessionId) return;
    setBusy(true);
    try {
      const response = await fetch("/api/v1/system/map/active", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          world_id: activeWorldId,
          session_id: draftSessionId,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "순찰 지도를 지정하지 못했습니다.");
      onSystemModeUpdate(result);
      await refreshSessions(activeWorldId);
      notify(result.message);
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  const saveRosMap = async () => {
    setBusy(true);
    try {
      const result = await onSaveSystemMap();
      if (result) await refreshSessions(activeWorldId);
    } finally {
      setBusy(false);
    }
  };

  const saveAndStop = async () => {
    if (!window.confirm("현재 지도 세션을 저장하고 SLAM·Gazebo를 종료할까요?")) return;
    setBusy(true);
    try {
      const result = await onSaveAndStop();
      if (result) await refreshSessions(activeWorldId);
    } finally {
      setBusy(false);
    }
  };

  const patchSession = async (patch) => {
    if (!selectedSession) return;
    setBusy(true);
    try {
      const response = await fetch(
        `/api/v1/system/maps/${encodeURIComponent(activeWorldId)}/${encodeURIComponent(selectedSession.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        },
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "세션 정보를 저장하지 못했습니다.");
      await refreshSessions(activeWorldId);
      notify(result.message);
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  const renameSession = () => {
    if (!selectedSession) return;
    const name = window.prompt(
      "팀원이 알아볼 수 있는 지도 세션 이름을 입력하세요.",
      selectedSession.name || "",
    );
    if (name === null || !name.trim()) return;
    void patchSession({ name: name.trim() });
  };

  const archiveSession = () => {
    if (!selectedSession) return;
    void patchSession({ archived: !selectedSession.archived });
  };

  const downloadCloud = async () => {
    if (!selectedSession?.rtabmap_available) return;
    setBusy(true);
    try {
      const response = await fetch(
        `/api/v1/system/maps/${encodeURIComponent(activeWorldId)}/${encodeURIComponent(selectedSession.id)}/cloud.ply?download=true`,
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "3D 지도 파일을 생성하지 못했습니다.");
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `hazard-guard-${selectedSession.name || selectedSession.id}.ply`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      notify("3D 컬러 포인트클라우드를 PLY로 저장했습니다.");
      await refreshSessions(activeWorldId);
    } catch (error) {
      notify(error.message, "warning");
    } finally {
      setBusy(false);
    }
  };

  return (
    <CollapsibleCard
      icon={Stack}
      title="시뮬레이션 환경·지도"
      subtitle={`${worlds.length}개 환경 · 회차별 SLAM 결과`}
      className="simulation-map-manager"
    >
      <div className="map-manager-field">
        <label htmlFor="simulation-world">시뮬레이션 환경</label>
        <div className="map-manager-select-row">
          <select
            id="simulation-world"
            value={draftWorldId}
            disabled={busy || environmentLocked}
            onChange={(event) => setDraftWorldId(event.target.value)}
          >
            {worlds.map((world) => (
              <option key={world.id} value={world.id}>
                {world.label} · {difficultyLabels[world.difficulty] || world.difficulty}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button secondary"
            disabled={busy || environmentLocked || !draftWorldId || draftWorldId === activeWorldId}
            onClick={applyWorld}
          >
            환경 적용
          </button>
        </div>
        {activeWorld && (
          <div className="world-summary">
            <span className={`difficulty-badge ${activeWorld.difficulty}`}>
              {difficultyLabels[activeWorld.difficulty] || activeWorld.difficulty}
            </span>
            <p>{activeWorld.description}</p>
            <small>{activeWorld.file_name} · 열원 프로필 {activeWorld.has_heat_source_profile ? "연동" : "없음"}</small>
          </div>
        )}
      </div>

      <div className="map-manager-field">
        <div className="map-manager-label-row">
          <label htmlFor="saved-map-session">저장된 SLAM 결과</label>
          <button type="button" className={showArchived ? "active" : ""} onClick={() => setShowArchived((value) => !value)}>
            <Archive size={13} />보관 {showArchived ? "숨기기" : "보기"}
          </button>
        </div>
        <div className="map-manager-select-row">
          <select
            id="saved-map-session"
            value={draftSessionId}
            disabled={busy || modeActive || visibleSessions.every((session) => !session.available)}
            onChange={(event) => setDraftSessionId(event.target.value)}
          >
            {visibleSessions.filter((session) => session.available).length === 0 && (
              <option value="">
                {systemMode?.map_available
                  ? "기존 단일 저장 지도 · 사용 중"
                  : "저장된 지도 없음"}
              </option>
            )}
            {visibleSessions.filter((session) => session.available).map((session) => (
              <option key={session.id} value={session.id}>
                {session.name || formatSessionTime(session.created_at)}
                {session.mapping_profile === "toolbox_rtabmap" ? " · 2D+3D" : " · 2D"}
                {session.archived ? " · 보관" : ""}
                {session.active ? " · 사용 중" : ""}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button secondary"
            disabled={busy || modeActive || !draftSessionId || sessions.find((item) => item.id === draftSessionId)?.active}
            onClick={activateMap}
          >
            순찰 지도 지정
          </button>
        </div>
        {selectedSession && (
          <div className={`map-session-detail ${selectedSession.rtabmap_available ? "has-3d" : ""} ${selectedSession.archived ? "archived" : ""}`}>
            <div>
              <span>{selectedSession.mapping_profile === "toolbox_rtabmap" ? "Toolbox + RTAB-Map" : "SLAM Toolbox"}</span>
              <small>
                {selectedSession.rtabmap_available
                  ? `3D DB ${formatBytes(selectedSession.rtabmap_database_bytes)}${selectedSession.cloud_available ? ` · PLY ${formatBytes(selectedSession.cloud_bytes)}` : ""}`
                  : "2D 지도 저장 결과"}
              </small>
            </div>
            <div className="map-session-actions">
              <button type="button" title="세션 이름 변경" aria-label="세션 이름 변경" onClick={renameSession} disabled={busy}><PencilSimple size={14} /></button>
              <button type="button" title={selectedSession.archived ? "보관 해제" : "보관"} aria-label={selectedSession.archived ? "보관 해제" : "보관"} onClick={archiveSession} disabled={busy}><Archive size={14} /></button>
              {selectedSession.rtabmap_available && (
                <>
                  <button type="button" className={selected3dSession?.id === selectedSession.id ? "active" : ""} title="저장 3D 지도 보기" aria-label="저장 3D 지도 보기" onClick={() => onSelect3dSession(selectedSession)} disabled={busy || modeActive}><Eye size={14} /></button>
                  <button type="button" title="PLY 내려받기" aria-label="PLY 내려받기" onClick={downloadCloud} disabled={busy || modeActive}><DownloadSimple size={14} /></button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="map-file-actions">
        <button
          type="button"
          className="button primary wide-button"
          onClick={saveRosMap}
          disabled={busy || systemMode?.mode !== "mapping" || !systemMode?.control_enabled}
        >
          <FloppyDisk size={18} />
          {systemMode?.mapping_profile === "toolbox_rtabmap" ? "현재 2D + 3D 세션 저장" : "현재 SLAM 지도 저장"}
        </button>
        <button
          type="button"
          className="button secondary wide-button"
          onClick={saveAndStop}
          disabled={busy || systemMode?.mode !== "mapping" || !systemMode?.control_enabled}
        >
          <Stop size={18} />지도 저장 후 종료
        </button>
        <button type="button" className="button ghost wide-button" onClick={onSaveImage}>
          <DownloadSimple size={18} />현재 화면 PNG 저장
        </button>
      </div>
      <p className={`map-storage-status ${systemMode?.map_available ? "available" : ""}`}>
        {systemMode?.mode === "mapping"
          ? `${systemMode?.mapping_profile === "toolbox_rtabmap" ? "2D + 3D" : "2D"} 새 SLAM 세션 ${systemMode?.mapping_session_id || "준비 중"}`
          : systemMode?.map_available
            ? "선택한 환경에서 AMCL 순찰에 사용할 지도가 준비되었습니다."
            : "맵 생성 모드에서 새 세션을 시작하고 지도를 저장하세요."}
      </p>
    </CollapsibleCard>
  );
}
