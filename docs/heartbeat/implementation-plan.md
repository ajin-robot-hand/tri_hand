# Heartbeat 구현 계획 (Phase별 상세)

> 최종 목표: 스크립트 실행 → 음원 재생 + 로봇이 135 BPM 박자에 맞춰 45마디(80.4s) 동작
>
> 기준 확정값: BPM 135, first_downbeat 0.422s, 45마디, 1마디 = 1.77778s
>
> 읽는 순서: 이 문서 → `brainstorming.md`(배경·제약) → `choreography.md`(영상 분석 근거) → 각 Phase 착수
>
> **구현 현황 (2026-10-10)**: Phase 0~5 완료. 단, 재생 범위는 영상을 분석한 **마디 1~19(음원 34.2 s)** 까지다.
> 마디 20~45는 영상 33초 이후 구간이라 `schedule.json`에 비어 있다 — 구간만 추가하면 그대로 늘어난다.
> Phase 6(실물 이식)은 미착수.

---

## Phase 0 — 음원 격자 확정 ✅ 완료

**완료 기준 달성**: `src/heartbeat/grid.json` 커밋됨 (2026-10-10)

```json
{ "bpm": 135.0, "first_downbeat": 0.422, "beats_per_bar": 4, "bars": 45 }
```

---

## Phase 1 — `grid.py` + 단위 테스트

### 목표
`grid.json`의 상수 4개로 마디·박 번호를 초(s)로 변환하는 순수 함수 모듈을 만든다.
외부 의존성 없음. pytest만으로 완료 가능.

### 만들 파일
- `src/heartbeat/grid.py`
- `tests/test_heartbeat.py` (Phase 1 테스트 포함)

### `grid.py` API

```python
from pathlib import Path
import json

GRID = json.loads((Path(__file__).with_name("grid.json")).read_text())

BPM:            float = GRID["bpm"]           # 135.0
FIRST_DOWNBEAT: float = GRID["first_downbeat"] # 0.422 s
BEAT_PERIOD:    float = 60.0 / BPM            # 0.44444 s
BAR_PERIOD:     float = BEAT_PERIOD * GRID["beats_per_bar"]  # 1.77778 s
BARS:           int   = GRID["bars"]          # 45
END:            float = FIRST_DOWNBEAT + BARS * BAR_PERIOD   # 80.422 s

def bar_beat_to_time(bar: int, beat: float = 0.0) -> float:
    """마디 k(1-indexed), 박 오프셋(0.0 = 마디 첫 박) → 음원 시각(s)
    beat=0.0  → 마디 첫 박
    beat=1.0  → 두 번째 박
    beat=0.5  → 8분음표 오프셋
    """
    ...

def time_to_bar_beat(t: float) -> tuple[int, float]:
    """음원 시각 → (마디 번호 1-indexed, 박 오프셋 0~4)"""
    ...

def snap_to_grid(t: float, subdivisions: int = 1) -> float:
    """t를 가장 가까운 박 격자(subdivisions=1: 4분음표, 2: 8분음표)에 스냅"""
    ...
```

### 단위 테스트 (`tests/test_heartbeat.py` Phase 1 부분)

```python
# 마디 1 시작 = first_downbeat
assert bar_beat_to_time(1, 0.0) == pytest.approx(0.422)
# 마디 2 시작 = 0.422 + 1.77778
assert bar_beat_to_time(2, 0.0) == pytest.approx(2.200, abs=1e-3)
# 마디 45 끝 = 80.422
assert bar_beat_to_time(46, 0.0) == pytest.approx(80.422, abs=1e-3)
# 왕복 변환
for bar in (1, 10, 45):
    b, beat = time_to_bar_beat(bar_beat_to_time(bar))
    assert b == bar and beat == pytest.approx(0.0, abs=1e-9)
# 스냅
t = bar_beat_to_time(3, 0.3)   # 박 격자 사이
assert snap_to_grid(t, 1) in (bar_beat_to_time(3,0), bar_beat_to_time(3,1))
```

### 완료 기준
- `pytest tests/test_heartbeat.py -k phase1` 통과
- 헤드리스 출력: `python src/heartbeat/grid.py` 실행 시 마디 1~45 시각 출력

---

## Phase 2 — `motions.json` + `choreo.py`

### 목표
동작 A~E를 관절 키프레임으로 정의하고, `choreo(t)` 순수 함수가 7관절 목표 각도를 반환한다.

### 전제
동작 A~E 표가 채워져 있어야 한다 (`brainstorming.md` 5장).
표가 없으면 임시 플레이스홀더(A=가벼운 j2 까딱임, E=정지)로 시작 가능.

