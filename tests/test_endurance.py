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


class FlakyClient(FakeClient):
    """state()/apply_preset()가 지정한 호출 번호에서 통신 오류를 내는 가짜 서버."""

    def __init__(self, grips, hot_after, fail_states=(), fail_applies=(), down_after=None):
        super().__init__(grips, hot_after)
        self._fail_states = set(fail_states)
        self._fail_applies = set(fail_applies)
        self._down_after = down_after   # 이 번호 이후 state()는 계속 실패 (서버 다운)
        self._state_calls = 0
        self._apply_calls = 0

    def apply_preset(self, name):
        self._apply_calls += 1
        if self._apply_calls in self._fail_applies:
            raise endurance.urllib.error.URLError("timed out")
        super().apply_preset(name)

    def state(self):
        self._state_calls += 1
        n = self._state_calls
        if n in self._fail_states or (self._down_after is not None and n > self._down_after):
            raise TimeoutError("timed out")
        return super().state()


def test_run_survives_transient_comm_errors():
    # 그립 명령 1번, 상태 조회 2번 실패해도 계속 돌다가 과열 조건에서 정상 종료
    c = FlakyClient(["power"], hot_after=3, fail_states={2, 3}, fail_applies={1})
    summary = endurance.run(c, hours=1.0, poll=0.0, max_temp=65)
    assert "과열 중단" in summary
    assert "통신 실패 3회" in summary
    assert c.applied == ["power"]          # 실패한 그립 명령을 다음 주기에 재전송
    assert c.torque[-1] is False


def test_run_aborts_after_sustained_outage_and_still_summarizes():
    # 서버가 죽으면 max_outage 뒤 중단, 마지막 요약 조회가 실패해도 예외 없이 요약 반환
    c = FlakyClient(["power"], hot_after=10**9, down_after=1)
    summary = endurance.run(c, hours=1.0, poll=0.0, max_temp=65, max_outage=0.0)
    assert "통신 두절 중단" in summary
    assert "서버 응답 없음" in summary
    assert c.grasps[-1] == 0.0 and c.torque[-1] is False   # 중단 시 오픈·토크 off 시도
