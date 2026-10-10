"""시간표 자동 검증. 재생 전에 반드시 한 번 호출한다 (AGENTS.md 4장).

위반하면 어느 키프레임·관절인지 찍고 ValidationError로 중단한다.
자가 충돌(규칙 5)은 정적으로 알 수 없으므로 play.py --headless 전구간 실행에서 본다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/ 를 import 경로에

from heartbeat.choreo import to_rad
from heartbeat.grid import BEAT_PERIOD, END as AUDIO_END, time_to_bar_beat
from heartbeat.schedule import JOINTS, MOTIONS, build_timeline
from motors import safe_range

MAX_SPEED = 3.0          # rad/s, AGENTS.md 3장 관절 회전 속도 상한
GRID_SUBDIVISION = 2     # 8분음표까지 허용 (beat 값이 0.5의 배수여야 함)

# 보간 곡선마다 '순간 최대 속도 / 평균 속도' 비율이 다르다. 평균만 보면 ease="out"의
# 출발 순간(평균의 3배)을 놓쳐서, 검증을 통과해도 실제로는 상한을 넘는다.
EASE_PEAK = {
    "linear": 1.0,   # 기울기 일정
    "out": 3.0,      # 1-(1-u)^3 → u=0에서 3배로 출발
    "inout": 1.5,    # 3u²-2u³ → u=0.5에서 1.5배
}


class ValidationError(AssertionError):
    """시간표가 하드웨어 안전 규칙을 어겼다."""


def check_safe_range(timeline) -> list[str]:
    bad = []
    for kf in timeline:
        for j in JOINTS:
            q = to_rad(j, kf["q"][j])
            lo, hi = safe_range(j)
            if not (lo - 1e-9 <= q <= hi + 1e-9):
                bad.append(f"{kf['tag']} {j}={q:+.3f} rad 가 안전 범위 [{lo:+.3f}, {hi:+.3f}] 밖")
    return bad


def peak_speed(a: dict, b: dict, joint: str) -> float:
    """두 키프레임 사이 관절의 순간 최대 명령 속도(rad/s). 보간 곡선을 반영한다."""
    dt = b["t"] - a["t"]
    if dt <= 0:
        return float("inf")
    mean = abs(to_rad(joint, b["q"][joint]) - to_rad(joint, a["q"][joint])) / dt
    return mean * EASE_PEAK.get(b["ease"], 1.5)


def check_speed_limit(timeline) -> list[str]:
    bad = []
    for a, b in zip(timeline, timeline[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0:
            bad.append(f"{a['tag']} → {b['tag']}: 시각이 증가하지 않음 (Δt={dt:.4f}s)")
            continue
        for j in JOINTS:
            v = peak_speed(a, b, j)
            if v > MAX_SPEED:
                bad.append(f"{a['tag']} → {b['tag']} {j}: 순간 {v:.2f} rad/s "
                           f"(ease={b['ease']}, ×{EASE_PEAK.get(b['ease'], 1.5)}) > {MAX_SPEED}")
    return bad


def check_grid_alignment() -> list[str]:
    """도착 시각이 박 격자(8분음표 단위)에 놓이는지. 동작 정의 자체를 본다."""
    step = 1.0 / GRID_SUBDIVISION
    bad = []
    for mid, m in MOTIONS.items():
        if mid.startswith("_"):
            continue
        for kf in m["keyframes"]:
            beat = kf["beat"]
            if abs(beat / step - round(beat / step)) > 1e-9:
                bad.append(f"동작 {mid} beat={beat} 가 {step}박 격자에 정렬되지 않음")
            if not (0 <= beat < m["beats"]):
                bad.append(f"동작 {mid} beat={beat} 가 길이 {m['beats']}박을 벗어남")
    return bad


def check_duration(timeline) -> list[str]:
    last = timeline[-1]["t"]
    if last > AUDIO_END:
        bar, beat = time_to_bar_beat(last)
        return [f"시간표 끝 {last:.3f}s (마디 {bar}.{beat:.1f}) 가 음원 길이 {AUDIO_END:.3f}s 초과"]
    return []


def validate_all(verbose: bool = False) -> list[dict]:
    """규칙 1~4를 모두 검사하고 타임라인을 돌려준다. 위반 시 ValidationError."""
    timeline = build_timeline()
    problems = (check_safe_range(timeline) + check_speed_limit(timeline)
                + check_grid_alignment() + check_duration(timeline))
    if problems:
        raise ValidationError("시간표 검증 실패:\n  - " + "\n  - ".join(problems))
    if verbose:
        worst = max((peak_speed(a, b, j), j, f"{a['tag']}→{b['tag']}")
                    for a, b in zip(timeline, timeline[1:]) for j in JOINTS)
        print(f"✅ 검증 통과: 키프레임 {len(timeline)}개, "
              f"{timeline[0]['t']:.3f}~{timeline[-1]['t']:.3f}s, "
              f"최대 명령 속도 {worst[0]:.2f} rad/s ({worst[1]} @ {worst[2]}, 상한 {MAX_SPEED})")
    return timeline


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    validate_all(verbose=True)
    print(f"박 길이 {BEAT_PERIOD*1000:.1f} ms 기준 8분음표 = {BEAT_PERIOD*500:.1f} ms")
