import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import teleop  # noqa: E402
from run_sim import CLOSE_SIGN, Q_CLOSE  # noqa: E402


def hand(mcp: float = 0.0, rest: float = 0.0) -> np.ndarray:
    """21 관절점. 모든 손가락이 손목에서 +y로 뻗고, MCP에서 mcp, PIP·DIP(엄지는 IP)에서 rest/2씩 꺾임"""
    points = np.zeros((21, 3))
    for chain in teleop.CHAINS.values():
        bends = [mcp, rest / 2, rest / 2][: len(chain) - 2]
        p, heading = np.zeros(3), 0.0
        if chain[0] != 0:   # 엄지는 손목이 아닌 CMC에서 시작
            p = points[chain[0]] = np.array([0.02, 0.0, 0.0])
        for k, idx in enumerate(chain[1:]):
            if k > 0:
                heading += bends[k - 1]
            p = p + 0.03 * np.array([0.0, np.cos(heading), np.sin(heading)])
            points[idx] = p
    return points


def test_open_hand_sends_zero():
    assert all(q == 0.0 for q in teleop.retarget(hand()).values())


def test_full_fist_reaches_close_angle_in_close_direction():
    targets = teleop.retarget(hand(mcp=np.pi / 2, rest=np.pi))
    for name, q in targets.items():
        finger, _, j = name.partition("_")
        assert q == pytest.approx(CLOSE_SIGN[finger] * Q_CLOSE[j])


def test_bend_angle_is_measured_not_guessed():
    bends = teleop.finger_bends(hand(mcp=0.5, rest=1.0))
    assert bends["B"]["j1"] == pytest.approx(0.5)
    assert bends["B"]["j2"] == pytest.approx(1.0)
    assert bends["A"]["j2"] == pytest.approx(0.5)   # 엄지는 IP 하나만 j2


def test_thumb_yaw_is_never_sent():
    assert "A_j0" not in teleop.retarget(hand(mcp=1.0, rest=1.0))


def test_smoother_limits_speed():
    s = teleop.Smoother()
    s({"B_j2": 0.0}, 0.033)
    out = s({"B_j2": 1.2}, 0.033)   # 한 프레임에 끝까지 오므리라는 입력
    assert out["B_j2"] == pytest.approx(teleop.MAX_SPEED * 0.033)
