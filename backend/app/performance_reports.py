from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any


ALLOWED_DOWNLOADS = {
    "csv": ("process-summary.csv", "text/csv"),
    "markdown": ("report.md", "text/markdown"),
    "json": ("summary.json", "application/json"),
}


def default_performance_root() -> Path:
    configured = os.getenv("HAZARD_GUARD_PERFORMANCE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local/share/hazard-guard/performance").resolve()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class PerformanceReportStore:
    """Read and safely manage reports produced by the Robot monitor."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_performance_root()).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _report_directories(self) -> list[Path]:
        return sorted(
            {path.parent.resolve() for path in self.root.rglob("summary.json")},
            reverse=True,
        )

    def _find(self, report_id: str) -> tuple[Path, dict[str, Any]]:
        for directory in self._report_directories():
            summary = _read_json(directory / "summary.json")
            if summary and summary.get("id") == report_id:
                return directory, summary
        raise KeyError(report_id)

    @staticmethod
    def _metric(summary: dict[str, Any], name: str) -> dict[str, Any]:
        metric = (summary.get("system") or {}).get(name)
        return metric if isinstance(metric, dict) else {}

    def _list_item(self, summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": summary.get("id"),
            "name": summary.get("name"),
            "mission_id": summary.get("mission_id"),
            "status": summary.get("status"),
            "started_at": summary.get("started_at"),
            "finished_at": summary.get("finished_at"),
            "duration_sec": summary.get("duration_sec", 0),
            "sample_count": summary.get("sample_count", 0),
            "cpu": self._metric(summary, "cpu_percent"),
            "gpu": self._metric(summary, "gpu_percent"),
            "ram": self._metric(summary, "ram_percent"),
        }

    def list(self) -> dict[str, Any]:
        with self._lock:
            reports = []
            for directory in self._report_directories():
                summary = _read_json(directory / "summary.json")
                if summary and summary.get("id"):
                    reports.append(self._list_item(summary))
            reports.sort(
                key=lambda item: str(item.get("started_at") or ""),
                reverse=True,
            )
            active = []
            now = datetime.now(timezone.utc)
            for path in self.root.rglob("active.json"):
                item = _read_json(path)
                if not item:
                    continue
                try:
                    updated = datetime.fromisoformat(str(item["updated_at"]))
                    age_sec = max(
                        0.0,
                        (now - updated.astimezone(timezone.utc)).total_seconds(),
                    )
                except (KeyError, TypeError, ValueError):
                    age_sec = None
                active.append(
                    {
                        **item,
                        "age_sec": age_sec,
                        "stale": age_sec is None or age_sec > 10.0,
                    }
                )
            return {"reports": reports, "active": active}

    def get(self, report_id: str) -> dict[str, Any]:
        with self._lock:
            directory, summary = self._find(report_id)
            return {
                **summary,
                "downloads": [
                    name
                    for name, (filename, _media_type) in ALLOWED_DOWNLOADS.items()
                    if (directory / filename).is_file()
                ],
            }

    def rename(self, report_id: str, name: str) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("report name must not be empty")
        with self._lock:
            directory, summary = self._find(report_id)
            summary["name"] = clean_name
            _atomic_json(directory / "summary.json", summary)
            metadata_path = directory / "metadata.json"
            metadata = _read_json(metadata_path)
            if metadata is not None:
                metadata["name"] = clean_name
                _atomic_json(metadata_path, metadata)
            markdown = directory / "report.md"
            if markdown.is_file():
                lines = markdown.read_text(encoding="utf-8").splitlines()
                if lines:
                    lines[0] = f"# {clean_name}"
                    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return self.get(report_id)

    def delete(self, report_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                directory, summary = self._find(report_id)
            except KeyError:
                directory = None
                summary = None
                for path in self.root.rglob("active.json"):
                    active = _read_json(path)
                    if active and active.get("id") == report_id:
                        directory = path.parent.resolve()
                        summary = active
                        break
                if directory is None or summary is None:
                    raise
            resolved = directory.resolve()
            if self.root not in resolved.parents:
                raise ValueError("report directory escaped the configured root")
            shutil.rmtree(resolved)
            return {"deleted": True, "id": report_id, "name": summary.get("name")}

    def download(self, report_id: str, format_name: str) -> tuple[Path, str]:
        try:
            filename, media_type = ALLOWED_DOWNLOADS[format_name]
        except KeyError as error:
            raise ValueError("unsupported report format") from error
        with self._lock:
            directory, _summary = self._find(report_id)
            path = directory / filename
            if not path.is_file():
                raise FileNotFoundError(filename)
            return path, media_type
