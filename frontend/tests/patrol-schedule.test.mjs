import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPatrolSchedulePayload,
  createDefaultPatrolSchedule,
  normalizePatrolSchedule,
} from "../src/patrolSchedule.js";

test("defaults to one immediate patrol", () => {
  const settings = createDefaultPatrolSchedule(new Date("2026-08-11T08:00:00+09:00"));

  assert.equal(settings.startMode, "now");
  assert.equal(settings.repeatMode, "once");
  assert.match(settings.endAt, /T18:00$/);
});

test("builds an absolute work-hours patrol window", () => {
  const now = new Date("2026-08-11T08:00:00+09:00");
  const payload = buildPatrolSchedulePayload({
    startMode: "scheduled",
    startAt: "2026-08-11T09:00",
    repeatMode: "until_time",
    repeatCount: 2,
    repeatIntervalMinutes: 15,
    endAt: "2026-08-11T18:00",
  }, now);

  assert.equal(payload.repeat_mode, "until_time");
  assert.equal(payload.repeat_interval_seconds, 900);
  assert.equal(new Date(payload.start_at).getTime(), new Date("2026-08-11T09:00").getTime());
  assert.equal(new Date(payload.end_at).getTime(), new Date("2026-08-11T18:00").getTime());
});

test("rejects a closing time before the scheduled start", () => {
  assert.throws(() => buildPatrolSchedulePayload({
    startMode: "scheduled",
    startAt: "2026-08-11T18:00",
    repeatMode: "until_time",
    repeatCount: 2,
    repeatIntervalMinutes: 10,
    endAt: "2026-08-11T09:00",
  }, new Date("2026-08-11T08:00:00")), /종료 시각/);
});

test("normalizes old saved routes without schedule fields", () => {
  const normalized = normalizePatrolSchedule(null, new Date("2026-08-11T08:00:00"));
  assert.equal(normalized.repeatMode, "once");
  assert.equal(normalized.repeatCount, 2);
});
