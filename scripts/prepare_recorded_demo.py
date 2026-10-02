"""Convert a saved map session into static, read-only browser assets.

No ROS, robot connection, pickle loading or modifications to source files.
Dependencies: numpy, opencv-python-headless, PyYAML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import cv2
import numpy as np
import yaml


def read_cloud(path: Path):
    scalars = {"float": "<f4", "double": "<f8", "uchar": "u1", "uint": "<u4", "int": "<i4"}
    properties, count = [], None
    with path.open("rb") as source:
        if source.readline().strip() != b"ply":
            raise ValueError("Not a PLY file")
        if source.readline().strip() != b"format binary_little_endian 1.0":
            raise ValueError("Expected binary little-endian PLY")
        in_vertex = False
        for _ in range(100):
            line = source.readline().decode("ascii").strip()
            parts = line.split()
            if parts[:2] == ["element", "vertex"]:
                count = int(parts[2]); in_vertex = True
            elif parts[:1] == ["element"]:
                in_vertex = False
            elif in_vertex and parts[:1] == ["property"]:
                if len(parts) != 3 or parts[1] not in scalars:
                    raise ValueError("Unsupported PLY property")
                properties.append((parts[2], scalars[parts[1]]))
            if line == "end_header":
                break
        else:
            raise ValueError("Missing PLY header terminator")
        if count is None or not 0 < count <= 5_000_000:
            raise ValueError("Invalid PLY vertex count")
        dtype = np.dtype(properties)
        rows = np.frombuffer(source.read(count * dtype.itemsize), dtype=dtype)
        if len(rows) != count:
            raise ValueError("Truncated PLY")
    xyz = np.column_stack([rows[key] for key in ("x", "y", "z")]).astype(np.float64)
    rgb = np.column_stack([rows[key] for key in ("red", "green", "blue")])
    return xyz, rgb


def canonical_cloud(xyz, rgb, voxel):
    if not np.isfinite(voxel) or voxel <= 0:
        raise ValueError("Invalid voxel size")
    valid = np.isfinite(xyz).all(axis=1)
    xyz, rgb = xyz[valid], rgb[valid]
    if not len(xyz):
        raise ValueError("Empty geometry")
    _, inverse, counts = np.unique(np.floor(xyz / voxel).astype(np.int64), axis=0,
                                   return_inverse=True, return_counts=True)
    sums = np.zeros((len(counts), 3), np.float64)
    np.add.at(sums, inverse, xyz)
    points = (sums / counts[:, None]).astype("<f4")
    sums.fill(0)
    np.add.at(sums, inverse, rgb)
    colors = np.clip(np.rint(sums / counts[:, None]), 0, 255).astype("u1")
    digest = hashlib.sha256(b"hazard-guard-frozen-geometry-v1\0")
    digest.update(struct.pack("<dQ", voxel, len(counts)))
    digest.update(points.tobytes())
    return points, colors, digest.hexdigest()


def prepare(source: Path, output: Path):
    source, output = source.resolve(), output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Output must be separate from the source session")
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("cloud_frame_id") != "map":
        raise ValueError("Demo requires map-frame geometry")
    xyz, rgb = read_cloud(source / "cloud.ply")
    with np.load(source / "thermal_layer.npz", allow_pickle=False) as layer:
        if int(layer["schema_version"]) != 1:
            raise ValueError("Unsupported thermal schema")
        voxel = float(layer["geometry_voxel_size_m"])
        points, colors, fingerprint = canonical_cloud(xyz, rgb, voxel)
        if fingerprint != str(layer["geometry_fingerprint"]) or fingerprint != metadata["thermal_layer_fingerprint"]:
            raise ValueError("Map/thermal fingerprint mismatch; refusing to misplace temperatures")
        if int(layer["geometry_voxel_count"]) != len(points):
            raise ValueError("Thermal geometry count mismatch")
        raw_indices = layer["observed_indices"]
        if not np.issubdtype(raw_indices.dtype, np.integer):
            raise ValueError("Thermal indices must be integers")
        indices = raw_indices.astype(np.int64)
        temperatures = layer["temperature_c"]
        if indices.ndim != 1 or temperatures.shape != indices.shape or not len(indices):
            raise ValueError("Missing or malformed thermal observations")
        if (indices < 0).any() or (indices >= len(points)).any() or len(np.unique(indices)) != len(indices) or not np.isfinite(temperatures).all():
            raise ValueError("Invalid thermal observations")
        thermal = {"indices": indices.tolist(), "temperatures": temperatures.tolist()}
    grid = yaml.safe_load((source / "map.yaml").read_text(encoding="utf-8"))
    # The demo only accepts the map.pgm sitting beside this metadata.
    if grid["image"] != "map.pgm" or not np.isfinite(grid["resolution"]) or grid["resolution"] <= 0 or len(grid["origin"]) != 3 or not np.isfinite(grid["origin"]).all():
        raise ValueError("Unsupported occupancy map configuration")
    occupancy = cv2.imread(str(source / "map.pgm"), cv2.IMREAD_GRAYSCALE)
    if occupancy is None:
        raise ValueError("Unreadable occupancy map")
    equipment_path = source / "equipment.json"
    equipment = json.loads(equipment_path.read_text(encoding="utf-8")) if equipment_path.exists() else {}
    if equipment and (equipment.get("map_session_id") != metadata["id"] or equipment.get("frame_id") != "map"):
        raise ValueError("Equipment belongs to a different map")
    manifest = {
        "schema": 1, "recorded": True, "session": metadata["id"], "world": metadata["world_id"],
        "recordedAt": metadata.get("cloud_exported_at") or metadata.get("created_at"),
        "thermalRecordedAt": metadata.get("thermal_layer_persisted_at"),
        "frame": metadata["cloud_frame_id"], "voxel": voxel, "fingerprint": fingerprint,
        "pointCount": len(points), "observedCount": len(indices),
        "temperatureMin": float(temperatures.min()), "temperatureMax": float(temperatures.max()),
        "bounds": {"min": points.min(0).tolist(), "max": points.max(0).tolist()},
        "savedPose": metadata.get("localization_pose"), "equipment": equipment.get("equipment", []),
        "map": {"width": int(occupancy.shape[1]), "height": int(occupancy.shape[0]),
                "resolution": grid["resolution"], "origin": grid["origin"]},
        "sourceHashes": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                         for name in ["cloud.ply", "thermal_layer.npz", "metadata.json", "map.yaml", "map.pgm"]},
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "points.bin").write_bytes(points.tobytes())
    (output / "colors.bin").write_bytes(colors.tobytes())
    (output / "thermal.json").write_text(json.dumps(thermal, allow_nan=False), encoding="utf-8")
    if not cv2.imwrite(str(output / "map.png"), occupancy):
        raise ValueError("Could not encode map preview")
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Saved session directory")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "frontend/public/demo-data")
    args = parser.parse_args()
    result = prepare(args.source, args.output)
    print(f"Prepared {result['pointCount']:,} points / {result['observedCount']:,} temperatures -> {args.output}")
