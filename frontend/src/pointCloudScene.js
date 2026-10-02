import * as THREE from "three";

export function fitCameraToCloud(camera, controls, geometry) {
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox;
  if (!bounds || bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const distance = Math.max(size.length() * 0.85, 2.5);
  controls.target.copy(center);
  camera.position.set(
    center.x + distance * 0.72,
    center.y - distance,
    center.z + distance * 0.62,
  );
  camera.near = Math.max(distance / 1000, 0.01);
  camera.far = Math.max(distance * 20, 100);
  camera.updateProjectionMatrix();
  controls.update();
}

export function createRobotMarker() {
  const group = new THREE.Group();
  group.name = "hazard-guard-robot-marker";
  group.visible = false;

  const chassisMaterial = new THREE.MeshBasicMaterial({ color: 0x2f80ed });
  const frontMaterial = new THREE.MeshBasicMaterial({ color: 0xe9f4ff });
  const ringMaterial = new THREE.MeshBasicMaterial({
    color: 0x66b6ff,
    transparent: true,
    opacity: 0.72,
    side: THREE.DoubleSide,
  });
  const chassisGeometry = new THREE.BoxGeometry(0.34, 0.26, 0.12);
  const frontGeometry = new THREE.ConeGeometry(0.075, 0.18, 3);
  const ringGeometry = new THREE.RingGeometry(0.22, 0.25, 40);

  const chassis = new THREE.Mesh(chassisGeometry, chassisMaterial);
  chassis.position.z = 0.07;
  group.add(chassis);

  const front = new THREE.Mesh(frontGeometry, frontMaterial);
  front.rotation.z = -Math.PI / 2;
  front.position.set(0.25, 0, 0.08);
  group.add(front);

  const ring = new THREE.Mesh(ringGeometry, ringMaterial);
  ring.position.z = 0.006;
  group.add(ring);

  return {
    group,
    setStale(stale) {
      chassisMaterial.color.setHex(stale ? 0x748190 : 0x2f80ed);
      frontMaterial.color.setHex(stale ? 0xb8c0c8 : 0xe9f4ff);
      ringMaterial.color.setHex(stale ? 0x8a949f : 0x66b6ff);
    },
    dispose() {
      chassisGeometry.dispose();
      frontGeometry.dispose();
      ringGeometry.dispose();
      chassisMaterial.dispose();
      frontMaterial.dispose();
      ringMaterial.dispose();
    },
  };
}

export function createEquipmentLabelSprite(item, selected) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const label = String(item.display_name || item.id || "설비");
  const background = selected ? "rgba(154, 96, 13, .94)" : "rgba(18, 43, 62, .92)";

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = background;
  context.beginPath();
  context.roundRect(4, 4, canvas.width - 8, canvas.height - 8, 24);
  context.fill();
  context.strokeStyle = selected ? "#ffd27a" : "#86c8ff";
  context.lineWidth = 5;
  context.stroke();
  context.fillStyle = "#ffffff";
  context.font = '800 46px "Pretendard Variable", Pretendard, sans-serif';
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, canvas.width / 2, canvas.height / 2, canvas.width - 48);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  const width = Math.max(0.62, Math.min(1.4, 0.44 + label.length * 0.075));
  sprite.scale.set(width, width / 4, 1);
  sprite.center.set(0.5, 0);
  sprite.renderOrder = 20;
  sprite.userData.equipmentId = item.id;
  sprite.userData.isEquipmentLabel = true;
  return sprite;
}

export function disposeObject3d(object) {
  object.traverse((child) => {
    child.geometry?.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.filter(Boolean).forEach((material) => {
      material.map?.dispose();
      material.dispose();
    });
  });
}
