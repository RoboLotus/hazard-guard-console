import * as THREE from "three";

export const DEFAULT_THERMAL_RENDER_CONFIG = Object.freeze({
  continuousGradient: true,
  circularSprite: true,
  temperatureSize: true,
  gaussianFalloff: true,
  confidenceOpacity: true,
  alertGlow: true,
  dynamicPulse: true,
  basePointSize: 0.055,
  maxTemperatureSizeIncrease: 0.28,
  minimumConfidenceOpacity: 0.18,
  warningTemperature: 60,
  criticalTemperature: 80,
  warningGlowStrength: 0.12,
  criticalGlowStrength: 0.22,
  dynamicGlowMultiplier: 1.18,
  pulseAmount: 0.07,
  pulseSpeed: 2.2,
  gaussianStrength: 2.8,
});

export function resolveThermalRenderConfig(overrides = {}) {
  return { ...DEFAULT_THERMAL_RENDER_CONFIG, ...overrides };
}

const vertexShader = /* glsl */`
  attribute float temperature;
  attribute float confidence;
  uniform float uTime;
  uniform float uPointScale;
  uniform float uBasePointSize;
  uniform float uTemperatureMin;
  uniform float uTemperatureMax;
  uniform float uWarningTemperature;
  uniform float uCriticalTemperature;
  uniform float uMaxTemperatureSizeIncrease;
  uniform float uPulseAmount;
  uniform float uPulseSpeed;
  uniform float uTemperatureSizeEnabled;
  uniform float uDynamicPulseEnabled;
  uniform float uIsDynamic;
  varying vec3 vSourceColor;
  varying float vTemperature;
  varying float vTemperatureRatio;
  varying float vConfidence;
  varying float vPulse;

  void main() {
    vSourceColor = color;
    vTemperature = temperature;
    vTemperatureRatio = clamp(
      (temperature - uTemperatureMin) / max(uTemperatureMax - uTemperatureMin, 0.0001),
      0.0,
      1.0
    );
    vConfidence = clamp(confidence, 0.0, 1.0);
    float phase = uTime * uPulseSpeed + dot(position, vec3(1.7, 2.3, 1.1));
    vPulse = 0.5 + 0.5 * sin(phase);
    float temperatureScale = mix(1.0, 1.0 + vTemperatureRatio * uMaxTemperatureSizeIncrease, uTemperatureSizeEnabled);
    float alert = smoothstep(uWarningTemperature - 1.0, uWarningTemperature + 1.0, temperature);
    float pulseScale = 1.0 + uIsDynamic * uDynamicPulseEnabled * alert * vPulse * uPulseAmount;
    vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * viewPosition;
    gl_PointSize = max(1.0, uBasePointSize * temperatureScale * pulseScale * uPointScale / max(-viewPosition.z, 0.01));
  }
`;

const fragmentShader = /* glsl */`
  uniform float uContinuousGradientEnabled;
  uniform float uCircularSpriteEnabled;
  uniform float uGaussianFalloffEnabled;
  uniform float uConfidenceOpacityEnabled;
  uniform float uAlertGlowEnabled;
  uniform float uDynamicPulseEnabled;
  uniform float uIsDynamic;
  uniform float uMinimumConfidenceOpacity;
  uniform float uWarningTemperature;
  uniform float uCriticalTemperature;
  uniform float uWarningGlowStrength;
  uniform float uCriticalGlowStrength;
  uniform float uDynamicGlowMultiplier;
  uniform float uGaussianStrength;
  varying vec3 vSourceColor;
  varying float vTemperature;
  varying float vTemperatureRatio;
  varying float vConfidence;
  varying float vPulse;

  vec3 heatGradient(float value) {
    float v = clamp(value, 0.0, 1.0);
    vec3 deepBlue = vec3(0.02, 0.08, 0.55);
    vec3 cyan = vec3(0.0, 0.82, 1.0);
    vec3 green = vec3(0.08, 0.95, 0.42);
    vec3 yellow = vec3(1.0, 0.88, 0.05);
    vec3 red = vec3(1.0, 0.06, 0.015);
    if (v < 0.25) return mix(deepBlue, cyan, smoothstep(0.0, 0.25, v));
    if (v < 0.5) return mix(cyan, green, smoothstep(0.25, 0.5, v));
    if (v < 0.75) return mix(green, yellow, smoothstep(0.5, 0.75, v));
    return mix(yellow, red, smoothstep(0.75, 1.0, v));
  }

  void main() {
    vec2 centered = gl_PointCoord * 2.0 - 1.0;
    float radiusSquared = dot(centered, centered);
    if (uCircularSpriteEnabled > 0.5 && radiusSquared > 1.0) discard;

    float gaussian = exp(-uGaussianStrength * radiusSquared);
    float shapeAlpha = mix(1.0, gaussian, uGaussianFalloffEnabled);
    float confidenceAlpha = mix(1.0, mix(uMinimumConfidenceOpacity, 1.0, vConfidence), uConfidenceOpacityEnabled);
    float warning = smoothstep(uWarningTemperature - 1.0, uWarningTemperature + 1.0, vTemperature);
    float critical = smoothstep(uCriticalTemperature - 1.0, uCriticalTemperature + 1.0, vTemperature);
    float glowStrength = warning * uWarningGlowStrength + critical * uCriticalGlowStrength;
    float dynamicStrength = mix(1.0, uDynamicGlowMultiplier, uIsDynamic);
    float pulse = mix(1.0, mix(0.93, 1.07, vPulse), uIsDynamic * uDynamicPulseEnabled * warning);
    float glow = uAlertGlowEnabled * glowStrength * dynamicStrength * pulse;
    vec3 baseColor = mix(vSourceColor, heatGradient(vTemperatureRatio), uContinuousGradientEnabled);
    vec3 color = baseColor * (1.0 + 0.14 * gaussian + glow * (0.35 + 0.65 * gaussian));
    float alpha = clamp(shapeAlpha * confidenceAlpha * (1.0 + glow * 0.18), 0.0, 1.0);
    if (alpha < 0.01) discard;
    gl_FragColor = vec4(color, alpha);
  }
`;

