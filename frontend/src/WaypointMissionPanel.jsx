import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Crosshair,
  DotsSixVertical,
  FloppyDisk,
  ListNumbers,
  NavigationArrow,
  Play,
  Sparkle,
  Stop,
  Trash,
  X,
} from "@phosphor-icons/react";

const missionActiveStates = new Set([
  "preparing",
  "running",
  "sending",
  "executing",
  "canceling",
]);

const waypointStateLabels = {
  pending: "대기",
  validating: "경로 확인",
  active: "이동 중",
  aligning: "방향 정렬",
  aligned: "정렬 완료",
  dwelling: "점검 대기",
  completed: "완료",
  failed: "실패",
  canceled: "취소",
  skipped: "건너뜀",
};

function degreesToRadians(degrees) {
  const normalized = ((((Number(degrees) || 0) + 180) % 360) + 360) % 360 - 180;
  return (normalized * Math.PI) / 180;
}

function radiansToDegrees(radians) {
  return Math.round(((Number(radians) || 0) * 180) / Math.PI);
}

export default function WaypointMissionPanel({
  waypoints,
  candidate,
  goalMode,
  repositioning,
  selectedId,
  mapLive,
  mapMismatch,
  patrolModeSelected,
  patrolModeReady,
  modeControlEnabled,
  modeTransitioning,
  readinessMessage,
  missionStatus,
  busy,
  onSelect,
  onToggleAdd,
  onAdd,
  onCancelCandidate,
  onUpdate,
  onDelete,
  onMove,
  onShift,
  onReposition,
  onStart,
  onRequestPatrolMode,
  onCancelMission,
  onRecommend,
  onSave,
  onClear,
}) {
  const [candidateName, setCandidateName] = useState("");
  const [candidateYaw, setCandidateYaw] = useState(0);
  const [candidateDwell, setCandidateDwell] = useState(2);
  const [draggingId, setDraggingId] = useState(null);
  const missionActive = missionActiveStates.has(missionStatus?.status);
  const enabledCount = waypoints.filter((waypoint) => waypoint.enabled !== false).length;
  const missionById = useMemo(
    () => new Map((missionStatus?.waypoints || []).map((item) => [item.id, item])),
    [missionStatus],
  );

  useEffect(() => {
    if (!candidate) return;
    setCandidateName(`WP-${String(waypoints.length + 1).padStart(2, "0")}`);
    setCandidateYaw(0);
    setCandidateDwell(2);
  }, [candidate?.mapX, candidate?.mapY, waypoints.length]);

  const addCandidate = () => {
    onAdd({
      name: candidateName,
      yaw: degreesToRadians(candidateYaw),
      dwell_seconds: Math.max(0, Math.min(300, Number(candidateDwell) || 0)),
    });
  };

  return (
    <section className="detail-card waypoint-mission-card">
      <div className="detail-card-title">
        <ListNumbers size={20} />
        <div>
          <strong>순찰 웨이포인트</strong>
          <span>{enabledCount}개 지점 · 사용자 순서</span>
        </div>
      </div>

      {!mapLive && (
        <div className="route-notice warning">
          실시간 ROS 지도가 연결되어야 좌표를 추가하고 주행할 수 있습니다.
        </div>
      )}
      {mapMismatch && (
        <div className="route-notice danger">
          저장한 경로와 현재 지도 버전이 다릅니다. 좌표를 확인한 후 다시 저장하세요.
        </div>
      )}
      {!patrolModeReady && (
        <div className="route-notice warning">
          <strong>{patrolModeSelected ? "AMCL·Nav2 준비 중" : "순찰 모드 전환 필요"}</strong>
          <span>
            {patrolModeSelected
              ? (readinessMessage || "위치 추정과 주행 서버가 준비될 때까지 기다리세요.")
              : "맵 생성 모드에서는 로봇 이동 명령을 내릴 수 없습니다. AMCL·Nav2 순찰 모드로 전환한 뒤 임무를 시작하세요."}
          </span>
        </div>
      )}
      {missionStatus?.status === "failed" && (
        <div className="route-notice danger">
          <strong>순찰 중단</strong>
          <span>{missionStatus.message}</span>
        </div>
      )}

      <button
        type="button"
        className={`button ${goalMode ? "secondary" : "primary"} wide-button waypoint-add-button`}
        disabled={missionActive || !mapLive}
        onClick={onToggleAdd}
      >
        {goalMode ? <X size={17} /> : <Crosshair size={17} />}
        {goalMode
          ? (repositioning ? "위치 재지정 취소" : "웨이포인트 추가 취소")
          : "지도에서 웨이포인트 추가"}
      </button>

      {goalMode && !candidate && (
        <div className="route-notice">
          {repositioning
            ? "지도에서 선택한 웨이포인트의 새 위치를 클릭하세요."
            : "지도에서 점검할 위치를 클릭하세요. 여러 지점을 연속해서 추가할 수 있습니다."}
        </div>
      )}

      {candidate && (
        <div className="waypoint-candidate-editor">
          <div className="candidate-coordinate">
            <NavigationArrow size={17} weight="fill" />
            <span>
              X {candidate.mapX?.toFixed(2)}m · Y {candidate.mapY?.toFixed(2)}m
            </span>
          </div>
          <label>
            <span>이름</span>
            <input
              value={candidateName}
              maxLength={40}
              onChange={(event) => setCandidateName(event.target.value)}
              placeholder="예: 펌프 점검구역"
            />
          </label>
          <div className="candidate-fields">
            <label>
              <span>바라볼 방향</span>
              <div className="input-suffix">
                <input
                  type="number"
                  min="-180"
                  max="180"
                  value={candidateYaw}
                  onChange={(event) => setCandidateYaw(event.target.value)}
                />
                <i>°</i>
              </div>
            </label>
            <label>
              <span>도착 후 대기</span>
              <div className="input-suffix">
                <input
                  type="number"
                  min="0"
                  max="300"
                  value={candidateDwell}
                  onChange={(event) => setCandidateDwell(event.target.value)}
                />
                <i>초</i>
              </div>
            </label>
          </div>
          <div className="candidate-actions">
            <button type="button" className="button ghost" onClick={onCancelCandidate}>
              <X size={16} />취소
            </button>
            <button
              type="button"
              className="button primary"
              disabled={!candidateName.trim()}
              onClick={addCandidate}
            >
              <Check size={16} weight="bold" />추가
            </button>
          </div>
        </div>
      )}

      <div className="waypoint-list" aria-label="순찰 웨이포인트 순서">
        {waypoints.length === 0 && (
          <div className="waypoint-empty">
            지도에서 웨이포인트 추가를 시작하세요.
          </div>
        )}
        {waypoints.map((waypoint, index) => {
          const itemStatus = missionById.get(waypoint.id);
          const selected = selectedId === waypoint.id;
          return (
            <div
              key={waypoint.id}
              className={`waypoint-row ${selected ? "selected" : ""} ${draggingId === waypoint.id ? "dragging" : ""}`}
              draggable={!missionActive}
              onDragStart={(event) => {
                setDraggingId(waypoint.id);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", waypoint.id);
              }}
              onDragEnd={() => setDraggingId(null)}
              onDragOver={(event) => {
                if (!missionActive) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                const sourceId = event.dataTransfer.getData("text/plain");
                if (sourceId) onMove(sourceId, waypoint.id);
                setDraggingId(null);
              }}
            >
              <button
                type="button"
                className="waypoint-row-main"
                onClick={() => onSelect(waypoint.id)}
              >
                <DotsSixVertical className="waypoint-drag" size={16} />
                <span className="waypoint-index">{index + 1}</span>
                <span className="waypoint-summary">
                  <strong>{waypoint.name}</strong>
                  <small>
                    X {waypoint.x.toFixed(2)} · Y {waypoint.y.toFixed(2)} · {radiansToDegrees(waypoint.yaw)}°
                  </small>
                </span>
                {itemStatus && (
                  <span className={`waypoint-run-state ${itemStatus.status}`}>
                    {waypointStateLabels[itemStatus.status] || itemStatus.status}
                  </span>
                )}
              </button>

              {selected && (
                <div className="waypoint-editor">
                  <label>
                    <span>이름</span>
                    <input
                      value={waypoint.name}
                      maxLength={40}
                      disabled={missionActive}
                      onChange={(event) => onUpdate(waypoint.id, { name: event.target.value })}
                    />
                  </label>
                  <div className="candidate-fields">
                    <label>
                      <span>방향</span>
                      <div className="input-suffix">
                        <input
                          type="number"
                          min="-180"
                          max="180"
                          disabled={missionActive}
                          value={radiansToDegrees(waypoint.yaw)}
                          onChange={(event) => onUpdate(waypoint.id, {
                            yaw: degreesToRadians(event.target.value),
                          })}
                        />
                        <i>°</i>
                      </div>
                    </label>
                    <label>
                      <span>대기</span>
                      <div className="input-suffix">
                        <input
                          type="number"
                          min="0"
                          max="300"
                          disabled={missionActive}
                          value={waypoint.dwell_seconds}
                          onChange={(event) => onUpdate(waypoint.id, {
                            dwell_seconds: Math.max(0, Math.min(300, Number(event.target.value) || 0)),
                          })}
                        />
                        <i>초</i>
                      </div>
                    </label>
                  </div>
                  {Number.isFinite(itemStatus?.yaw_error_deg) && (
                    <div className="waypoint-arrival-error">
                      최근 도착 오차 · 위치 {Number(itemStatus.position_error_m).toFixed(2)}m
                      · 방향 {Number(itemStatus.yaw_error_deg).toFixed(1)}°
                    </div>
                  )}
                  <div className="waypoint-editor-actions">
                    <button
                      type="button"
                      title="한 칸 위로"
                      disabled={missionActive || index === 0}
                      onClick={() => onShift(waypoint.id, -1)}
                    >
                      <ArrowUp size={15} />
                    </button>
                    <button
                      type="button"
                      title="한 칸 아래로"
                      disabled={missionActive || index === waypoints.length - 1}
                      onClick={() => onShift(waypoint.id, 1)}
                    >
                      <ArrowDown size={15} />
                    </button>
                    <button
                      type="button"
                      title="지도에서 위치 다시 지정"
                      disabled={missionActive}
                      onClick={() => onReposition(waypoint.id)}
                    >
                      <Crosshair size={15} />
                    </button>
                    <button
                      type="button"
                      className="danger"
                      title="삭제"
                      disabled={missionActive}
                      onClick={() => onDelete(waypoint.id)}
                    >
                      <Trash size={15} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="route-tools">
        <button
          type="button"
          className="button ghost"
          disabled={busy || missionActive || enabledCount < 2 || !mapLive}
          onClick={onRecommend}
        >
          <Sparkle size={17} weight="fill" />순서 추천
        </button>
        <button
          type="button"
          className="button ghost"
          disabled={missionActive || waypoints.length === 0}
          onClick={onSave}
        >
          <FloppyDisk size={17} />경로 저장
        </button>
      </div>

      <div className="route-primary-actions">
        {missionActive ? (
          <button type="button" className="button danger-button wide-button" onClick={onCancelMission}>
            <Stop size={18} weight="fill" />순찰 중단
          </button>
        ) : !patrolModeReady ? (
          <button
            type="button"
            className="button secondary wide-button"
            disabled={busy || modeTransitioning || patrolModeSelected || !modeControlEnabled}
            onClick={onRequestPatrolMode}
          >
            <NavigationArrow size={18} weight="fill" />
            {patrolModeSelected || modeTransitioning
              ? "순찰 모드 준비 중"
              : "순찰 모드로 전환"}
          </button>
        ) : (
          <button
            type="button"
            className="button primary wide-button"
            disabled={busy || enabledCount === 0 || !mapLive || mapMismatch}
            onClick={onStart}
          >
            <Play size={18} weight="fill" />이 순서로 순찰 시작
          </button>
        )}
        {!missionActive && waypoints.length > 0 && (
          <button type="button" className="text-button danger-text" onClick={onClear}>
            전체 웨이포인트 삭제
          </button>
        )}
      </div>
    </section>
  );
}