### 만들 파일
- `src/heartbeat/motions.json`
- `src/heartbeat/choreo.py`
- `tests/test_heartbeat.py` (Phase 2 테스트 추가)

### `motions.json` 형식

키프레임의 `q` 값은 **0~1 정규화 오므림량** (0 = 완전히 펼침, 1 = `Q_CLOSE` 최대).
`A_j0`만 rad(-1.0472 ~ +1.0472).
적지 않은 관절은 이전 자세 유지.

```json
{
  "A": {
    "label": "가벼운 까딱임",
    "beats": 4,
    "keyframes": [
      { "beat": 0, "q": { "B_j2": 0.0, "C_j2": 0.0 }, "ease": "linear" },
      { "beat": 2, "q": { "B_j2": 0.4, "C_j2": 0.4 }, "ease": "out" },
      { "beat": 4, "q": { "B_j2": 0.0, "C_j2": 0.0 }, "ease": "out" }
    ]
  },
  "E": {
    "label": "정지",
    "beats": 4,
    "keyframes": [
      { "beat": 0, "q": { "A_j0": 0.0, "A_j1": 0.0, "A_j2": 0.0,
                          "B_j1": 0.0, "B_j2": 0.0,
                          "C_j1": 0.0, "C_j2": 0.0 }, "ease": "out" }
    ]
  }
}
```

**속도 제약 자동 검증 (`beat` 값으로)**:
인접 키프레임 `beat_i → beat_{i+1}` 사이 Δt = `(beat_{i+1} - beat_i) × BEAT_PERIOD`.
최대 Δq = 1.2 rad(j2 전체). 3.0 rad/s 제한 → Δt ≥ 0.4 s → **2박(0.888s) 이상 간격** 필요.

### `choreo.py` API

```python
def choreo(t: float) -> dict[str, float]:
    """음원 시각 t(s) → 7관절 목표 각도(rad).
    - CLOSE_SIGN과 Q_CLOSE는 src/run_sim.py에서 import
    - 0~1 정규화값 → rad 변환: CLOSE_SIGN[f] * Q_CLOSE[j] * norm
    - ease="out": cubic ease-out 보간 (도착 감속)
    - t가 END를 넘으면 마지막 자세 유지
    """
    ...
```

내부 구조:
1. `time_to_bar_beat(t)` → 현재 마디, 박 오프셋
2. `schedule.get_motion(bar)` → 현재 동작 ID
3. 동작의 키프레임에서 박 오프셋에 해당하는 보간값 계산
4. 정규화값 → rad 변환 (CLOSE_SIGN, Q_CLOSE 적용)
5. `dict[joint_name → rad]` 반환 (7개 전부)

### `schedule.py`는 Phase 3에서 만들지만, Phase 2에서는 단일 동작으로 테스트

```python
# Phase 2 임시: 항상 동작 A 반환
def get_motion(bar: int) -> str:
    return "A"
```

### 단위 테스트

```python
# 7관절 전부 반환
q = choreo(bar_beat_to_time(1, 0.0))
assert set(q.keys()) == {"A_j0", "A_j1", "A_j2", "B_j1", "B_j2", "C_j1", "C_j2"}

# 안전 범위 내
from src.motors import safe_range
for name, val in q.items():
    lo, hi = safe_range(name)
    assert lo <= val <= hi

# beat=0 키프레임 값이 정확히 반환됨
t_beat0 = bar_beat_to_time(3, 0.0)
q0 = choreo(t_beat0)
assert q0["B_j2"] == pytest.approx(0.0, abs=1e-6)  # A 동작 beat=0 시 펼침

# beat=2 값이 정확히 반환됨
t_beat2 = bar_beat_to_time(3, 2.0)
q2 = choreo(t_beat2)
assert q2["B_j2"] == pytest.approx(CLOSE_SIGN["B"] * Q_CLOSE["j2"] * 0.4, abs=1e-4)
```

### 완료 기준
- `pytest tests/test_heartbeat.py -k phase2` 통과
- 헤드리스 출력: `python -c "from src.heartbeat.choreo import choreo; [print(f'{t:.2f}s', choreo(t)) for t in [0.422, 1.311, 2.200]]"`

---

## Phase 3 — `schedule.py` 구간 표 적용

### 목표
`schedule.json`의 구간 표와 규칙으로 45마디 시간표를 생성하고,
전체 시간표를 검증 규칙 5개 모두 통과시킨다.

### 만들 파일
- `src/heartbeat/schedule.json`
- `src/heartbeat/schedule.py` (Phase 2의 임시 버전을 교체)
- `src/heartbeat/validate.py`
- `tests/test_heartbeat.py` (Phase 3 테스트 추가)

