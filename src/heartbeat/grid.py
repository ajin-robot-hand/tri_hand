"""비트 격자: 마디·박 ↔ 음원 시각(s) 변환.

grid.json의 상수 4개만으로 모든 시각을 수식으로 계산한다. 검출된 비트 시각 목록을
그대로 쓰지 않는 이유는 23 ms 프레임에 양자화되어 명령이 들쭉날쭉 나가기 때문이다.
외부 의존성 없음(순수 함수).
"""
import json
from pathlib import Path

GRID = json.loads(Path(__file__).with_name("grid.json").read_text(encoding="utf-8"))

BPM: float = GRID["bpm"]                            # 135.0
FIRST_DOWNBEAT: float = GRID["first_downbeat"]      # 0.422 s, 마디 1의 첫 박
BEATS_PER_BAR: int = GRID["beats_per_bar"]          # 4
BEAT_PERIOD: float = 60.0 / BPM                     # 0.444444 s
BAR_PERIOD: float = BEAT_PERIOD * BEATS_PER_BAR     # 1.777778 s
BARS: int = GRID["bars"]                            # 45 (음원 전체)
END: float = FIRST_DOWNBEAT + BARS * BAR_PERIOD     # 80.422 s


def bar_beat_to_time(bar: int, beat: float = 0.0) -> float:
    """마디 k(1부터) + 박 오프셋 → 음원 시각(s). beat=0.0이 마디 첫 박, 0.5는 8분음표."""
    return FIRST_DOWNBEAT + (bar - 1) * BAR_PERIOD + beat * BEAT_PERIOD


def time_to_bar_beat(t: float) -> tuple[int, float]:
    """음원 시각 → (마디 번호 1부터, 박 오프셋 0~BEATS_PER_BAR)."""
    beats = (t - FIRST_DOWNBEAT) / BEAT_PERIOD
    bar, beat = divmod(beats, BEATS_PER_BAR)
    return int(bar) + 1, beat


def snap_to_grid(t: float, subdivisions: int = 1) -> float:
    """t를 가장 가까운 박 격자에 스냅. subdivisions=1은 4분음표, 2는 8분음표."""
    step = BEAT_PERIOD / subdivisions
    return FIRST_DOWNBEAT + round((t - FIRST_DOWNBEAT) / step) * step


if __name__ == "__main__":
    print(f"BPM {BPM}  1박 {BEAT_PERIOD*1000:.3f} ms  1마디 {BAR_PERIOD:.5f} s  "
          f"마디 1~{BARS}  끝 {END:.3f} s")
    for bar in range(1, BARS + 1):
        print(f"  마디 {bar:2d}: {bar_beat_to_time(bar):7.3f} s")
