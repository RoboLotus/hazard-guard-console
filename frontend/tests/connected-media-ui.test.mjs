import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = async (path) => readFile(new URL(`../src/${path}`, import.meta.url), "utf8");

test("미연결 Overview는 정적 지도와 카메라 목업을 표시하지 않는다", async () => {
  const [mapPanel, overview] = await Promise.all([
    source("components/MapPanel.jsx"),
    source("pages/Overview.jsx"),
  ]);

  assert.doesNotMatch(mapPanel, /slam-map\.webp|디지털 트윈 목업/);
  assert.match(mapPanel, /지도 연결이 필요합니다/);
  assert.doesNotMatch(overview, /industrial-(rgb|thermal)\.webp|>MOCK</);
  assert.match(overview, /카메라 연결이 필요합니다/);
});

test("영상과 이벤트 화면도 예시 사진 대신 연결 상태를 사용한다", async () => {
  const [videoPage, eventsPage] = await Promise.all([
    source("pages/VideoPage.jsx"),
    source("pages/EventsPage.jsx"),
  ]);

  assert.doesNotMatch(videoPage, /industrial-(rgb|thermal)\.webp|영상 목업/);
  assert.match(videoPage, /영상 연결 필요/);
  assert.doesNotMatch(eventsPage, /industrial-(rgb|thermal)\.webp/);
  assert.match(eventsPage, /RGB 영상 연결 필요/);
  assert.match(eventsPage, /열화상 영상 연결 필요/);
});

test("지도 화면은 연결 전 목업 운용 상태를 실제 상태처럼 표시하지 않는다", async () => {
  const [mapPage, sidebar] = await Promise.all([
    source("pages/MapPage.jsx"),
    source("components/Sidebar.jsx"),
  ]);

  assert.doesNotMatch(mapPage, /UI 목업/);
  assert.match(mapPage, /운용 환경 확인 중/);
  assert.match(mapPage, /데이터 연결 필요/);
  assert.doesNotMatch(sidebar, /Prototype v0\.1\.0/);
});
