import test from "node:test";
import assert from "node:assert/strict";

import {
  isEditableKeyboardTarget,
  isSimulationTeleopMode,
  teleopDirectionForKey,
} from "../src/teleop.js";

test("teleop maps arrows and WASD to bounded directions", () => {
  assert.equal(teleopDirectionForKey("ArrowUp"), "forward");
  assert.equal(teleopDirectionForKey("KeyW"), "forward");
  assert.equal(teleopDirectionForKey("ArrowLeft"), "left");
  assert.equal(teleopDirectionForKey("KeyD"), "right");
  assert.equal(teleopDirectionForKey("Space"), "stop");
  assert.equal(teleopDirectionForKey("KeyQ"), null);
});

test("teleop keyboard shortcuts ignore editable controls", () => {
  assert.equal(isEditableKeyboardTarget({ tagName: "INPUT" }), true);
  assert.equal(isEditableKeyboardTarget({ tagName: "textarea" }), true);
  assert.equal(isEditableKeyboardTarget({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(isEditableKeyboardTarget({ tagName: "BUTTON" }), false);
});

test("teleop stays available during both 2D and RGB-D mapping", () => {
  assert.equal(isSimulationTeleopMode("mapping"), true);
  assert.equal(isSimulationTeleopMode("rgbd_mapping"), true);
  assert.equal(isSimulationTeleopMode("patrol"), true);
  assert.equal(isSimulationTeleopMode("idle"), false);
});
