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

# 실물 보정값(zero, sign)이 바뀌어도 테스트가 흔들리지 않게 고정
_cfg = config.load()
CFG = dataclasses.replace(_cfg, joints={n: dataclasses.replace(j, zero=2048, sign=1) for n, j in _cfg.joints.items()})


class FakeBus:
    """레지스터만 흉내 냄. 위치 모드에서 토크가 켜지면 현재 위치가 곧바로 목표를 따라감."""

    def __init__(self, ids):
        self.regs = {i: {"torque_enable": 1, "operating_mode": 16, "min_position_limit": 0,
                         "max_position_limit": 4095, "position_p_gain": 640, "position_d_gain": 0,
                         "goal_pwm": 885, "velocity_limit": 265, "present_position": 2048, "goal_position": 2048,
                         "goal_velocity": 0, "profile_velocity": 0, "present_velocity": 0, "present_load": 0,
                         "hardware_error_status": 0, "present_input_voltage": 111, "present_temperature": 25}
                     for i in ids}
        self.writes = []
        self.sync_writes = []   # (name, {id: value}) — GroupSyncWrite 1건
        self.tx_count = 0
        self.rx_error_count = 0
        self.fail = False

    def read(self, i, name):
        self.tx_count += 1
        if self.fail:
            self.rx_error_count += 1
            raise DxlError(f"ID {i} {name} 읽기 실패")
        return self.regs[i][name]

    def write(self, i, name, value):
        self.tx_count += 1
        if self.fail:
            self.rx_error_count += 1
            raise DxlError(f"ID {i} {name} 쓰기 실패")
        r = self.regs[i]
        if name in ("operating_mode", "min_position_limit", "max_position_limit") and r["torque_enable"]:
            raise DxlError(f"ID {i} {name}: 토크가 켜져 있어 EEPROM 쓰기 불가")
        if name == "torque_enable" and value and not r["torque_enable"]:
            r["goal_position"] = r["present_position"]   # 실물처럼 토크를 켜면 목표가 현재 위치로 바뀜
        r[name] = value
        self.writes.append((i, name, value))
        if r["torque_enable"] and r["operating_mode"] == 3:
            r["present_position"] = r["goal_position"]

    def reboot(self, i):
        """실물 Reboot 흉내: 하드웨어 오류 래치를 지우고 토크를 끔(부팅 상태)."""
        self.tx_count += 1
        if self.fail:
            self.rx_error_count += 1
            raise DxlError(f"ID {i} reboot 실패")
        self.regs[i]["hardware_error_status"] = 0
        self.regs[i]["torque_enable"] = 0
        self.reboots = getattr(self, "reboots", [])
        self.reboots.append(i)

    def sync_read(self, ids, first, last):
        self.tx_count += 1
        if self.fail:
            self.rx_error_count += 1
            raise DxlError(f"일괄 읽기 실패 ({first}~{last})")
        start, end = REG[first].addr, REG[last].addr + REG[last].size
        names = [n for n, r in REG.items() if start <= r.addr and r.addr + r.size <= end]
        return {i: {n: self.regs[i][n] for n in names} for i in ids}

    def sync_write(self, name, values):
        """GroupSyncWrite 흉내: 응답 없는 패킷 1건으로 여러 id에 같은 레지스터를 씀."""
        self.tx_count += 1
        if self.fail:
            self.rx_error_count += 1
            raise DxlError(f"{name} 일괄 쓰기 실패")
        self.sync_writes.append((name, dict(values)))
        for i, v in values.items():
            r = self.regs[i]
            r[name] = v
            if name == "goal_position" and r["torque_enable"] and r["operating_mode"] == 3:
                r["present_position"] = v   # 실물처럼 위치 모드 + 토크 켜짐이면 즉시 추종


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
    """poll()은 20 ms 핫루프(부하/속도/위치)만, poll_slow()는 1 Hz(온도/전압/하드웨어 오류)만 갱신."""
    hand = server.Hand(bus, CFG)
    bus.regs[ID("A_j0")]["present_load"] = -500
    hand.poll()
    assert hand.state()["forces"]["A_j0"] == pytest.approx(-0.7)

    bus.regs[ID("A_j0")]["hardware_error_status"] = 0b100000
    bus.regs[ID("A_j0")]["present_temperature"] = 58
    bus.regs[ID("A_j0")]["present_input_voltage"] = 115
    hand.poll_slow()
    s = hand.state()
    assert s["hw_errors"]["A_j0"] == ["과부하"]
    assert s["temperatures"]["A_j0"] == 58 and s["voltages"]["A_j0"] == pytest.approx(11.5)

    bus.fail = True
    hand.poll()
    hand.poll_slow()
    s = hand.state()
    assert s["comm_error"] and s["hw_errors"]["A_j0"] == ["과부하"]   # 이전 값 유지


