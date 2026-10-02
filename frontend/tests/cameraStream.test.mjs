import test from "node:test";
import assert from "node:assert/strict";
import { cameraStreamState } from "../src/cameraStream.js";

test("실물과 시뮬레이션을 구분하고 RGB 대체 열화상은 차단한다", () => {
  assert.equal(cameraStreamState({ available: true, source: "ros:/thermal_camera/image_color" }).available, true);
  assert.equal(cameraStreamState({ available: true, source: "gazebo:/custom/thermal" }).simulated, true);
  for (const source of ["derived:rgb-colormap", "mock:thermal", "", undefined]) {
    assert.equal(cameraStreamState({ available: true, source }).available, false);
  }
  assert.equal(cameraStreamState({ available: true, stale: true, source: "ros:/rgb" }).available, false);
});
