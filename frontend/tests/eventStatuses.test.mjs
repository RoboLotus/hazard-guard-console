import test from "node:test";
import assert from "node:assert/strict";
import { mergeEventStatuses, applyEventStatuses } from "../src/eventStatuses.js";

test("불완전한 상태 응답도 페이지를 깨뜨리지 않는다", () => {
  for (const payload of [null, {}, { map_id: "a" }, { map_id: "a", statuses: null }]) {
    assert.equal(mergeEventStatuses(null, payload), null);
  }
  assert.deepEqual(mergeEventStatuses(null, { map_id: "a", statuses: [null, {}] }).statuses, []);
  assert.deepEqual(applyEventStatuses([{ id: "a" }], null, undefined), [{ id: "a" }]);
});

test("늦게 도착한 조회가 완료된 저장을 되돌리지 않는다", () => {
  const current = { map_id: "a", statuses: [{ id: "1", level: "warning", status: "resolved", revision: 2 }] };
  const merged = mergeEventStatuses(current, { map_id: "a", statuses: [{ id: "1", level: "warning", status: "working", revision: 1 }] });
  assert.equal(merged.statuses[0].status, "resolved");
  const events = [{ id: "1", level: "warning", status: "new" }];
  assert.equal(applyEventStatuses(events, merged, "a")[0].status, "resolved");
  assert.equal(applyEventStatuses(events, merged, "b")[0].status, "new");
  assert.equal(applyEventStatuses([{ ...events[0], level: "critical" }], merged, "a")[0].status, "new");
});