def test_targets_sent_as_single_sync_write(bus, client):
    """GroupSyncWrite로 7관절을 1패킷에 보냄 — 관절별 개별 goal_position 쓰기(TxRx 왕복)는 없어야 함."""
    client.post("/torque", json={"enabled": True})
    bus.writes.clear()
    bus.sync_writes.clear()
    r = client.post("/joints", json={n: 0.1 for n in CFG.joints}).json()
    assert len(bus.sync_writes) == 1
    name, values = bus.sync_writes[0]
    assert name == "goal_position" and set(values) == {j.id for j in CFG.joints.values()}
    assert not any(w[1] == "goal_position" for w in bus.writes)   # 개별 왕복 경로를 안 탐
    assert all(v == pytest.approx(0.1, abs=2e-3) for v in r["applied"].values())


def test_packet_stats_exposed_in_state(bus, client):
    client.post("/torque", json={"enabled": True})
    before = client.get("/state").json()["packets"]
    client.post("/joints", json={"A_j1": 0.1})
    after = client.get("/state").json()["packets"]
    assert after["tx"] > before["tx"] and after["rx_errors"] == 0

    bus.fail = True
    r = client.post("/joints", json={"A_j1": 0.2})
    assert r.status_code == 502
    bus.fail = False
    assert client.get("/state").json()["packets"]["rx_errors"] >= 1


def test_comm_failure_returns_502(bus, client):
    client.post("/torque", json={"enabled": True})
    bus.fail = True
    r = client.post("/joints", json={"A_j1": 0.1})
    assert r.status_code == 502 and "실패" in r.json()["detail"]


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_home_moves_all_joints_to_zero_with_torque_on(bus):
    bus.regs[ID("C_j1")]["present_position"] = 3335   # +1.97 rad, 범위 밖이어도 0 rad로 옮김
    hand = server.Hand(bus, CFG)
    assert hand.home(timeout=0.1) == {}
    for n, j in CFG.joints.items():
        r = bus.regs[j.id]
        assert r["torque_enable"] == 1 and r["goal_position"] == j.zero and hand.servos[n].torque
        assert r["profile_velocity"] == 0   # 이동 뒤 원래 값으로 되돌림
    assert (ID("C_j1"), "profile_velocity", round(server.HOME_SPEED / VEL_UNIT)) in bus.writes


def test_loop_stats_in_state(client):
    s = client.get("/state").json()
    assert "loop" in s and s["loop"]["samples"] == 0 and s["loop"]["dropped_frac"] == 0.0


def test_loop_stats_jitter_and_dropped_frames():
    period = 0.02   # 50 Hz
    stats = server.LoopStats(period)
    p = round(period * 1e9)
    now = 1_000_000_000
    stats.tick(now)                       # 첫 tick은 기준점만
    for _ in range(100):
        now += p + 500_000               # 매 주기 +0.5 ms 편차 (정상 범위)
        stats.tick(now)
    now += round(p * 2.0)                 # 한 번 크게 밀림 → 누락 프레임 1
    stats.tick(now)
    s = stats.summary()
    assert s["samples"] == 101
    assert s["dropped_frames"] == 1
    assert s["dropped_frac"] == pytest.approx(1 / 101)
    assert 0.4 < s["jitter_ms_mean"] < 1.0   # 대부분 0.5 ms 편차
    assert s["jitter_ms_max"] == pytest.approx(period * 1000, abs=0.2)   # 2.0배 밀린 주기 = +20 ms 편차
    assert s["hz"] == pytest.approx(50, rel=0.1)


def test_loop_stats_reset():
    stats = server.LoopStats(0.02)
    stats.tick(0)
    stats.tick(20_000_000)
    assert stats.summary()["samples"] == 1
    stats.reset()
    assert stats.summary()["samples"] == 0


