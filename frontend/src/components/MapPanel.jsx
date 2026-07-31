import { useEffect, useRef, useState } from "react";
import {
  CaretRight,
  Crosshair,
  NavigationArrow,
} from "@phosphor-icons/react";
import slamMap from "../assets/slam-map.webp";
import {
  buildFootprintPolygon,
  buildFovPolygon,
  detectionOpacity,
  fallbackSpatialState,
  mapToGrid,
  resolveMapSpec,
  sensorLegend,
  temperatureColor,
  temperatureLevel,
} from "../spatial.js";
import {
  CurrentTime,
  LiveImage,
  PanelHeader,
} from "./Common.jsx";

function SpatialMapOverlay({
  spatialState,
  mapSpec,
  layers,
  detail,
  waypoints = [],
  selectedWaypointId = null,
  onWaypointSelect,
}) {
  const pose = spatialState?.pose;
  const trail = (spatialState?.trail || [])
    .map((point) => mapToGrid(point.x, point.y, mapSpec))
    .filter(Boolean);
  const sensors = spatialState?.sensors || [];
  const detections = spatialState?.heatmap?.detections || [];
  const posePoint = pose?.available ? mapToGrid(pose.x, pose.y, mapSpec) : null;
  const robotLength = Math.max(3.2, Math.min(5, 0.22 / mapSpec.resolution));
  const robotWidth = robotLength * 0.72;
  const robotAngle = pose?.available ? (-pose.yaw * 180) / Math.PI : 0;
  const waypointPoints = waypoints
    .map((waypoint) => ({ waypoint, point: mapToGrid(waypoint.x, waypoint.y, mapSpec) }))
    .filter((item) => item.point);

  return (
    <svg
      className="spatial-map-overlay"
      viewBox={`0 0 ${mapSpec.width} ${mapSpec.height}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="로봇 위치, 카메라 시야각, 이동 궤적 및 열원 히트맵"
    >
      <defs>
        <filter id="heat-blur" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="3.2" />
        </filter>
        <filter id="robot-shadow" x="-80%" y="-80%" width="260%" height="260%">
          <feDropShadow dx="0" dy="1" stdDeviation="1.2" floodColor="#173e68" floodOpacity=".35" />
        </filter>
      </defs>

      {layers.trail && trail.length > 1 && (
        <polyline
          className="robot-trail"
          points={trail.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")}
        />
      )}

      {waypointPoints.length > 1 && (
        <polyline
          className="waypoint-route-line"
          points={waypointPoints.map(({ point }) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")}
        />
      )}

      {pose?.available && sensors.map((sensor) => (
        layers[sensor.id] ? (
          <polygon
            key={sensor.id}
            className={`sensor-sector sensor-sector-${sensor.id}`}
            points={buildFovPolygon(pose, sensor, mapSpec)}
          />
        ) : null
      ))}

      {layers.heatmap && detections.map((detection) => {
        const point = mapToGrid(detection.x, detection.y, mapSpec);
        if (!point) return null;
        const radius = Math.max(4, detection.radius_m / mapSpec.resolution);
        const color = temperatureColor(detection.temperature_c);
        const opacity = detectionOpacity(detection);
        return (
          <g key={detection.detection_id} className="heat-detection">
            <circle
              className="heat-blob"
              cx={point.x}
              cy={point.y}
              r={radius * 2.5}
              fill={color}
              opacity={opacity * 0.34}
              filter="url(#heat-blur)"
            />
            <circle
              className="heat-core"
              cx={point.x}
              cy={point.y}
              r={Math.max(2.4, radius * 0.34)}
              fill={color}
              opacity={Math.max(0.58, opacity)}
            />
            <circle
              className="heat-ring"
              cx={point.x}
              cy={point.y}
              r={Math.max(4.6, radius * 0.68)}
              stroke={color}
              opacity={Math.max(0.5, opacity)}
            />
            {detail && (
              <g className="heat-label" transform={`translate(${point.x + radius * 0.72} ${point.y - radius * 0.72})`}>
                <rect x="0" y="-7.5" width="27" height="11" rx="2.5" />
                <text x="3.2" y="-2.3">{detection.temperature_c.toFixed(1)}°C</text>
                <text className="heat-label-level" x="3.2" y="1.2">{temperatureLevel(detection.temperature_c)}</text>
              </g>
            )}
          </g>
        );
      })}

      {posePoint && (
        <>
          {layers.footprint && (
            <polygon
              className="robot-footprint"
              points={buildFootprintPolygon(pose, mapSpec)}
            />
          )}
        <g
          className="live-robot"
          transform={`translate(${posePoint.x} ${posePoint.y}) rotate(${robotAngle})`}
          filter="url(#robot-shadow)"
        >
          <rect
            x={-robotLength * 0.55}
            y={-robotWidth * 0.62}
            width={robotLength * 1.18}
            height={robotWidth * 1.24}
            rx={robotWidth * 0.28}
            className="live-robot-halo"
          />
          <rect
            x={-robotLength * 0.42}
            y={-robotWidth * 0.43}
            width={robotLength * 0.86}
            height={robotWidth * 0.86}
            rx={robotWidth * 0.12}
            className="live-robot-deck"
          />
          <rect x={-robotLength * 0.28} y={-robotWidth * 0.31} width={robotLength * 0.52} height={robotWidth * 0.62} rx={robotWidth * 0.06} className="live-robot-frame" />
          {[
            [-0.27, -0.58],
            [-0.27, 0.58],
            [0.27, -0.58],
            [0.27, 0.58],
          ].map(([x, y], index) => (
            <rect
              key={index}
              x={robotLength * x - robotLength * 0.13}
              y={robotWidth * y - robotWidth * 0.12}
              width={robotLength * 0.26}
              height={robotWidth * 0.24}
              rx={robotWidth * 0.08}
              className="live-robot-wheel"
            />
          ))}
          <circle cx={-robotLength * 0.04} cy="0" r={robotWidth * 0.13} className="live-robot-lidar" />
          <rect x={robotLength * 0.27} y={-robotWidth * 0.17} width={robotLength * 0.17} height={robotWidth * 0.34} rx={robotWidth * 0.05} className="live-robot-camera" />
          <path d={`M ${robotLength * 0.48} ${-robotWidth * 0.28} L ${robotLength * 0.78} 0 L ${robotLength * 0.48} ${robotWidth * 0.28} Z`} className="live-robot-front" />
        </g>
        </>
      )}

      {waypointPoints.map(({ waypoint, point }, index) => (
        <g
          key={waypoint.id}
          className={`waypoint-marker-map ${selectedWaypointId === waypoint.id ? "selected" : ""}`}
          transform={`translate(${point.x} ${point.y})`}
          role="button"
          aria-label={`${index + 1}번 웨이포인트 ${waypoint.name}`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => onWaypointSelect?.(waypoint.id)}
        >
          <g transform={`rotate(${(-waypoint.yaw * 180) / Math.PI})`}>
            <line
              className="waypoint-heading-line"
              x1="2"
              y1="0"
              x2="8"
              y2="0"
            />
            <path className="waypoint-heading-arrow" d="M 8 0 L 6.4 -1.1 L 6.4 1.1 Z" />
          </g>
          <circle r="2.4" />
          <text x="0" y=".15">{index + 1}</text>
        </g>
      ))}
    </svg>
  );
}

export default function MapPanel({
  onLocate,
  onOpen,
  mediaStatus,
  spatialState = fallbackSpatialState,
  layers = { depth: true, thermal: true, heatmap: true, trail: true },
  detail = false,
  goalMode = false,
  goalCandidate,
  onGoalCandidate,
  waypoints = [],
  selectedWaypointId = null,
  onWaypointSelect,
}) {
  const mapLive = Boolean(mediaStatus?.map?.available);
  const mapSpec = resolveMapSpec(mediaStatus, spatialState);
  const depthLegend = sensorLegend(spatialState, "depth");
  const thermalLegend = sensorLegend(spatialState, "thermal");
  const stageRef = useRef(null);
  const dragRef = useRef(null);
  const [mapView, setMapView] = useState({ zoom: 1, x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });

  const fitScale = stageSize.width && stageSize.height
    ? Math.min(stageSize.width / mapSpec.width, stageSize.height / mapSpec.height)
    : 1;
  const imageGeometry = {
    width: mapSpec.width * fitScale,
    height: mapSpec.height * fitScale,
    left: (stageSize.width - mapSpec.width * fitScale) / 2,
    top: (stageSize.height - mapSpec.height * fitScale) / 2,
  };

  const clampPan = (x, y, zoom) => {
    const bounds = stageRef.current?.getBoundingClientRect();
    if (!bounds) return { x, y };
    const maxX = Math.max(0, (bounds.width * (zoom - 1)) / 2);
    const maxY = Math.max(0, (bounds.height * (zoom - 1)) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, x)),
      y: Math.min(maxY, Math.max(-maxY, y)),
    };
  };

  const changeZoom = (delta) => {
    setMapView((current) => {
      const zoom = Math.min(4, Math.max(0.5, Number((current.zoom + delta).toFixed(2))));
      const ratio = zoom / current.zoom;
      const pan = clampPan(current.x * ratio, current.y * ratio, zoom);
      return { zoom, ...pan };
    });
  };

  const resetMapView = () => {
    setMapView({ zoom: 1, x: 0, y: 0 });
    onLocate();
  };

  const startMapDrag = (event) => {
    if (event.button !== 0 || event.target.closest(".map-zoom")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: mapView.x,
      originY: mapView.y,
    };
    setDragging(true);
  };

  const moveMap = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const pan = clampPan(
      drag.originX + event.clientX - drag.startX,
      drag.originY + event.clientY - drag.startY,
      mapView.zoom,
    );
    setMapView((current) => ({ ...current, ...pan }));
  };

  const endMapDrag = (event) => {
    const drag = dragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const movement = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (goalMode && movement < 6 && onGoalCandidate) {
      const bounds = stageRef.current?.getBoundingClientRect();
      if (bounds) {
        const unscaledX = ((event.clientX - bounds.left) - bounds.width / 2 - mapView.x) / mapView.zoom + bounds.width / 2;
        const unscaledY = ((event.clientY - bounds.top) - bounds.height / 2 - mapView.y) / mapView.zoom + bounds.height / 2;
        const imageLeft = imageGeometry.left;
        const imageTop = imageGeometry.top;
        const imageWidth = imageGeometry.width;
        const imageHeight = imageGeometry.height;
        const normalizedX = (unscaledX - imageLeft) / imageWidth;
        const normalizedY = (unscaledY - imageTop) / imageHeight;
        if (normalizedX >= 0 && normalizedX <= 1 && normalizedY >= 0 && normalizedY <= 1) {
          const candidate = {
            screenX: ((imageLeft + normalizedX * imageWidth) / bounds.width) * 100,
            screenY: ((imageTop + normalizedY * imageHeight) / bounds.height) * 100,
            mapX: null,
            mapY: null,
            frameId: mapSpec.frame_id || "map",
          };
          if (
            mapLive
            && Number.isFinite(mapSpec.resolution)
            && Number.isFinite(mapSpec.origin_x)
            && Number.isFinite(mapSpec.origin_y)
          ) {
            candidate.mapX = mapSpec.origin_x + normalizedX * mapSpec.width * mapSpec.resolution;
            candidate.mapY = mapSpec.origin_y + (1 - normalizedY) * mapSpec.height * mapSpec.resolution;
          }
          onGoalCandidate(candidate);
        }
      }
    }
    dragRef.current = null;
    setDragging(false);
  };

  useEffect(() => {
    const handleResize = () => {
      const bounds = stageRef.current?.getBoundingClientRect();
      if (bounds) setStageSize({ width: bounds.width, height: bounds.height });
      setMapView((current) => ({
        ...current,
        ...clampPan(current.x, current.y, current.zoom),
      }));
    };
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(handleResize);
    if (stageRef.current) observer?.observe(stageRef.current);
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <section className={`panel map-panel ${detail ? "map-panel-detail" : ""}`}>
      <PanelHeader eyebrow="LIVE MAP" title="2D SLAM 지도" action={
        <div className="panel-actions">
          <CurrentTime />
          <button type="button" className="icon-action" aria-label="지도 중앙 정렬" title="지도 중앙 정렬" onClick={resetMapView}><Crosshair size={19} /></button>
          {onOpen && <button type="button" className="icon-action" aria-label="지도 상세 화면 열기" title="지도 상세 화면 열기" onClick={onOpen}><CaretRight size={19} /></button>}
        </div>
      } />
      <div
        ref={stageRef}
        className={`map-stage ${dragging ? "dragging" : ""} ${goalMode ? "goal-mode" : ""}`}
        aria-label="확대 및 드래그 가능한 2D SLAM 지도"
        onPointerDown={startMapDrag}
        onPointerMove={moveMap}
        onPointerUp={endMapDrag}
        onPointerCancel={endMapDrag}
      >
        <div
          className="map-canvas"
          style={{ transform: `translate3d(${mapView.x}px, ${mapView.y}px, 0) scale(${mapView.zoom})` }}
        >
          <div
            className="map-image-frame"
            style={{
              left: `${imageGeometry.left}px`,
              top: `${imageGeometry.top}px`,
              width: `${imageGeometry.width}px`,
              height: `${imageGeometry.height}px`,
            }}
          >
            <LiveImage className={mapLive ? "live-map" : ""} draggable="false" endpoint="/api/v1/media/map" fallback={slamMap} enabled={mapLive} interval={1000} alt="ROS 2 SLAM 점유 지도" />
            <SpatialMapOverlay
              spatialState={spatialState}
              mapSpec={mapSpec}
              layers={layers}
              detail={detail}
              waypoints={waypoints}
              selectedWaypointId={selectedWaypointId}
              onWaypointSelect={onWaypointSelect}
            />
          </div>
          {goalCandidate && (
            <div
              className="goal-marker"
              style={{ left: `${goalCandidate.screenX}%`, top: `${goalCandidate.screenY}%` }}
              aria-label="목적지 후보"
            >
              <NavigationArrow size={17} weight="fill" />
            </div>
          )}
        </div>
        <div className={`map-live-badge ${mapLive ? "" : "mock"}`}><span />{mapLive ? "SLAM · 공간 데이터 실시간" : "디지털 트윈 목업"}</div>
        {spatialState?.heatmap?.simulated && layers.heatmap && <div className="heatmap-simulation-badge">SIMULATED HEAT</div>}
        {goalMode && <div className="goal-mode-hint">지도를 클릭해 목적지 후보를 선택하세요</div>}
        {detail && (
          <div className="map-axis-guide" aria-label="ROS 지도 각도 기준">
            <span className="axis-y">↑ <strong>+Y</strong> 90°</span>
            <span className="axis-x"><strong>+X</strong> 0° →</span>
          </div>
        )}
        <div className="map-zoom" onPointerDown={(event) => event.stopPropagation()}>
          <button type="button" aria-label="지도 확대" title="지도 확대" disabled={mapView.zoom >= 4} onClick={() => changeZoom(0.25)}>+</button>
          <button type="button" aria-label="지도 축소" title="지도 축소" disabled={mapView.zoom <= 0.5} onClick={() => changeZoom(-0.25)}>−</button>
        </div>
      </div>
      <footer className="map-footer">
        <span><i className="legend-route" />이동 궤적</span>
        {depthLegend && <span><i className="legend-depth" />{depthLegend}</span>}
        {thermalLegend && <span><i className="legend-thermal" />{thermalLegend}</span>}
        <span><i className="legend-heat" />열원</span>
        <strong>{mapLive ? `ROS /map · ${Math.round(mapView.zoom * 100)}%` : `목업 · ${Math.round(mapView.zoom * 100)}%`}</strong>
      </footer>
    </section>
  );
}
