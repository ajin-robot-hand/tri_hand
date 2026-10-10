"""choreo(t): 음원 시각 t(s) → 7관절 목표 각도(rad).

MuJoCo와 실물이 똑같이 쓰는 순수 함수. 시간만 넣으면 자세가 나오므로
마스터 클럭(음원 재생 위치)만 정확하면 누적 오차가 생기지 않는다.

정규화값 → rad: CLOSE_SIGN[손가락] * (q>=0 ? Q_CLOSE : Q_OPEN)[관절] * q.  A_j0만 처음부터 rad.
"""
import bisect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/ 를 import 경로에

from heartbeat.schedule import JOINTS, build_timeline
from run_sim import CLOSE_SIGN, Q_CLOSE, Q_OPEN

_TIMELINE = build_timeline()
_TIMES = [kf["t"] for kf in _TIMELINE]

START: float = _TIMES[0]
END: float = _TIMES[-1]


def to_rad(joint: str, q_norm: float) -> float:
    """-1~+1 정규화 오므림량 → rad. A_j0(요)은 이미 rad이므로 그대로.

    0이 곧게 편 자세, +1이 오므림 끝(Q_CLOSE), -1이 바깥으로 누운 끝(Q_OPEN)이다.
    양쪽 끝의 크기가 다를 수 있어 부호에 따라 다른 배율을 쓴다.
    """
    finger, _, j = joint.partition("_")
    if j not in Q_CLOSE:
        return q_norm
    span = Q_CLOSE[j] if q_norm >= 0.0 else Q_OPEN[j]
    return CLOSE_SIGN[finger] * span * q_norm


def _ease(u: float, kind: str) -> float:
    """0~1 진행률 u를 보간 곡선에 태운다. 'out'은 도착할 때 감속한다."""
    if kind == "linear":
        return u
    if kind == "out":                       # cubic ease-out: 빠르게 출발해 박에 사뿐히 도착
        return 1.0 - (1.0 - u) ** 3
    return u * u * (3.0 - 2.0 * u)          # inout: smoothstep


def pose_norm(t: float) -> dict[str, float]:
    """t 시점의 정규화 자세. 타임라인 바깥은 양 끝 키프레임을 유지."""
    if t <= START:
        return dict(_TIMELINE[0]["q"])
    if t >= END:
        return dict(_TIMELINE[-1]["q"])

    i = bisect.bisect_right(_TIMES, t) - 1
    a, b = _TIMELINE[i], _TIMELINE[i + 1]
    span = b["t"] - a["t"]
    u = _ease((t - a["t"]) / span, b["ease"]) if span > 0 else 1.0
    return {j: a["q"][j] + (b["q"][j] - a["q"][j]) * u for j in JOINTS}


def choreo(t: float) -> dict[str, float]:
    """t 시점의 7관절 목표 각도(rad)."""
    return {j: to_rad(j, q) for j, q in pose_norm(t).items()}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from heartbeat.grid import bar_beat_to_time

    print(f"타임라인 {START:.3f} ~ {END:.3f} s, 키프레임 {len(_TIMELINE)}개\n")
    print("  시각     " + "  ".join(f"{j:>7}" for j in JOINTS))
    for bar in range(1, 21):
        for beat in (0.0, 2.0):
            t = bar_beat_to_time(bar, beat)
            q = choreo(t)
            print(f"{t:7.3f}s  " + "  ".join(f"{q[j]:+7.3f}" for j in JOINTS)
                  + (f"   ← 마디 {bar}" if beat == 0.0 else ""))