### `schedule.json` 형식

```json
{
  "sections": [
    { "bars": [1,  8],  "motion": "A" },
    { "bars": [9,  26], "motion": "B", "fill": { "every": 4, "motion": "C" } },
    { "bars": [27, 39], "motion": "D" },
    { "bars": [40, 45], "motion": "E" }
  ],
  "rules": {
    "accent_first_beat_scale": 1.15,
    "neutral_after_end": true
  }
}
```

- `fill.every`: N마디마다 fill 동작으로 교체
- `accent_first_beat_scale`: 마디 첫 박의 진폭 배율 (1.0 = 변화 없음)
- `neutral_after_end`: END 이후 모든 관절 0으로 복귀

### `schedule.py` API

```python
def build_schedule() -> list[dict]:
    """45마디 × {bar, motion_id, accent_scale} 목록 반환.
    같은 입력이면 항상 같은 결과 (난수 없음).
    """
    ...

def get_motion(bar: int) -> tuple[str, float]:
    """bar번 마디의 (동작ID, 악센트 배율) 반환. bar는 1-indexed."""
    ...
```

### `validate.py` 검증 규칙

실행 전 `validate_all()` 한 번 호출. 위반 시 `ValidationError` 발생하고 어느 마디·관절인지 출력.

```python
MAX_SPEED = 3.0  # rad/s (AGENTS.md)

def validate_all() -> None:
    """5가지 규칙 전부 검사. 위반 시 ValidationError."""
    check_safe_range()     # 1. 안전 범위
    check_speed_limit()    # 2. 속도 상한
    check_grid_alignment() # 3. 도착 시각 격자 정렬
    check_duration()       # 4. 시간표 길이
    # 5번(자가 충돌)은 Phase 4 헤드리스 실행에서 확인
```

**규칙별 구현 메모**

1. **안전 범위**: `motors.safe_range(name)` 재사용. lo ≤ q ≤ hi.
2. **속도 상한**: 인접 키프레임 `(q1, t1) → (q2, t2)` 에서 `|q2−q1| / (t2−t1) ≤ 3.0`.
   - `t`는 `bar_beat_to_time(bar, beat)` 으로 계산.
3. **격자 정렬**: 키프레임의 `beat` 값이 0.5의 배수인지 확인 (8분음표 단위).
4. **시간표 길이**: 마지막 키프레임 시각 ≤ `END`.

### 단위 테스트

```python
# 스케줄 생성
sched = build_schedule()
assert len(sched) == 45
assert sched[0]["bar"] == 1
assert sched[-1]["bar"] == 45

# 구간 배정 확인
assert get_motion(1)[0]  == "A"
assert get_motion(26)[0] == "B"
assert get_motion(27)[0] == "D"
assert get_motion(45)[0] == "E"

# fill 규칙: 9, 13, 17, 21, 25번 마디는 C
for bar in (9+3, 9+7, 9+11, 9+15):   # 4마디마다: 12,16,20,24
    assert get_motion(bar)[0] == "C"

# 검증 통과
validate_all()   # 예외 없이 통과하면 OK
```

### 완료 기준
- `pytest tests/test_heartbeat.py -k phase3` 통과
- `validate_all()` 예외 없이 통과
- 헤드리스 출력: `python -m src.heartbeat.schedule` 실행 시 45마디 표 출력

---

## Phase 4 — 헤드리스 전구간 시뮬레이션

### 목표
MuJoCo에서 음원·GUI 없이 45마디(80.4s) 전 구간을 빠르게 시뮬레이션해
발산·자가 충돌 없음을 확인하고, 추종 지연 `LEAD`를 측정한다.

### 수정할 파일
- `src/heartbeat/play.py` — `--headless` 모드 구현
- `src/run_sim.py` — `apply_ctrl`을 `choreo(t)` 기반으로 교체 (기존 코사인 루프 대체)

### `play.py --headless` 동작

```
python src/heartbeat/play.py --headless
```

1. `validate_all()` 실행 → 위반 시 중단
2. MuJoCo 모델 로드 (`scene.xml`)
3. 실시간 페이싱 없이 **가상 시간**으로 빠르게 스텝 진행
4. 매 스텝: `apply_ctrl(model, data, choreo(data.time + LEAD))`
5. 1마디마다 콘솔 출력:
   ```
   bar  1 ( 0.42s): A  contacts=0  max|qerr|=0.023rad  max|qvel|=1.21 rad/s
   bar  2 ( 2.20s): A  contacts=0  max|qerr|=0.019rad  ...
   ```
