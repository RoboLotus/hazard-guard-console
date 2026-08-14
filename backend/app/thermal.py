from __future__ import annotations

from typing import Any


GAZEBO_MONO16_RESOLUTION_K = 0.01
DISPLAY_MIN_C = 20.0
DISPLAY_MAX_C = 90.0


def calibrated_thermal_u8(
    raw: Any,
    encoding: str,
    *,
    minimum_c: float = DISPLAY_MIN_C,
    maximum_c: float = DISPLAY_MAX_C,
) -> Any:
    """Convert a thermal frame to a fixed absolute-temperature 8-bit scale.

    Gazebo Fortress publishes its default 16-bit thermal camera as Kelvin /
    0.01 K.  Unknown encodings retain a min/max fallback so real-camera
    integration can be added without breaking the simulated stream.
    """
    import cv2
    import numpy as np

    values = raw.astype(np.float32)
    normalized_encoding = (encoding or "").lower()
    if normalized_encoding in {"mono16", "16uc1"}:
        temperature_c = values * GAZEBO_MONO16_RESOLUTION_K - 273.15
        span = maximum_c - minimum_c
        if span <= 0:
            raise ValueError("maximum_c must be greater than minimum_c")
        return np.clip(
            (temperature_c - minimum_c) * (255.0 / span),
            0.0,
            255.0,
        ).astype(np.uint8)

    return cv2.normalize(
        values,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    ).astype(np.uint8)
