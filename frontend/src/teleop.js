export const TELEOP_KEY_DIRECTIONS = Object.freeze({
  ArrowUp: "forward",
  KeyW: "forward",
  ArrowDown: "backward",
  KeyS: "backward",
  ArrowLeft: "left",
  KeyA: "left",
  ArrowRight: "right",
  KeyD: "right",
  Space: "stop",
});

export function teleopDirectionForKey(code) {
  return TELEOP_KEY_DIRECTIONS[code] || null;
}

export function isSimulationTeleopMode(mode) {
  return ["mapping", "rgbd_mapping", "patrol"].includes(mode);
}

export function isEditableKeyboardTarget(target) {
  const tagName = target?.tagName?.toLowerCase();
  return Boolean(
    target?.isContentEditable
    || tagName === "input"
    || tagName === "textarea"
    || tagName === "select"
  );
}
