export function optionalFiniteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeEquipmentSettings(payload) {
  return {
    schema_version: Number(payload?.schema_version || 1),
    equipment: Array.isArray(payload?.equipment)
      ? payload.equipment.map((item) => ({
        ...item,
        adaptive_threshold_enabled: item.adaptive_threshold_enabled !== false,
      }))
      : [],
  };
}

export function adaptivePolicyConfirmation(enabled, runtimeState) {
  return {
    title: enabled
      ? "자동 가변 기준을 사용할까요?"
      : "고정 임계값만 사용할까요?",
    description: enabled
      ? "승인된 정상 기준선과 순찰 간 상승 추세를 함께 사용합니다. 기준선 수집 중이면 완료 후 자동 적용됩니다."
      : "기준선 파일은 보존하지만 가변 이탈 경고를 중지합니다. 절대 위험온도 판정은 계속 작동합니다.",
    impact: runtimeState === "pending"
      ? "현재 순찰 종료 후 변경됩니다."
      : "설정 저장 후 다음 설비 검사부터 적용됩니다.",
    confirmLabel: enabled
      ? "자동 가변 기준 사용"
      : "고정 임계값만 사용",
    danger: !enabled,
  };
}

export function effectiveThresholdSummary(runtime, equipment) {
  const minimum = optionalFiniteNumber(
    runtime?.effective_adaptive_threshold_min_c,
  );
  const maximum = optionalFiniteNumber(
    runtime?.effective_adaptive_threshold_max_c,
  );
  if (minimum !== null && maximum !== null) {
    if (Math.abs(maximum - minimum) < 0.05) {
      return `${maximum.toFixed(1)}°C (최근 voxel)`;
    }
    return `${minimum.toFixed(1)}~${maximum.toFixed(1)}°C (최근 voxel 범위)`;
  }
  const legacy = optionalFiniteNumber(
    runtime?.effective_adaptive_threshold_c,
  );
  if (legacy !== null) {
    return `${legacy.toFixed(1)}°C (이전 형식·상한)`;
  }
  const baseline = optionalFiniteNumber(runtime?.baseline_temperature_c);
  const delta = optionalFiniteNumber(equipment?.adaptive_delta_c);
  if (baseline !== null && delta !== null) {
    return `${(baseline + delta).toFixed(1)}°C (설비 기준선 추정)`;
  }
  return "기준선 활성화 후 계산";
}
