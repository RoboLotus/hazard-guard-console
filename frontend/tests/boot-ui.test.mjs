import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("앱 번들이 준비되기 전 접근 가능한 로딩 상태를 표시한다", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(html, /<html lang="ko">/);
  assert.match(html, /class="app-boot-loader" role="status" aria-live="polite"/);
  assert.match(html, /관제 화면을 준비하고 있습니다\./);
  assert.doesNotMatch(html, /setTimeout|animation-delay/);
});
