import { useEffect } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { fitCameraToCloud, createRobotMarker, disposeObject3d } from "../pointCloudScene.js";
import { createThermalPointMaterial } from "../thermalPointMaterial.js";

export function usePointCloudScene({ mountRef, sceneRef, fitRef, variant, spec, thermalRenderConfig }) {
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111a25);
    scene.fog = new THREE.FogExp2(0x111a25, 0.025);
    const camera = new THREE.PerspectiveCamera(48, 1, 0.01, 200);
    camera.up.set(0, 0, 1);
    camera.position.set(4.5, -5.5, 3.6);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-label", spec.ariaLabel);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, 0.6);
    controls.update();

    const grid = new THREE.GridHelper(12, 24, 0x315f8f, 0x273849);
    grid.rotation.x = Math.PI / 2;
    grid.material.opacity = 0.5;
    grid.material.transparent = true;
    scene.add(grid);
    const axes = new THREE.AxesHelper(0.75);
    scene.add(axes);

    const geometry = new THREE.BufferGeometry();
    const baseGeometry = variant === "thermal" ? new THREE.BufferGeometry() : null;
    const baseMaterial = variant === "thermal" ? new THREE.PointsMaterial({
      size: 0.035,
      sizeAttenuation: true,
      vertexColors: true,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
    }) : null;
    const basePoints = baseGeometry && baseMaterial
      ? new THREE.Points(baseGeometry, baseMaterial)
      : null;
    if (basePoints) scene.add(basePoints);
    const material = variant === "thermal"
      ? createThermalPointMaterial({ config: thermalRenderConfig })
      : new THREE.PointsMaterial({ size: 0.035, sizeAttenuation: true, vertexColors: true });
    const points = new THREE.Points(geometry, material);
    scene.add(points);
    const dynamicGeometry = new THREE.BufferGeometry();
    const dynamicMaterial = variant === "thermal"
      ? createThermalPointMaterial({ dynamic: true, config: thermalRenderConfig })
      : material;
    const dynamicPoints = new THREE.Points(dynamicGeometry, dynamicMaterial);
    dynamicPoints.frustumCulled = false;
    dynamicPoints.visible = variant === "thermal";
    scene.add(dynamicPoints);
    const robotMarker = createRobotMarker();
    scene.add(robotMarker.group);
    const equipmentGroup = new THREE.Group();
    equipmentGroup.name = "hazard-guard-equipment-rois";
    scene.add(equipmentGroup);
    sceneRef.current = {
      camera,
      controls,
      geometry,
      baseGeometry,
      baseMaterial,
      basePoints,
      material,
      dynamicMaterial,
      points,
      dynamicGeometry,
      dynamicPoints,
      renderer,
      robotMarker,
      equipmentGroup,
    };
    fitRef.current = () => {
      const basePositions = baseGeometry?.getAttribute("position");
      fitCameraToCloud(
        camera,
        controls,
        basePositions?.count ? baseGeometry : geometry,
      );
    };

    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      renderer.setSize(width, height, false);
      if (material.uniforms?.uPointScale) material.uniforms.uPointScale.value = height * renderer.getPixelRatio() * 0.5;
      if (dynamicMaterial.uniforms?.uPointScale) dynamicMaterial.uniforms.uPointScale.value = height * renderer.getPixelRatio() * 0.5;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    let animationFrame;
    const render = () => {
      controls.update();
      const elapsed = performance.now() * 0.001;
      if (material.uniforms?.uTime) material.uniforms.uTime.value = elapsed;
      if (dynamicMaterial.uniforms?.uTime) dynamicMaterial.uniforms.uTime.value = elapsed;
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animationFrame);
      controls.dispose();
      geometry.dispose();
      dynamicGeometry.dispose();
      material.dispose();
      if (dynamicMaterial !== material) dynamicMaterial.dispose();
      baseGeometry?.dispose();
      baseMaterial?.dispose();
      robotMarker.dispose();
      disposeObject3d(grid);
      disposeObject3d(axes);
      renderer.dispose();
      renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, []);

}
