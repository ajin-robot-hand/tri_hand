"""real/ 단위 변환, 설정 검증, 모터 상태 비교 테스트. 하드웨어 없이 실행.

  ~/mujoco_env/bin/python -m pytest tests/test_real.py
"""
import dataclasses
import sys
from pathlib import Path

import mujoco
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "real"))
import check  # noqa: E402
import config  # noqa: E402
from dxl import DxlError, hw_errors, rad_to_tick, tick_to_rad  # noqa: E402

CFG = config.load()


def test_config_ranges_match_sim():
    model = mujoco.MjModel.from_xml_path(str(ROOT / "src" / "scene.xml"))
    assert set(CFG.joints) == {model.actuator(i).name.removesuffix("_act") for i in range(model.nu)}
    for n, j in CFG.joints.items():
        assert j.range == pytest.approx(tuple(model.actuator(f"{n}_act").ctrlrange))


@pytest.mark.parametrize("sign", [1, -1])
def test_tick_rad_roundtrip(sign):
    assert tick_to_rad(2048, 2048, sign) == 0
    assert tick_to_rad(3072, 2048, sign) == pytest.approx(sign * 1.5708, abs=1e-4)
    for t in (0, 1000, 2048, 4095):
        assert rad_to_tick(tick_to_rad(t, 1900, sign), 1900, sign) == t


def test_validate_catches_bad_values():
    bad = dict(CFG.joints)
    bad["A_j1"] = dataclasses.replace(bad["A_j1"], id=CFG.joints["A_j0"].id, sign=0, zero=5000)
    errors = config.validate(dataclasses.replace(CFG, baudrate=12345, joints=bad))
    text = "\n".join(errors)
    for word in ("baudrate", "중복", "sign", "zero"):
        assert word in text


def test_hw_errors():
    assert hw_errors(0) == []
    assert hw_errors(0b100100) == ["과열", "과부하"]


def healthy(**overrides):
    v = {"model_number": 1060, "operating_mode": 3, "drive_mode": 0, "torque_enable": 0,
         "hardware_error_status": 0, "min_position_limit": 0, "max_position_limit": 4095,
         "present_position": 2048, "present_input_voltage": 111, "present_temperature": 30,
         "temperature_limit": 72}
    v.update(overrides)
    return v.__getitem__


J = config.JointCfg(id=1, sign=1, zero=2048, range=(-1.5708, 1.5708))


def test_inspect_healthy_motor():
    r = check.inspect_motor("A_j1", J, healthy())
    assert r.errors == [] and r.warnings == []


@pytest.mark.parametrize("overrides, kind, word", [
    ({"model_number": 1200}, "errors", "모델"),
    ({"hardware_error_status": 0b100000}, "errors", "과부하"),
    ({"operating_mode": 1}, "warnings", "velocity"),
    ({"drive_mode": 1}, "warnings", "역방향"),
    ({"min_position_limit": 1500}, "warnings", "위치 제한"),
    ({"present_position": 4000}, "warnings", "zero/sign"),
    ({"present_input_voltage": 50}, "warnings", "전압"),
    ({"present_temperature": 70}, "warnings", "온도"),
])
def test_inspect_detects(overrides, kind, word):
    r = check.inspect_motor("A_j1", J, healthy(**overrides))
    assert any(word in m for m in getattr(r, kind)), (r.errors, r.warnings)


def test_inspect_zero_outside_revolution():
    r = check.inspect_motor("A_j1", dataclasses.replace(J, zero=100), healthy(present_position=100))
    assert any("한 바퀴" in e for e in r.errors)


def test_inspect_read_failure():
    def read(name):
        raise DxlError("ID 1 model_number 읽기 실패")
    r = check.inspect_motor("A_j1", J, read)
    assert r.errors and r.values == {}
