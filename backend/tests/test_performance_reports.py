from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.performance_reports import PerformanceReportStore


client = TestClient(app)


def write_report(root: Path, report_id: str = "report-1") -> Path:
    directory = root / "2026-08-18" / report_id
    directory.mkdir(parents=True)
    summary = {
        "schema_version": 1,
        "id": report_id,
        "name": "1차 순찰",
        "mission_id": "mission-1",
        "status": "completed",
        "started_at": "2026-08-18T00:00:00+00:00",
        "finished_at": "2026-08-18T00:01:00+00:00",
        "duration_sec": 60,
        "sample_count": 60,
        "system": {
            "cpu_percent": {"mean": 50, "median": 49, "p95": 80, "max": 90},
            "gpu_percent": {"mean": 40, "median": 38, "p95": 70, "max": 80},
            "ram_percent": {"mean": 60, "median": 60, "p95": 65, "max": 66},
        },
        "cores": {},
        "processes": [],
        "phases": {},
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "metadata.json").write_text(
        json.dumps({"id": report_id, "name": "1차 순찰"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / "report.md").write_text("# 1차 순찰\n", encoding="utf-8")
    (directory / "process-summary.csv").write_text("name,mean\n", encoding="utf-8")
    return directory


def test_store_lists_reads_and_renames_report(tmp_path: Path):
    directory = write_report(tmp_path)
    store = PerformanceReportStore(tmp_path)

    listing = store.list()
    assert listing["reports"][0]["cpu"]["p95"] == 80

    renamed = store.rename("report-1", "야간 순찰")
    assert renamed["name"] == "야간 순찰"
    assert (directory / "report.md").read_text(encoding="utf-8").startswith(
        "# 야간 순찰"
    )


def test_store_exposes_active_session_and_stale_state(tmp_path: Path):
    directory = tmp_path / "2026-08-18" / "active-1"
    directory.mkdir(parents=True)
    (directory / "active.json").write_text(
        json.dumps(
            {
                "id": "active-1",
                "name": "진행 중",
                "updated_at": "2020-01-01T00:00:00+00:00",
                "sample_count": 3,
                "latest": {},
            }
        ),
        encoding="utf-8",
    )

    active = PerformanceReportStore(tmp_path).list()["active"][0]
    assert active["stale"] is True

    deleted = PerformanceReportStore(tmp_path).delete("active-1")
    assert deleted["deleted"] is True
    assert not directory.exists()


def test_delete_removes_only_the_resolved_report_directory(tmp_path: Path):
    directory = write_report(tmp_path)
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    store = PerformanceReportStore(tmp_path)

    result = store.delete("report-1")

    assert result["deleted"] is True
    assert not directory.exists()
    assert sibling.exists()


def test_performance_report_api_manages_files(monkeypatch, tmp_path: Path):
    directory = write_report(tmp_path)
    monkeypatch.setattr(
        main_module,
        "performance_report_store",
        PerformanceReportStore(tmp_path),
    )

    listing = client.get("/api/v1/performance/reports")
    assert listing.status_code == 200
    assert listing.json()["reports"][0]["id"] == "report-1"

    renamed = client.patch(
        "/api/v1/performance/reports/report-1",
        json={"name": "주간 순찰"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "주간 순찰"

    refused = client.delete("/api/v1/performance/reports/report-1")
    assert refused.status_code == 409
    assert directory.exists()

    downloaded = client.get(
        "/api/v1/performance/reports/report-1/download?format=csv"
    )
    assert downloaded.status_code == 200

    deleted = client.delete(
        "/api/v1/performance/reports/report-1?confirm=true"
    )
    assert deleted.status_code == 200
    assert not directory.exists()
