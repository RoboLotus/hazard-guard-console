import * as THREE from 'three';

// Reuse the original PointCloudPanel scene/materials. Only its data source changes.
export function populateRecordedScene(scene, recording, variant) {
  const { points, colors, thermal, manifest } = recording;
  const rgb = new Float32Array(colors.length);
  const color = new THREE.Color();
  for (let i = 0; i < colors.length; i += 3) {
    color.setRGB(colors[i] / 255, colors[i + 1] / 255, colors[i + 2] / 255, THREE.SRGBColorSpace);
    color.toArray(rgb, i);
  }
  const fill = (geometry, xyz, colorValues) => {
    geometry.setAttribute('position', new THREE.BufferAttribute(xyz, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colorValues, 3));
    geometry.computeBoundingSphere();
  };
  if (variant !== 'thermal') { fill(scene.geometry, points, rgb); return; }
  fill(scene.baseGeometry, points, rgb);
  const xyz = new Float32Array(thermal.indices.length * 3);
  thermal.indices.forEach((index, i) => xyz.set(points.subarray(index * 3, index * 3 + 3), i * 3));
  fill(scene.geometry, xyz, new Float32Array(xyz.length).fill(1));
  scene.geometry.setAttribute('temperature', new THREE.BufferAttribute(new Float32Array(thermal.temperatures), 1));
  // Confidence opacity is disabled: archived conversion does not contain confidence.
  scene.geometry.setAttribute('confidence', new THREE.BufferAttribute(new Float32Array(thermal.indices.length), 1));
  scene.material.uniforms.uConfidenceOpacityEnabled.value = 0;
  scene.material.uniforms.uTemperatureMin.value = manifest.temperatureMin;
  scene.material.uniforms.uTemperatureMax.value = manifest.temperatureMax;
  scene.dynamicPoints.visible = false;
}
