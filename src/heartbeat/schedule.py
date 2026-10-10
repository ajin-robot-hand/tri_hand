"""구간 표(schedule.json) → 마디별 동작 배정 → 절대 시각 키프레임 타임라인.

핵심 아이디어: 모든 동작을 미리 펼쳐 **하나의 전역 타임라인**으로 만든다.
- 동작 사이 경계가 그냥 이웃한 두 키프레임이 되므로 전환이 자동으로 부드럽다.
- 검증(validate.py)이 "인접한 두 키프레임" 하나만 보면 되므로 규칙이 단순해진다.
- 재생 중에는 이분 탐색 한 번이라 실시간 부담이 없다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/ 를 import 경로에 (어떤 실행 방식에서도 동작)

from heartbeat.grid import BEATS_PER_BAR, bar_beat_to_time

MOTIONS = json.loads(Path(__file__).with_name("motions.json").read_text(encoding="utf-8"))
SCHEDULE = json.loads(Path(__file__).with_name("schedule.json").read_text(encoding="utf-8"))

JOINTS = ("A_j0", "A_j1", "A_j2", "B_j1", "B_j2", "C_j1", "C_j2")
SECTIONS = [s for s in SCHEDULE["sections"]]
RULES = SCHEDULE.get("rules", {})

FIRST_BAR: int = SECTIONS[0]["bars"][0]
LAST_BAR: int = SECTIONS[-1]["bars"][1]


def get_motion(bar: int) -> tuple[str, float]:
    """bar번 마디의 (동작 ID, 동작이 시작된 마디). 배정이 없으면 ValueError."""
    for s in SECTIONS:
        lo, hi = s["bars"]
        if lo <= bar <= hi:
            motion = s["motion"]
            stride = MOTIONS[motion]["beats"] // BEATS_PER_BAR   # 동작 한 번이 차지하는 마디 수
            reps = (bar - lo) // stride
            return motion, lo + reps * stride
    raise ValueError(f"마디 {bar}에 배정된 동작이 없습니다 (구간 표: {FIRST_BAR}~{LAST_BAR})")


def build_schedule() -> list[dict]:
    """마디별 배정 목록. 난수 없이 같은 입력이면 같은 결과."""
    out = []
    for bar in range(FIRST_BAR, LAST_BAR + 1):
        motion, start_bar = get_motion(bar)
        out.append({"bar": bar, "motion": motion, "start_bar": start_bar,
                    "time": bar_beat_to_time(bar)})
    return out


def _scaled(q_norm: dict, scale: float) -> dict:
    """악센트 배율. A_j0은 요 회전이라 방향을 유지한 채 크기만 키운다."""
    return {k: v * scale for k, v in q_norm.items()}


def build_timeline() -> list[dict]:
    """전체 구간을 펼친 절대 시각 키프레임 목록.

    각 원소는 {"t": 초, "q": {관절: 0~1 정규화값 또는 A_j0은 rad}, "ease": str, "tag": str}.
    "q"는 7관절이 모두 채워진 상태다(생략한 관절은 직전 값 유지 규칙을 여기서 해소).
    """
    accent = RULES.get("accent_first_beat_scale", 1.0)
    state = {j: 0.0 for j in JOINTS}
    timeline: list[dict] = []

    bar = FIRST_BAR
    while bar <= LAST_BAR:
        motion_id, start_bar = get_motion(bar)
        if start_bar != bar:          # 이미 앞선 마디에서 펼친 반복의 중간
            bar += 1
            continue
        motion = MOTIONS[motion_id]
        for kf in motion["keyframes"]:
            beat = kf["beat"]
            scale = accent if beat == 0 else 1.0
            state = {**state, **_scaled(kf["q"], scale)}
            timeline.append({
                "t": bar_beat_to_time(bar, beat),
                "q": dict(state),
                "ease": kf.get("ease", "inout"),
                "tag": f"{motion_id}@{bar}.{beat}",
            })
        bar += motion["beats"] // BEATS_PER_BAR

    # 마무리: 마지막 마디가 끝난 뒤 중립으로 복귀
    outro = RULES.get("outro_beats", 4)
    timeline.append({
        "t": bar_beat_to_time(LAST_BAR + 1, outro),
        "q": {j: 0.0 for j in JOINTS},
        "ease": "inout",
        "tag": "neutral@outro",
    })
    return timeline


#: 시간표가 끝나는 시각(s). 재생 루프의 종료 조건.
def end_time() -> float:
    return build_timeline()[-1]["t"]


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"구간 표: 마디 {FIRST_BAR}~{LAST_BAR}, 끝 {end_time():.3f} s\n")
    print(" 마디   시각      동작      라벨")
    for row in build_schedule():
        head = "←" if row["start_bar"] == row["bar"] else " "
        print(f"  {row['bar']:3d}  {row['time']:6.3f}s  {head} {row['motion']:<7}"
              f"  {MOTIONS[row['motion']]['label']}")
    print(f"\n키프레임 {len(build_timeline())}개")
