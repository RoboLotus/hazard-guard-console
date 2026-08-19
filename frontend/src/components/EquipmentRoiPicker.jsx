import { Crosshair, MapTrifold } from "@phosphor-icons/react";
import { useState } from "react";

function pointToGrid(point, mapSpec) {
  return {
    x: (point[0] - mapSpec.origin_x) / mapSpec.resolution,
    y: mapSpec.height - (point[1] - mapSpec.origin_y) / mapSpec.resolution,
  };
}

function rectangleFor(item, mapSpec) {
  const minimum = pointToGrid(item.roi.min, mapSpec);
  const maximum = pointToGrid(item.roi.max, mapSpec);
  return {
    x: Math.min(minimum.x, maximum.x),
    y: Math.min(minimum.y, maximum.y),
    width: Math.abs(maximum.x - minimum.x),
    height: Math.abs(maximum.y - minimum.y),
  };
}

function validMapSpec(mapSpec) {
  return mapSpec
    && Number.isFinite(mapSpec.width)
    && Number.isFinite(mapSpec.height)
    && Number.isFinite(mapSpec.resolution)
    && mapSpec.width > 0
    && mapSpec.height > 0
    && mapSpec.resolution > 0;
}

export default function EquipmentRoiPicker({ equipment, equipmentList, mapSpec, onApply }) {
  const [start, setStart] = useState(null);
  const available = validMapSpec(mapSpec);

  const pick = (event) => {
    if (!available) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const normalizedX = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const normalizedY = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
    const point = {
      x: mapSpec.origin_x + normalizedX * mapSpec.width * mapSpec.resolution,
      y: mapSpec.origin_y + (1 - normalizedY) * mapSpec.height * mapSpec.resolution,
    };
    if (!start) {
      setStart(point);
      return;
    }
    onApply({
      minimum: [Math.min(start.x, point.x), Math.min(start.y, point.y)],
      maximum: [Math.max(start.x, point.x), Math.max(start.y, point.y)],
    });
    setStart(null);
  };

  return (
    <div className="roi-map-picker">
      <div className="roi-picker-guide">
        <MapTrifold size={18} weight="duotone" />
        <div>
          <strong>{start ? "두 번째 모서리를 선택하세요" : "첫 번째 모서리를 선택하세요"}</strong>
          <small>XY 범위만 변경되며 Z 높이는 아래 숫자 입력값을 유지합니다.</small>
        </div>
        {start && (
          <button type="button" className="button ghost compact" onClick={() => setStart(null)}>
            선택 취소
          </button>
        )}
      </div>
      {available ? (
        <svg
          className="roi-map-stage"
          viewBox={`0 0 ${mapSpec.width} ${mapSpec.height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="설비 ROI XY 범위 지정 지도"
          onPointerDown={pick}
        >
          <image
            href="/api/v1/media/map"
            width={mapSpec.width}
            height={mapSpec.height}
            preserveAspectRatio="none"
          />
          {equipmentList.filter((item) => item.enabled).map((item) => {
            const rectangle = rectangleFor(item, mapSpec);
            return (
              <g key={item.id} className={item.id === equipment.id ? "selected" : ""}>
                <rect {...rectangle} />
                <text x={rectangle.x + 2} y={rectangle.y + 8}>{item.display_name}</text>
              </g>
            );
          })}
          {start && (() => {
            const point = pointToGrid([start.x, start.y], mapSpec);
            return <circle className="roi-pick-start" cx={point.x} cy={point.y} r="4" />;
          })()}
        </svg>
      ) : (
        <div className="roi-map-unavailable">
          <Crosshair size={22} />
          <span>실시간 2D 지도 메타데이터를 기다리고 있습니다.</span>
        </div>
      )}
    </div>
  );
}
