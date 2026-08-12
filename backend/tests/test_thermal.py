import numpy as np

from app.thermal import calibrated_thermal_u8


def raw_kelvin(celsius: float) -> int:
    return round((celsius + 273.15) / 0.01)


def test_mono16_uses_fixed_absolute_temperature_scale():
    raw = np.asarray(
        [[raw_kelvin(20.0), raw_kelvin(55.0), raw_kelvin(90.0)]],
        dtype=np.uint16,
    )

    result = calibrated_thermal_u8(raw, "mono16")

    assert result.tolist() == [[0, 127, 255]]


def test_uniform_ambient_frame_stays_dark_instead_of_expanding_contrast():
    raw = np.full((3, 3), raw_kelvin(25.0), dtype=np.uint16)

    result = calibrated_thermal_u8(raw, "mono16")

    assert np.all(result == 18)


def test_temperature_values_are_clipped_to_display_range():
    raw = np.asarray(
        [[raw_kelvin(-10.0), raw_kelvin(120.0)]],
        dtype=np.uint16,
    )

    result = calibrated_thermal_u8(raw, "16UC1")

    assert result.tolist() == [[0, 255]]
