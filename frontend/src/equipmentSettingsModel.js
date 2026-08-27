export function optionalFiniteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeEquipmentSettings(payload) {
  return {
    schema_version: Number(payload?.schema_version || 1),
    world_id: payload?.world_id ?? null,
    map_session_id: payload?.map_session_id ?? null,
    frame_id: payload?.frame_id ?? null,
    geometry_fingerprint: payload?.geometry_fingerprint ?? null,
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

export function equipmentSyncStatus(runtime) {
  const state = String(runtime?.state || "unknown");
  const error = typeof runtime?.error === "string" && runtime.error.trim()
    ? runtime.error.trim()
    : null;
  const states = {
    applied: {
      label: "로봇 적용 완료",
      detail: "서버에 저장된 설정과 로봇의 실제 판정 설정이 일치합니다.",
      tone: "success",
    },
    pending: {
      label: "적용 대기",
      detail: "서버에는 저장됐으며 현재 순찰 종료 후 로봇에 적용됩니다.",
      tone: "pending",
    },
    syncing: {
      label: "적용 확인 중",
      detail: "서버 저장은 완료됐으며 로봇의 적용 응답을 기다리고 있습니다.",
      tone: "pending",
    },
    rejected: {
      label: "로봇 적용 실패",
      detail: "서버에는 저장됐지만 로봇은 안전을 위해 이전 설정을 유지합니다.",
      tone: "error",
    },
    offline: {
      label: "로봇 미연결",
      detail: "서버에는 저장됐지만 로봇 연결 후 다시 적용해야 합니다.",
      tone: "offline",
    },
    ready: {
      label: "로봇 설정 대기",
      detail: "열화상 분석 노드는 준비됐으며 저장 설정의 적용 응답을 기다립니다.",
      tone: "pending",
    },
  };
  return {
    state,
    error,
    canRetry: state === "rejected" || state === "offline",
    ...(states[state] || {
      label: "적용 상태 확인 필요",
      detail: "서버 저장 상태와 로봇 적용 상태를 확인하고 다시 적용하세요.",
      tone: "offline",
    }),
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