6. 완료 후 통계 출력 (최대 추종 오차, 최대 접촉 수, 최대 관절 속도)

### `apply_ctrl` 교체

기존 `run_sim.py`의 코사인 루프 대신 `choreo(t)`를 쓰도록 교체.
기존 함수는 남겨두되 `heartbeat_ctrl`로 분리.

```python
# src/run_sim.py 에 추가
def heartbeat_ctrl(model, data, t: float, lead: float = 0.0) -> None:
    from src.heartbeat.choreo import choreo
    for joint_name, q_des in choreo(t + lead).items():
        data.ctrl[model.actuator(f"{joint_name}_act").id] = q_des
```

### `LEAD` 측정 방법

1. `LEAD=0`으로 헤드리스 실행
2. 각 박 시각 `t_beat`에서 `|q_actual − q_target|` 기록
3. 출력된 추종 오차가 0.05 rad 초과 시 `LEAD` 값을 높임 (권장 시작값: 0.05s)
4. `LEAD`를 `play.py` 상단 상수로 고정

### 자가 충돌 검사

`contacts > 0`이 바닥(`floor`) 외에서 발생하면 해당 마디·동작을 출력하고 중단.

```python
# 바닥 접촉만 허용
floor_id = model.geom("floor").id
bad = [c for c in data.contact[:data.ncon]
       if floor_id not in (c.geom1, c.geom2)]
if bad:
    raise RuntimeError(f"self-collision at t={data.time:.3f}s bar={bar}")
```

### 완료 기준
- 45마디 전 구간 수치 발산 없음 (`assert np.isfinite(data.qpos).all()`)
- 바닥 외 접촉 0
- 최대 관절 속도 < 3.0 rad/s
- `LEAD` 값 확정 후 `play.py` 상수로 기재

---

## Phase 5 — `play.py` 음원 + MuJoCo 뷰어

### 목표
음원 재생과 MuJoCo 뷰어를 동기화해 눈·귀로 박자 일치를 확인한다.
`AUDIO_OFFSET`을 측정해 보정한다.

### 만들 파일 / 수정할 파일
- `src/heartbeat/play.py` — `--viewer` 모드 완성
- `src/heartbeat/audio.py` — sounddevice 래퍼

### 마스터 클럭 설계

```python
# audio.py
import sounddevice as sd, soundfile as sf, numpy as np

class AudioClock:
    """재생된 샘플 수를 마스터 클럭으로 사용."""

    def __init__(self, path: str, offset: float = 0.0):
        self.data, self.sr = sf.read(path, dtype="float32")
        self.offset = offset          # AUDIO_OFFSET (s)
        self._played = 0

    def start(self):
        self._stream = sd.OutputStream(
            samplerate=self.sr, channels=self.data.shape[1],
            callback=self._cb, latency="low"
        )
        self._stream.start()
        self._latency = self._stream.latency   # 측정값 보정

    def _cb(self, outdata, frames, time_info, status):
        chunk = self.data[self._played : self._played + frames]
        outdata[:len(chunk)] = chunk
        outdata[len(chunk):] = 0
        self._played += frames

    @property
    def t(self) -> float:
        """현재 음원 시각(s). 재생 완료 샘플 기준."""
        return self._played / self.sr - self._latency + self.offset

    def stop(self):
        self._stream.stop(); self._stream.close()
```

### `play.py --viewer` 루프

```
python src/heartbeat/play.py --viewer
```

1. `validate_all()`
2. `AudioClock("docs/heartbeat/Heartbeat.mp3").start()`
3. MuJoCo 뷰어 열기
4. 루프: `clock.t`를 기준으로 시뮬레이션 스텝 따라잡기

```python
while viewer.is_running():
    t_now = clock.t
    # 현재 t_now에 해당하는 스텝 수까지 따라잡기
    target_steps = int(t_now / model.opt.timestep)
    while data.time / model.opt.timestep < target_steps:
        heartbeat_ctrl(model, data, t_now, lead=LEAD)
        mujoco.mj_step(model, data)
    viewer.sync()
    if t_now >= END:
        break
```

5. `END` 도달 시 음원 페이드아웃(0.5s), 로봇 중립 복귀

### `AUDIO_OFFSET` 보정 방법

1. `AUDIO_OFFSET = 0.0`으로 실행
2. 뷰어에서 마디 1 첫 박에 손가락이 도착하는 시각과 음원 클릭이 들리는 시각의 차이를 귀로 판단
3. 손이 **늦으면** `AUDIO_OFFSET` 음수로 (음원을 앞으로), 손이 **빠르면** 양수로
4. 권장 측정: 마디 1, 10, 27, 45 각각 확인

