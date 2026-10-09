import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import motors  # noqa: E402
from run_sim import Q_CLOSE  # noqa: E402


class FakeBus:
    """모터 레지스터를 dict로 흉내. 쓰기 순서를 log에 남김"""

    def __init__(self, ids, mode=motors.POSITION_MODE, error=0, present=2048):
        self.reg = {i: {motors.OPERATING_MODE: mode, motors.HARDWARE_ERROR: error,
                        motors.PRESENT_POSITION: present, motors.TORQUE_ENABLE: 0} for i in ids}
        self.log, self.closed = [], False

    def read(self, i, field):
        return self.reg[i][field]

    def write(self, i, field, value):
        self.reg[i][field] = value
        self.log.append((i, field, value))

    def positions(self, ids):
        return {i: self.reg[i][motors.PRESENT_POSITION] for i in ids}

    def goals(self, raw):
        for i, v in raw.items():
            self.write(i, motors.GOAL_POSITION, v)

    def close(self):
        self.closed = True


# B는 오므림이 +, A는 -. A_j2 모터는 오므리면 틱이 증가하도록 장착됐다고 가정 → sign -1
JOINTS = {
    "A_j0": {"id": 1, "zero": 2000, "sign": 1},
    "A_j2": {"id": 3, "zero": 2048, "sign": -1},
    "B_j2": {"id": 5, "zero": 1000, "sign": 1},
}


def hand(bus=None):
    return motors.HandMotors(bus or FakeBus([1, 3, 5]), JOINTS, max_speed=3.0)


def goal(bus, i):
    return bus.reg[i][motors.GOAL_POSITION]


def test_targets_are_clipped_between_straight_and_close_angle():
    bus = FakeBus([1, 3, 5])
    with hand(bus) as h:
        h.send({"B_j2": 5.0, "A_j2": +0.5, "A_j0": 0.8})   # 지나치게 오므림 / 반대로 젖힘 / 엄지 요
        assert goal(bus, 5) == motors.to_raw(JOINTS["B_j2"], Q_CLOSE["j2"])
        assert goal(bus, 3) == JOINTS["A_j2"]["zero"]   # 펼침 너머로 가지 않음
        assert goal(bus, 1) == JOINTS["A_j0"]["zero"]   # 엄지 요는 0 고정


def test_closing_in_sim_moves_motor_the_way_it_was_bent_during_calibration():
    cal = {"zero": 2048, "sign": motors.motor_sign("A_j2", close_delta=+300)}
    assert motors.to_raw(cal, -Q_CLOSE["j2"]) > cal["zero"]   # A의 오므림(-)이 틱 증가 방향
    cal = {"zero": 2048, "sign": motors.motor_sign("B_j2", close_delta=-300)}
    assert motors.to_raw(cal, +Q_CLOSE["j2"]) < cal["zero"]   # B의 오므림(+)이 틱 감소 방향


def test_torque_turns_on_holding_present_position_with_speed_limit():
    bus = FakeBus([1, 3, 5], present=1500)
    with hand(bus):
        for i in (1, 3, 5):
            writes = [(f, v) for j, f, v in bus.log if j == i]
            on = writes.index((motors.TORQUE_ENABLE, 1))
            assert (motors.GOAL_POSITION, 1500) in writes[:on]
            rpm = bus.reg[i][motors.PROFILE_VELOCITY] * motors.RPM_PER_UNIT
            assert 0 < rpm * 2 * 3.14159 / 60 <= 3.0


def test_torque_off_and_port_closed_even_on_error():
    bus = FakeBus([1, 3, 5])
    with pytest.raises(IOError):
        with hand(bus):
            raise IOError("통신 끊김")
    assert all(bus.reg[i][motors.TORQUE_ENABLE] == 0 for i in (1, 3, 5))
    assert bus.closed


@pytest.mark.parametrize("kw", [{"mode": 1}, {"error": 0x20}])
def test_refuses_to_start_without_position_mode_or_with_hardware_error(kw):
    bus = FakeBus([1, 3, 5], **kw)
    with pytest.raises(SystemExit):
        hand(bus)
    assert not any(f == motors.TORQUE_ENABLE for _, f, _ in bus.log)


def test_detect_picks_moved_motor_and_ignores_small_or_taken():
    before = {1: 2000, 2: 2000, 3: 2000}
    assert motors.detect(before, {1: 2010, 2: 1700, 3: 2000}, taken=set()) == (2, -300)
    assert motors.detect(before, {1: 2050, 2: 2000, 3: 2000}, taken=set()) is None
    assert motors.detect(before, {1: 2000, 2: 1700, 3: 2400}, taken={3}) == (2, -300)