def test_recovery_reboots_and_counts_success(bus):
    hand = server.Hand(bus, CFG)
    hand.t0 = 99.0                               # 주입하는 now와 같은 시간축으로 맞춤
    hand.servos["A_j0"].torque = True            # 복구 후 토크/목표 재설정 확인용
    hand.servos["A_j0"].target = 0.2
    bus.regs[ID("A_j0")]["hardware_error_status"] = 0b100000   # 과부하
    hand.poll_slow()
    events = hand.check_recovery(now=100.0)       # 장애 감지 → reboot 1회
    assert any(e["kind"] == "reboot" and e["joint"] == "A_j0" for e in events)
    assert ID("A_j0") in bus.reboots and hand.reboots["attempts"] == 1

    hand.poll_slow()                              # reboot로 오류 지워짐
    events = hand.check_recovery(now=102.0)       # 2초 < 5초 → 성공
    assert any(e["kind"] == "recover_ok" for e in events)
    assert hand.reboots["successes"] == 1 and hand.reboots["failures"] == 0
    assert bus.regs[ID("A_j0")]["torque_enable"] == 1     # 재설정으로 토크 복원
    av = hand.availability(now=102.0)            # t0=99 → total=3s, downtime=2s
    assert av["downtime_s"] == pytest.approx(2.0) and av["availability"] == pytest.approx(1 / 3)


def test_recovery_marks_failure_after_timeout(bus):
    hand = server.Hand(bus, CFG)
    bus.regs[ID("B_j1")]["hardware_error_status"] = 0b100000
    hand.poll_slow()
    hand.check_recovery(now=100.0)                # 장애 시작 + reboot(오류 지움)
    bus.regs[ID("B_j1")]["hardware_error_status"] = 0b100000   # 복구 안 됨(재발)
    hand.poll_slow()
    events = hand.check_recovery(now=106.0)       # 6초 > 5초 → 실패 1회
    assert any(e["kind"] == "recover_failed" for e in events)
    assert hand.reboots["failures"] == 1


def test_no_auto_recover_detects_but_does_not_reboot(bus):
    hand = server.Hand(bus, CFG, auto_recover=False)
    bus.regs[ID("C_j2")]["hardware_error_status"] = 0b100000
    hand.poll_slow()
    hand.check_recovery(now=100.0)
    assert not getattr(bus, "reboots", []) and hand.reboots["attempts"] == 0
    assert hand.state()["hw_errors"]["C_j2"] == ["과부하"]   # 감지는 됨


def test_availability_full_when_no_faults(client):
    s = client.get("/state").json()
    assert s["availability"] == 1.0 and s["downtime_s"] == 0.0
    assert s["reboots"] == {"attempts": 0, "successes": 0, "failures": 0}


def test_csv_logging_writes_samples_and_events(bus, tmp_path):
    import csv
    import importlib.util as _u
    _s = _u.spec_from_file_location("runlog", ROOT / "real" / "runlog.py")
    runlog = _u.module_from_spec(_s)
    _s.loader.exec_module(runlog)

    hand = server.Hand(bus, CFG)
    hand.logger = runlog.CsvLogger(tmp_path / "run")

    bus.regs[ID("A_j0")]["present_temperature"] = 40
    hand.poll()
    hand.poll_slow()                       # 1 Hz 샘플 1묶음(관절 7행)
    hand.poll_slow()                       # 2묶음

    bus.regs[ID("A_j0")]["hardware_error_status"] = 0b100000
    hand.poll_slow()
    hand.check_recovery(now=10.0)          # reboot 이벤트 1건
    hand.log_run_summary()
    hand.logger.close()

    rows = list(csv.DictReader(open(tmp_path / "run" / "joint_sample.csv")))
    assert len(rows) == 3 * len(CFG.joints)          # poll_slow 3회 × 7관절
    assert any(r["joint"] == "A_j0" and r["temperature_c"] == "40" for r in rows)

    errs = list(csv.DictReader(open(tmp_path / "run" / "error_event.csv")))
    assert any(e["kind"] == "reboot" and e["joint"] == "A_j0" for e in errs)

    run = list(csv.DictReader(open(tmp_path / "run" / "run.csv")))
    assert run and "packet_error_rate" in run[0] and "availability" in run[0]


def test_home_reports_joints_that_did_not_arrive(bus):
    hand = server.Hand(bus, CFG)
    real_write = bus.write

    def stuck_write(i, name, value):
        real_write(i, name, value)
        if i == ID("B_j2"):
            bus.regs[i]["present_position"] = 2300   # 걸려서 움직이지 못함
    bus.write = stuck_write
    far = hand.home(timeout=0.05)
    assert list(far) == ["B_j2"] and far["B_j2"] > 0.3
