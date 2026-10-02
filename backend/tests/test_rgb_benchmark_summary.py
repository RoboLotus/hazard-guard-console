import copy
from scripts.summarize_rgb_benchmark import stats, summarize


def fixture():
    return {
        "spec": {"label": "unit", "views": 1, "mode": "basic"},
        "elapsed_sec": 10, "pid": 42, "aborted": None, "errors": [],
        "samples": [{"cpu_total_pct": 10, "ram_mib": 2000, "processes": [
            {"pid": 42, "name": "python", "cpu_one_core_100": 30, "rss_mib": 100},
            {"pid": 43, "name": "ascamera_node", "cpu_one_core_100": 10, "rss_mib": 90}]}],
        "counts": {"rgb_received": 200, "jpeg_encode": 200, "jpeg_payload_bytes": 100000,
                   "metadata_header_bytes": 2000, "report_body_bytes": 1000},
        "timings": {}, "reports": [],
        "tegrastats": [{"at": 20, "text": "GR3D_FREQ 0% cpu@52.5C VDD_IN 5000mW/5000mW"}],
    }


def report():
    return {"client_id": "a", "server_received_monotonic": 19, "window_ms": 5000,
            "observed_ms": 5000, "missing_ms": 0, "stale_ms": 0, "unique_frames": 15,
            "request_errors": 0, "report_errors": 0, "metadata_errors": 0, "uncertainty_max_ms": 80,
            "age": {"samples": 10, "mean_ms": 200, "max_ms": 500,
                    "histogram": [0, 0, 0, 9, 1] + [0] * 10}}


def test_stats_nearest_rank_and_missing():
    assert stats([]) is None
    assert stats(range(1, 21))["p95"] == 19


def test_no_reports_is_unknown_not_zero_latency():
    d = fixture(); d["spec"]["mode"] = "off"
    r = summarize(d)
    assert r["browser"]["age_p95_bucket_ms"] is None
    assert r["browser"]["stale_or_missing_pct"] is None
    assert r["rgb_input_fps"] == 20
    assert r["observability_to_jpeg_pct"] == 3
    assert r["cpu_temp_c"]["mean"] == 52.5


def test_histograms_merge_without_averaging_window_percentiles():
    d = fixture(); d["reports"] = [report(), copy.deepcopy(report())]
    r = summarize(d)
    assert r["browser"]["age_p95_bucket_ms"] == [300, 500]
    assert r["browser"]["age_samples"] == 20
    assert r["browser"]["mean_view_fps"] == 3


def test_missing_reported_time_is_separate_from_observation_coverage():
    d = fixture(); d["reports"] = [report()]
    r = summarize(d)["browser"]
    assert r["observed_within_retained_windows_pct"] == 100
    assert r["retained_window_coverage_pct"] == 50
    d["reports"][0]["server_received_monotonic"] = 13
    assert summarize(d)["browser"]["report_windows"] == 0


def test_explicit_phase_boundary_takes_priority_over_tegrastats():
    d = fixture(); d["reports"] = [report()]
    d["begin_monotonic"] = 15
    assert summarize(d)["browser"]["report_windows"] == 0
