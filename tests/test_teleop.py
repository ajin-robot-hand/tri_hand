import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import teleop  # noqa: E402
from run_sim import CLOSE_SIGN, Q_CLOSE, YAW_AMPLITUDE  # noqa: E402


def hand(mcp: float = 0.0, rest: float = 0.0, spread: float = 0.0) -> np.ndarray:
    """21 관절점. 손목이 원점, 손바닥은 xy 면, 엄지 쪽이 +x. 손가락은 손목→MCP 방향으로 부채꼴로 뻗음.
    MCP에서 mcp, PIP·DIP에서 rest/2씩 +z로 꺾임. 검지만 손바닥 면에서 +x 쪽으로 spread만큼 더 벌어짐"""
    points = np.zeros((21, 3))
    for k_finger, chain in enumerate(teleop.CHAINS.values()):   # 검지, 중지, 약지 순
        s = spread if chain[1] == 5 else 0.0
        p, heading = np.array([0.02 * (1 - k_finger), 0.08, 0.0]), 0.0
        fan = np.arctan2(p[0], p[1]) + s
        u = np.array([np.sin(fan), np.cos(fan), 0.0])   # 손바닥 면에서의 손가락 방향
        bends = [mcp, rest / 2, rest / 2]
        points[chain[1]] = p
        for k, idx in enumerate(chain[2:]):
            heading += bends[k]
            p = p + 0.03 * (np.cos(heading) * u + np.sin(heading) * np.array([0.0, 0.0, 1.0]))
            points[idx] = p
    return points


def test_open_hand_sends_zero():   # A_j0 포함
    assert all(q == 0.0 for q in teleop.retarget(hand()).values())


def test_full_fist_reaches_close_angle_in_close_direction():
    targets = teleop.retarget(hand(mcp=np.pi / 2, rest=np.pi))
    for name, q in targets.items():
        finger, _, j = name.partition("_")
        if j == "j0":
            continue   # 90° 굽힌 검지는 좌우를 알 수 없어 A_j0를 보내지 않음 (아래 테스트)
        assert q == pytest.approx(CLOSE_SIGN[finger] * Q_CLOSE[j])


def test_bend_angle_is_measured_not_guessed():
    bends = teleop.finger_bends(hand(mcp=0.5, rest=1.0))
    assert bends["B"]["j1"] == pytest.approx(0.5)
    assert bends["B"]["j2"] == pytest.approx(1.0)


def test_index_middle_ring_drive_a_b_c():
    for robot, human in (("A", slice(5, 9)), ("B", slice(9, 13)), ("C", slice(13, 17))):
        points = hand()
        points[human] = hand(mcp=1.0)[human]   # 사람 손가락 하나만 MCP를 굽힘
        moved = {n for n, q in teleop.retarget(points).items() if abs(q) > 1e-9}
        assert moved == {f"{robot}_j1"}


@pytest.mark.parametrize("mcp", [0.0, 0.8])   # 굽혀도 같은 값
def test_index_spread_drives_a_j0_and_ignores_flexion(mcp):
    spread = teleop.SPREAD_MAX / 2
    assert teleop.index_spread(hand(mcp=mcp, spread=spread)) == pytest.approx(spread)
    assert teleop.retarget(hand(mcp=mcp, spread=spread))["A_j0"] == pytest.approx(
        teleop.SPREAD_SIGN * YAW_AMPLITUDE / 2)
    assert teleop.retarget(hand(mcp=mcp, spread=-1.0))["A_j0"] == pytest.approx(
        -teleop.SPREAD_SIGN * YAW_AMPLITUDE)   # 범위 밖은 끝에서 멈춤


def test_spread_ignored_when_index_bent_too_far():
    assert "A_j0" not in teleop.retarget(hand(mcp=1.4, spread=0.2))


def test_smoother_limits_speed():
    s = teleop.Smoother()
    s({"B_j2": 0.0}, 0.033)
    out = s({"B_j2": 1.2}, 0.033)   # 한 프레임에 끝까지 오므리라는 입력
    assert out["B_j2"] == pytest.approx(teleop.MAX_SPEED * 0.033)