function flag(value) { return value ? 1 : 0; }

export function updateThermalPointMaterial(material, overrides = {}) {
  const config = resolveThermalRenderConfig(overrides);
  const values = {
    uContinuousGradientEnabled: flag(config.continuousGradient),
    uCircularSpriteEnabled: flag(config.circularSprite),
    uTemperatureSizeEnabled: flag(config.temperatureSize),
    uGaussianFalloffEnabled: flag(config.gaussianFalloff),
    uConfidenceOpacityEnabled: flag(config.confidenceOpacity),
    uAlertGlowEnabled: flag(config.alertGlow),
    uDynamicPulseEnabled: flag(config.dynamicPulse),
    uBasePointSize: config.basePointSize,
    uMaxTemperatureSizeIncrease: config.maxTemperatureSizeIncrease,
    uMinimumConfidenceOpacity: config.minimumConfidenceOpacity,
    uWarningTemperature: config.warningTemperature,
    uCriticalTemperature: config.criticalTemperature,
    uWarningGlowStrength: config.warningGlowStrength,
    uCriticalGlowStrength: config.criticalGlowStrength,
    uDynamicGlowMultiplier: config.dynamicGlowMultiplier,
    uPulseAmount: config.pulseAmount,
    uPulseSpeed: config.pulseSpeed,
    uGaussianStrength: config.gaussianStrength,
  };
  Object.entries(values).forEach(([name, value]) => { material.uniforms[name].value = value; });
  return config;
}

export function createThermalPointMaterial({ dynamic = false, config: overrides = {} } = {}) {
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPointScale: { value: 1 },
      uIsDynamic: { value: dynamic ? 1 : 0 },
      uTemperatureMin: { value: 20 },
      uTemperatureMax: { value: 40 },
      ...Object.fromEntries(Object.keys({
        uContinuousGradientEnabled: 0, uCircularSpriteEnabled: 0, uTemperatureSizeEnabled: 0,
        uGaussianFalloffEnabled: 0, uConfidenceOpacityEnabled: 0, uAlertGlowEnabled: 0,
        uDynamicPulseEnabled: 0, uBasePointSize: 0, uMaxTemperatureSizeIncrease: 0,
        uMinimumConfidenceOpacity: 0, uWarningTemperature: 0, uCriticalTemperature: 0,
        uWarningGlowStrength: 0, uCriticalGlowStrength: 0, uDynamicGlowMultiplier: 0,
        uPulseAmount: 0, uPulseSpeed: 0, uGaussianStrength: 0,
      }).map((name) => [name, { value: 0 }])),
    },
    vertexShader,
    fragmentShader,
    vertexColors: true,
    transparent: true,
    depthTest: true,
    depthWrite: false,
    blending: THREE.NormalBlending,
    toneMapped: false,
  });
  material.name = dynamic ? "thermal-dynamic-points" : "thermal-static-points";
  updateThermalPointMaterial(material, overrides);
  return material;
}

export function setThermalMaterialTemperatureWindow(material, minimum, maximum) {
  if (!material?.uniforms || !Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return;
  material.uniforms.uTemperatureMin.value = minimum;
  material.uniforms.uTemperatureMax.value = maximum;
}
