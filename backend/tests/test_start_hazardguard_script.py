from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "start_hazardguard.sh"
)


def test_runtime_environment_is_exported_to_backend_and_ros_children():
    source = SCRIPT.read_text(encoding="utf-8")

    allexport_start = source.index("set -a")
    runtime_source = source.index('source "${RUNTIME_ENV}"')
    allexport_end = source.index("set +a")

    assert allexport_start < runtime_source < allexport_end


def test_physical_runtime_overrides_remain_operator_configurable():
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'HAZARD_GUARD_PERSON_SAFETY_ENABLED="'
        '${HAZARD_GUARD_PERSON_SAFETY_ENABLED:-1}"'
    ) in source
    assert (
        'HAZARD_GUARD_THERMAL_ROI_CONFIG="'
        '${HAZARD_GUARD_THERMAL_ROI_CONFIG:-'
    ) in source
