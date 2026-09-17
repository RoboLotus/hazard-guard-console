import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("gate", Path(__file__).parents[1] / "scripts/rgb_encode_gate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_gate_rate_and_no_backlog():
    gate = module.EncodeGate()
    assert sum(gate.allow(i / 20, 10) for i in range(200)) == 100
    assert gate.allow(100, 10)
    assert not gate.allow(100.001, 10)
    gate.reset()
    assert gate.allow(100.001, 10)


def test_jitter_keeps_rate_not_half_rate():
    gate = module.EncodeGate()
    times = [i / 20 + (0.002 if i % 2 == 0 else 0) for i in range(200)]
    assert 99 <= sum(gate.allow(t, 10) for t in times) <= 101
