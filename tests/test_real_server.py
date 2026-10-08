"""real/server.py 테스트. 가짜 버스로 하드웨어 없이 실행.

  ~/mujoco_env/bin/python -m pytest tests/test_real_server.py
"""
import dataclasses
import importlib.util
import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "real"))
import config  # noqa: E402
from dxl import REG, VEL_UNIT, DxlError  # noqa: E402

# src/server.py와 모듈 이름이 같아서 다른 이름으로 불러옴
_spec = importlib.util.spec_from_file_location("real_server", ROOT / "real" / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

CFG = config.load()


class FakeBus:
    """레지스터만 흉내 냄. 위치 모드에서 토크가 켜지면 현재 위치가 곧바로 목표를 따라감."""

    def __init__(self, ids):
        self.regs = {i: {"torque_enable": 1, "operating_mode": 16, "min_position_limit": 0,
                         "max_position_limit": 4095, "position_p_gain": 640, "position_d_gain": 0,
                         "goal_pwm": 885, "velocity_limit": 265, "present_position": 2048, "goal_position": 2048,
                         "goal_velocity": 0, "present_velocity": 0, "present_load": 0, "hardware_error_status": 0}
                     for i in ids}
        self.writes = []
        self.fail = False

    def read(self, i, name):
        if self.fail:
            raise DxlError(f"ID {i} {name} 읽기 실패")
        return self.regs[i][name]

    def write(self, i, name, value):
        if self.fail:
            raise DxlError(f"ID {i} {name} 쓰기 실패")
        r = self.regs[i]
        if name in ("operating_mode", "min_position_limit", "max_position_limit") and r["torque_enable"]:
            raise DxlError(f"ID {i} {name}: 토크가 켜져 있어 EEPROM 쓰기 불가")
        r[name] = value
        self.writes.append((i, name, value))
        if r["torque_enable"] and r["operating_mode"] == 3:
            r["present_position"] = r["goal_position"]

    def sync_read(self, ids, first, last):
        start, end = REG[first].addr, REG[last].addr + REG[last].size
        names = [n for n, r in REG.items() if start <= r.addr and r.addr + r.size <= end]
        return {i: {n: self.read(i, n) for n in names} for i in ids}


@pytest.fixture
def bus():
    return FakeBus([j.id for j in CFG.joints.values()])


@pytest.fixture
def client(bus, tmp_path):
    hand = server.Hand(bus, CFG)
    return TestClient(server.create_app(hand, tmp_path / "presets.json"))


def ID(n):
    return CFG.joints[n].id


def test_startup_turns_torque_off_and_sets_position_mode(bus, client):
    s = client.get("/state").json()
    assert not any(s["torque"].values())
    assert set(s["modes"].values()) == {"position"}
    for n, j in CFG.joints.items():
        r = bus.regs[j.id]
        assert r["torque_enable"] == 0 and r["operating_mode"] == 3
        assert (r["min_position_limit"], r["max_position_limit"]) == tuple(
            sorted(round(2048 + q * 4096 / (2 * math.pi)) for q in j.range))


def test_startup_skips_eeprom_writes_when_already_set(bus):
    server.Hand(bus, CFG)
    bus.writes.clear()
    server.Hand(bus, CFG)
    assert {name for _, name, _ in bus.writes} == {"torque_enable"}


def test_target_rejected_while_torque_off(client):
    r = client.post("/joints", json={"A_j1": 0.3})
    assert r.status_code == 409


def test_torque_on_holds_current_position(bus, client):
    bus.regs[ID("B_j1")]["present_position"] = 2300
    s = client.post("/joints/B_j1/torque", json={"enabled": True}).json()
    assert s["torque"]["B_j1"] and bus.regs[ID("B_j1")]["goal_position"] == 2300
    assert s["targets"]["B_j1"] == pytest.approx(252 * 2 * math.pi / 4096)


def test_torque_on_outside_range_rejected_without_change(bus, client):
    bus.regs[ID("B_j1")]["present_position"] = 779   # -1.95 rad, 범위 ±1.57 밖
    r = client.post("/joints/B_j1/torque", json={"enabled": True})
    assert r.status_code == 409 and "B_j1" in r.json()["detail"]
    assert bus.regs[ID("B_j1")]["torque_enable"] == 0


def test_bulk_torque_skips_joints_outside_range(bus, client):
    bus.regs[ID("B_j1")]["present_position"] = 779
    s = client.post("/torque", json={"enabled": True}).json()
    assert list(s["skipped"]) == ["B_j1"] and s["skipped"]["B_j1"] == pytest.approx((779 - 2048) * 2 * math.pi / 4096)
    assert s["torque"] == {n: n != "B_j1" for n in CFG.joints}
    assert bus.regs[ID("B_j1")]["torque_enable"] == 0
    s = client.post("/torque", json={"enabled": False}).json()
    assert s["skipped"] == {} and not any(s["torque"].values())


def test_position_target_uses_zero_and_sign(bus, tmp_path):
    joints = dict(CFG.joints)
    joints["A_j1"] = dataclasses.replace(joints["A_j1"], sign=-1, zero=1900)
    hand = server.Hand(bus, dataclasses.replace(CFG, joints=joints))
    c = TestClient(server.create_app(hand, tmp_path / "p.json"))
    c.post("/torque", json={"enabled": True})
    r = c.post("/joints", json={"A_j1": 0.5, "A_j2": 9.0}).json()
    assert r["clipped"] == ["A_j2"]
    assert bus.regs[ID("A_j1")]["goal_position"] == round(1900 - 0.5 * 4096 / (2 * math.pi))
    hand.poll()
    assert hand.state()["joints"]["A_j1"] == pytest.approx(0.5, abs=2e-3)


def test_mode_change_requires_torque_off(bus, client):
    client.post("/joints/C_j2/torque", json={"enabled": True})
    assert client.post("/joints/C_j2/mode", json={"mode": "velocity"}).status_code == 409
    client.post("/joints/C_j2/torque", json={"enabled": False})
    s = client.post("/joints/C_j2/mode", json={"mode": "velocity"}).json()
    assert s["modes"]["C_j2"] == "velocity" and bus.regs[ID("C_j2")]["operating_mode"] == 1


def test_velocity_target_in_register_units(bus, client):
    client.post("/joints/C_j2/mode", json={"mode": "velocity"})
    client.post("/joints/C_j2/torque", json={"enabled": True})
    assert client.post("/joints", json={"C_j2": 0.1}).status_code == 409
    r = client.post("/velocities", json={"C_j2": 1.0}).json()
    assert bus.regs[ID("C_j2")]["goal_velocity"] == round(1.0 / VEL_UNIT)
    assert r["applied"]["C_j2"] == 1.0
    lim = client.get("/joints").json()["C_j2"]["velocity_range"][1]
    assert lim == pytest.approx(265 * VEL_UNIT)


def test_grasp_closes_fingers(bus, client):
    client.post("/torque", json={"enabled": True})
    r = client.post("/grasp", json={"amount": 1}).json()
    assert "A_j0" not in r["applied"]
    assert r["applied"]["A_j2"] < 0 < r["applied"]["B_j2"]


def test_preset_apply_writes_gains_and_pwm(bus, client):
    preset = {n: {"target": 0.0, "kp": 800, "kv": 10, "torque_limit": 0.7} for n in CFG.joints}
    assert client.put("/presets/soft", json=preset).status_code == 200
    assert client.post("/presets/soft/apply").status_code == 409   # 토크 꺼짐
    client.post("/torque", json={"enabled": True})
    s = client.post("/presets/soft/apply").json()
    r = bus.regs[ID("B_j2")]
    assert (r["position_p_gain"], r["position_d_gain"], r["goal_pwm"]) == (800, 10, 442)
    assert s["gains"]["B_j2"] == {"kp": 800, "kv": 10, "torque_limit": 0.7}


def test_poll_errors(bus):
    hand = server.Hand(bus, CFG)
    bus.regs[ID("A_j0")]["hardware_error_status"] = 0b100000
    bus.regs[ID("A_j0")]["present_load"] = -500
    hand.poll()
    s = hand.state()
    assert s["hw_errors"]["A_j0"] == ["과부하"] and s["forces"]["A_j0"] == pytest.approx(-0.7)
    bus.fail = True
    hand.poll()
    s = hand.state()
    assert s["comm_error"] and s["hw_errors"]["A_j0"] == ["과부하"]   # 이전 값 유지


def test_comm_failure_returns_502(bus, client):
    client.post("/torque", json={"enabled": True})
    bus.fail = True
    r = client.post("/joints", json={"A_j1": 0.1})
    assert r.status_code == 502 and "실패" in r.json()["detail"]


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
