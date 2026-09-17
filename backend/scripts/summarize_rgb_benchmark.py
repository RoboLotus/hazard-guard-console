"""Summarize immutable phase JSON files; never average per-window p95s."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics

BOUNDS = [50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000, 30000, 60000]


def stats(xs):
    xs = sorted(xs)
    return {"n": len(xs), "mean": statistics.mean(xs), "median": statistics.median(xs),
            "p95": xs[math.ceil(.95 * len(xs)) - 1], "max": xs[-1]} if xs else None


def summarize(data):
    rows = data["samples"]
    elapsed = data["elapsed_sec"]
    # Reports are received on server monotonic clock. Discard warmup-overlapping windows.
    # Server receive time includes reporting network delay; windows are approximate.
    if "begin_monotonic" in data:
        start = data["begin_monotonic"]
    elif data["tegrastats"]:
        end = data["tegrastats"][-1]["at"]
        start = end - elapsed
    else:
        start = math.inf
    windows = [r for r in data["reports"] if r["server_received_monotonic"] - r["window_ms"] / 1000 >= start + 1]
    hist = [sum(r["age"]["histogram"][i] for r in windows) for i in range(len(BOUNDS) + 1)]
    target = math.ceil(sum(hist) * .95)
    cumulative = 0
    p95_bucket = None
    if target:
        for i, count in enumerate(hist):
            cumulative += count
            if cumulative >= target:
                p95_bucket = [0 if i == 0 else BOUNDS[i - 1], BOUNDS[i] if i < len(BOUNDS) else None]
                break
    observed = sum(r["observed_ms"] for r in windows)
    duration = sum(r["window_ms"] for r in windows)
    n = sum(r["age"]["samples"] for r in windows)
    backend = [next((p for p in r["processes"] if p["pid"] == data["pid"]), None) for r in rows]
    camera_cpu = [sum(p["cpu_one_core_100"] for p in r["processes"] if "ascamera" in p["name"]) for r in rows]
    gpu, temp, power = [], [], []
    for sample in data["tegrastats"]:
        text = sample["text"]
        m = re.search(r"GR3D_FREQ\s+(\d+)%", text)
        if m: gpu.append(float(m[1]))
        m = re.search(r"cpu@([\d.]+)C", text)
        if m: temp.append(float(m[1]))
        m = re.search(r"VDD_IN\s+(\d+)mW", text)
        if m: power.append(float(m[1]) / 1000)
    return {"label": data["spec"]["label"], "started_unix": data.get("started_unix"), "views": data["spec"]["views"], "mode": data["spec"]["mode"],
            "target_fps": data["spec"].get("target_fps", 1000/300),
            "elapsed_sec": elapsed, "aborted": data["aborted"], "errors": data["errors"],
            "cpu_total_pct": stats([r["cpu_total_pct"] for r in rows]),
            "backend_cpu_one_core_100": stats([r["cpu_one_core_100"] for r in backend if r]),
            "camera_cpu_one_core_100": stats(camera_cpu),
            "backend_rss_mib": stats([r["rss_mib"] for r in backend if r]),
            "ram_mib": stats([r["ram_mib"] for r in rows]), "gpu_pct": stats(gpu), "cpu_temp_c": stats(temp),
            "board_watts": stats(power), "rgb_input_fps": data["counts"].get("rgb_received", 0) / elapsed,
            "jpeg_encode_fps": data["counts"].get("jpeg_encode", 0) / elapsed,
            "http_response_fps_total": data["counts"].get("http_200", 0) / elapsed,
            "jpeg_payload_kib_sec": data["counts"].get("jpeg_payload_bytes", 0) / elapsed / 1024,
            "observability_bytes_sec": (data["counts"].get("metadata_header_bytes", 0) + data["counts"].get("report_body_bytes", 0)) / elapsed,
            "observability_to_jpeg_pct": 100 * (data["counts"].get("metadata_header_bytes", 0) + data["counts"].get("report_body_bytes", 0)) / data["counts"]["jpeg_payload_bytes"] if data["counts"].get("jpeg_payload_bytes") else None,
            "http_503": data["counts"].get("http_503", 0), "timings": data["timings"],
            "browser": {"report_windows": len(windows), "sampled_clients": len({r['client_id'] for r in windows}),
                        "retained_window_seconds": duration / 1000,
                        "nominal_view_seconds": elapsed * data["spec"]["views"],
                        "retained_window_coverage_pct": 100 * duration / 1000 / (elapsed * data["spec"]["views"]) if data["spec"]["views"] else None,
                        "age_samples": n, "age_mean_ms": sum(r["age"]["mean_ms"] * r["age"]["samples"] for r in windows if r["age"]["samples"]) / n if n else None,
                        "age_p95_bucket_ms": p95_bucket, "age_max_ms": max((r["age"]["max_ms"] for r in windows if r["age"]["samples"]), default=None),
                        "observed_within_retained_windows_pct": 100 * observed / duration if duration else None,
                        "stale_or_missing_pct": 100 * sum(r["missing_ms"] + r["stale_ms"] for r in windows) / observed if observed else None,
                        "mean_view_fps": sum(r["unique_frames"] for r in windows) / (duration / 1000) if duration else None,
                        "request_errors": sum(r["request_errors"] for r in windows),
                        "report_errors": sum(r["report_errors"] for r in windows), "metadata_errors": sum(r["metadata_errors"] for r in windows),
                        "uncertainty_max_ms": max((r["uncertainty_max_ms"] for r in windows), default=None)}}


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("directory"); args = p.parse_args()
    root = Path(args.directory)
    items = []
    for file in sorted(root.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "spec" in data and "samples" in data:
            items.append(summarize(data))
    items.sort(key=lambda d: d["started_unix"] or 0)
    (root / "summary.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    flat = []
    for row in items:
        flat.append({"label": row["label"], "views": row["views"], "mode": row["mode"], "target_fps": row["target_fps"],
                     "cpu_total_mean_pct": row["cpu_total_pct"]["mean"],
                     "backend_cpu_mean_one_core_100": row["backend_cpu_one_core_100"]["mean"],
                     "backend_cpu_p95_one_core_100": row["backend_cpu_one_core_100"]["p95"],
                     "rgb_input_fps": row["rgb_input_fps"], "jpeg_encode_fps": row["jpeg_encode_fps"],
                     "http_response_fps_total": row["http_response_fps_total"],
                     "jpeg_payload_kib_sec": row["jpeg_payload_kib_sec"],
                     "observability_bytes_sec": row["observability_bytes_sec"],
                     "observability_to_jpeg_pct": row["observability_to_jpeg_pct"],
                     "browser_mean_view_fps": row["browser"]["mean_view_fps"],
                     "age_p95_bucket_ms": str(row["browser"]["age_p95_bucket_ms"]),
                     "age_max_ms": row["browser"]["age_max_ms"],
                     "retained_window_coverage_pct": row["browser"]["retained_window_coverage_pct"],
                     "stale_or_missing_pct": row["browser"]["stale_or_missing_pct"],
                     "aborted": row["aborted"]})
    if flat:
        with (root / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(flat[0])); writer.writeheader(); writer.writerows(flat)
    for row in items:
        print(row["label"], "views", row["views"], row["mode"], "CPU", round(row["backend_cpu_one_core_100"]["mean"], 2),
              "input", round(row["rgb_input_fps"], 2), "browser", row["browser"])
