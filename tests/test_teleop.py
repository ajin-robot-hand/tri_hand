import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import teleop  # noqa: E402
from run_sim import CLOSE_SIGN, Q_CLOSE, YAW_AMPLITUDE  # noqa: E402


def hand(mcp: float = 0.0, rest: float = 0.0, thumb: float = sum(teleop.THUMB_RANGE) / 2,
         thumb_lift: float = 0.0) -> np.ndarray:
    """21 관절점. 손목이 원점, 손바닥은 xy 면, 엄지 쪽이 +x. 손가락은 손목→MCP 방향으로 부채꼴로 뻗음.
    MCP에서 mcp, PIP·DIP에서 rest/2씩 +z로 꺾임.
    엄지 CMC→MCP는 손목→검지 MCP 선에서 손바닥 면 +x 쪽으로 thumb만큼, 면 밖 +z로 thumb_lift만큼 기울어짐"""
    points = np.zeros((21, 3))
    index_line = np.arctan2(0.02, 0.08) + thumb
    points[1] = [0.02, 0.02, 0.0]
    points[2] = points[1] + 0.03 * np.array([np.cos(thumb_lift) * np.sin(index_line),
                                             np.cos(thumb_lift) * np.cos(index_line), np.sin(thumb_lift)])
    for k_finger, chain in enumerate(teleop.CHAINS.values()):   # 검지, 중지, 약지 순
        p, heading = np.array([0.02 * (1 - k_finger), 0.08, 0.0]), 0.0
        fan = np.arctan2(p[0], p[1])
        u = np.array([np.sin(fan), np.cos(fan), 0.0])   # 손바닥 면에서의 손가락 방향
        bends = [mcp, rest / 2, rest / 2]
        points[chain[1]] = p
        for k, idx in enumerate(chain[2:]):
            heading += bends[k]
            p = p + 0.03 * (np.cos(heading) * u + np.sin(heading) * np.array([0.0, 0.0, 1.0]))
            points[idx] = p
    return points


def test_open_hand_with_relaxed_thumb_sends_zero():   # 엄지가 THUMB_RANGE 가운데면 A_j0도 0
    assert teleop.retarget(hand()) == pytest.approx(dict.fromkeys(teleop.retarget(hand()), 0.0))


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


@pytest.mark.parametrize("lift", [0.0, 0.6])   # 엄지가 손바닥 면에서 조금 들려도 같은 값
def test_thumb_spread_drives_a_j0(lift):
    lo, hi = teleop.THUMB_RANGE
    assert teleop.thumb_spread(hand(thumb=0.7, thumb_lift=lift)) == pytest.approx(0.7)
    a_j0 = lambda t: teleop.retarget(hand(thumb=t, thumb_lift=lift))["A_j0"]
    assert a_j0(lo) == pytest.approx(-teleop.THUMB_SIGN * YAW_AMPLITUDE)   # 검지에 붙임 → 한쪽 끝
    assert a_j0(hi) == pytest.approx(+teleop.THUMB_SIGN * YAW_AMPLITUDE)   # 최대로 벌림 → 반대쪽 끝
    assert a_j0(hi + 1.0) == pytest.approx(+teleop.THUMB_SIGN * YAW_AMPLITUDE)   # 범위 밖은 끝에서 멈춤


def test_thumb_spread_not_changed_by_finger_bending():
    assert teleop.thumb_spread(hand(mcp=1.2, rest=2.0, thumb=0.7)) == pytest.approx(0.7)


def test_thumb_far_out_of_palm_plane_holds_a_j0():
    assert "A_j0" not in teleop.retarget(hand(thumb_lift=1.2))


def test_smoother_limits_speed():
    s = teleop.Smoother()
    s({"B_j2": 0.0}, 0.033)
    out = s({"B_j2": 1.2}, 0.033)   # 한 프레임에 끝까지 오므리라는 입력
    assert out["B_j2"] == pytest.approx(teleop.MAX_SPEED * 0.033)
