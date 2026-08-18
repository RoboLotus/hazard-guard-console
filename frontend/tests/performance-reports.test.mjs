import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  formatDuration,
  formatMetric,
  reportStatusLabel,
  sortReports,
} from "../src/performanceReports.js";


test("formats missing metrics without pretending that a sample exists", () => {
  assert.equal(formatMetric(undefined), "—");
  assert.equal(formatMetric({ mean: null }), "—");
  assert.equal(formatMetric({ p95: 82.456 }, "p95"), "82.5");
});


test("formats mission duration as a stable clock", () => {
  assert.equal(formatDuration(0), "00:00:00");
  assert.equal(formatDuration(3661), "01:01:01");
});


test("sorts newest reports first without mutating the input", () => {
  const reports = [
    { id: "old", started_at: "2026-08-17T00:00:00Z" },
    { id: "new", started_at: "2026-08-18T00:00:00Z" },
  ];

  assert.deepEqual(sortReports(reports).map((item) => item.id), ["new", "old"]);
  assert.equal(reports[0].id, "old");
});


test("localizes terminal mission status", () => {
  assert.equal(reportStatusLabel("completed"), "완료");
  assert.equal(reportStatusLabel("failed"), "실패");
  assert.equal(reportStatusLabel("interrupted"), "중단");
});


test("report management uses in-app dialogs instead of browser prompts", async () => {
  const source = await readFile(
    new URL("../src/pages/ReportsPage.jsx", import.meta.url),
    "utf8",
  );

  assert.equal(source.includes("window.prompt"), false);
  assert.equal(source.includes("window.confirm"), false);
  assert.match(source, /performance-dialog/);
  assert.match(source, /setDetail\(null\);\s+setDetailLoading\(true\)/);
});
