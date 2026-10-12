"""real/endurance.py (24h 러너, T-14) 테스트. HTTP 없이 순수 함수와 run() 루프를 검증.

  ~/mujoco_env/bin/python -m pytest tests/test_endurance.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "real"))

_spec = importlib.util.spec_from_file_location("endurance", ROOT / "real" / "endurance.py")
endurance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(endurance)


def test_phase_duty_cycle():
    # 듀티 120s = 정적 30 + 오픈 90
    assert endurance.phase_at(0, 3)[0] == "grasp"
    assert endurance.phase_at(29.9, 3)[0] == "grasp"
    assert endurance.phase_at(30, 3)[0] == "open"
    assert endurance.phase_at(119.9, 3)[0] == "open"
    assert endurance.phase_at(120, 3)[0] == "grasp"   # 다음 듀티 시작


def test_phase_rotates_grips_every_5min():
    assert endurance.phase_at(0, 3)[1] == 0
    assert endurance.phase_at(300, 3)[1] == 1
    assert endurance.phase_at(600, 3)[1] == 2
    assert endurance.phase_at(900, 3)[1] == 0   # 한 바퀴
    assert endurance.phase_at(0, 0)[1] is None  # 프리셋 없음


def test_over_temp_flags_hot_joints():
    st = {"temperatures": {"A_j0": 40, "B_j1": 70, "C_j2": 66}}
    assert endurance.over_temp(st, 65) == {"B_j1": 70, "C_j2": 66}
    assert endurance.over_temp(st, 80) == {}


class FakeClient:
    """상태 호출 N번 뒤 뜨거워지는 가짜 서버."""

    def __init__(self, grips, hot_after):
        self._grips = grips
        self._hot_after = hot_after
        self._calls = 0
        self.torque = []
        self.grasps = []
        self.applied = []

    def presets(self):
        return {n: {} for n in self._grips}

    def set_torque(self, enabled):
        self.torque.append(enabled)

    def apply_preset(self, name):
        self.applied.append(name)

    def grasp(self, amount):
        self.grasps.append(amount)

    def state(self):
        self._calls += 1
        temp = 70 if self._calls > self._hot_after else 30
        return {"temperatures": {"A_j0": temp}, "packets": {"tx": 1000, "rx_errors": 1},
                "loop": {"jitter_ms_p95": 1.2, "dropped_frac": 0.0},
                "availability": 0.999, "downtime_s": 0.0,
                "reboots": {"attempts": 0, "successes": 0, "failures": 0}}


def test_run_aborts_on_overtemp_and_disables_torque():
    c = FakeClient(["power", "pinch", "spherical"], hot_after=1)
    summary = endurance.run(c, hours=1.0, poll=0.0, max_temp=65)
    assert "과열 중단" in summary
    assert c.torque[0] is True and c.torque[-1] is False   # 시작 때 켜고 끝에 끔
    assert c.grasps[-1] == 0.0                              # 중단 시 오픈
    assert c.applied and c.applied[0] == "power"            # 첫 그립 적용


def test_run_falls_back_to_grasp_without_presets():
    c = FakeClient([], hot_after=1)
    endurance.run(c, hours=1.0, poll=0.0, max_temp=65)
    assert 1.0 in c.grasps   # 프리셋이 없으면 /grasp amount=1로 파지