### 완료 기준
- 마디 1, 27, 45에서 눈·귀로 박자 일치
- `AUDIO_OFFSET` 값 확정 후 `play.py` 상수로 기재
- 45마디 종료 후 음원 중지, 로봇 중립 자세 복귀

---

## Phase 6 — 실물 이식

### 목표
같은 `choreo(t)` + `schedule.py`로 실물 Dynamixel 손을 구동한다.
MuJoCo와 같은 시간표, 다른 `LEAD` 값.

### 수정할 파일
- `src/heartbeat/play.py` — `--motors` 모드 추가
- `src/motors.py` — 기존 `HandMotors.send` 재사용

### `play.py --motors` 루프

```
python src/heartbeat/play.py --motors --port COM3
```

1. `validate_all()`
2. `HandMotors` 로드 (`motors.py`의 `load()`)
3. `AudioClock` 시작
4. 루프: 박 경계마다 Time-based Profile + Sync Write

```python
next_beat = bar_beat_to_time(1, 0.0)
while clock.t < END:
    t_now = clock.t
    if t_now >= next_beat - MOTORS_LEAD:
        q = choreo(next_beat)                       # 도착 시각 기준 목표
        dt_ms = int((next_beat - t_now) * 1000)     # 남은 시간 (ms)
        hand.send(q, profile_time_ms=dt_ms)         # Time-based Profile
        next_beat += BEAT_PERIOD                    # 다음 박으로
    time.sleep(0.001)  # 1ms 폴링
```

### `HandMotors.send` 확장

기존 `send(targets: dict[str, float])`에 `profile_time_ms` 파라미터 추가.

```python
def send(self, targets: dict[str, float], profile_time_ms: int = 200) -> None:
    """PROFILE_VELOCITY를 time-based로 설정 후 GOAL_POSITION Sync Write."""
    ...
```

### 지터 측정 방법

1. `--motors` 모드로 실행하며 명령 전송 시각과 실제 도달 시각을 로그
2. `PRESENT_POSITION` 폴링으로 도달 시각 추정
3. 지터(명령~도달 표준편차) > 20 ms이면 `MOTORS_LEAD` 조정

### `MOTORS_LEAD` vs `LEAD`

| 상수 | 용도 | 위치 |
|---|---|---|
| `LEAD` | MuJoCo 추종 오차 보정 | Phase 4 측정, `play.py` 상단 |
| `MOTORS_LEAD` | 실물 Dynamixel 전송 선행 시간 | Phase 6 측정, `play.py` 상단 |
| `AUDIO_OFFSET` | 음원 재생 지연 보정 | Phase 5 측정, `play.py` 상단 |

### 완료 기준
- 실물에서 45마디 지속 동작 (탈조·하드웨어 오류 없음)
- 지터 < 20 ms (Sync Write 기준)
- MuJoCo 뷰어와 실물을 나란히 두었을 때 동작이 눈으로 맞음

---

## 의존 관계 요약

```
Phase 0 (grid.json) ──┐
                       ▼
Phase 1 (grid.py)  ────┐
                        ▼
Phase 2 (choreo.py) ───┐  ← motions.json (동작 A~E 표 필요)
                        ▼
Phase 3 (schedule.py) ─┐  ← schedule.json (구간 표 필요)
                        ▼
Phase 4 (헤드리스) ────┐  ← LEAD 확정
                        ▼
Phase 5 (음원+뷰어) ───┐  ← AUDIO_OFFSET 확정
                        ▼
Phase 6 (실물) ─────────  ← MOTORS_LEAD 확정
```

Phase 1~4는 음원·GUI·실물 없이 완료 가능.
Phase 2는 동작 A~E 표가 없으면 임시 플레이스홀더(A=j2 까딱임, E=정지)로 시작 가능.

---

## 상수 목록 (구현하면서 채울 것)

| 상수 | 파일 | 확정 시점 | 값 |
|---|---|---|---|
| `LEAD` | `play.py` | Phase 4 ✅ | **0.050 s** (0~0.13 s 스윕, 추종 오차 0.027 rad 최소점) |
| `AUDIO_OFFSET` | `play.py` | Phase 5 ✅ | **0.0 s** (장치 지연은 `outputBufferDacTime`이 보정. 귀로 재조정하는 값) |
| `VIDEO_OFFSET` | `play.py` | Phase 2 ✅ | **0.966 s** (`mp3_t = video_t + 0.966`. 문서용, 재생에는 미사용) |
| `MOTORS_LEAD` | `play.py` | Phase 6 | 미정 |
