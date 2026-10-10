# tri_hand: 비트 동기화 안무 (Heartbeat)

3지 다관절 로봇 손(`tri_hand`)이 **음원 박자에 맞춰 미리 정의된 안무를 재생**하는 프로젝트입니다.

이전 Sim-to-Real 텔레오퍼레이션 프로젝트의 **MuJoCo 기구학/동역학 모델(`hand.xml`, `scene.xml`)과 실물 Dynamixel 모터 드라이버(`motors.py`)를 재사용**하되, 목표는 완전히 다릅니다 — 카메라나 실시간 입력 없이, 노래 **"Heartbeat"**(2PM, 135 BPM)의 안무를 분석해 **규칙 기반 시간표**로 미리 계산하고, 오디오 재생 위치 하나만을 마스터 클럭으로 삼아 로봇 손이 박자에 맞춰 움직이도록 합니다.

| MuJoCo 시뮬레이션 (안무 재생) |
| :---: |
| <img src="docs/mujoco.gif" alt="tri_hand MuJoCo 시뮬레이션 데모" width="100%"> |

> 안무의 원본은 [`docs/heartbeat/heartbeat.mp4`](docs/heartbeat/heartbeat.mp4)(0~33초 구간)이며, 영상은 **실행 시에는 전혀 쓰이지 않습니다.** 영상을 사람이 관찰해 `motions.json`/`schedule.json`에 손 동작으로 옮겨 적었고, 재생은 오직 `grid.json`의 비트 격자 수식으로만 이뤄집니다. 근거는 [docs/heartbeat/choreography.md](docs/heartbeat/choreography.md) 참조.

---

## 📋 목차

1. [프로젝트 아키텍처](#-프로젝트-아키텍처)
2. [핵심 기능](#-핵심-기능-key-features)
3. [빠른 시작](#-빠른-시작-quick-start)
4. [비트 동기화 재생 (`heartbeat/play.py`)](#-비트-동기화-재생-heartbeatplaypy)
5. [안무 커스터마이징](#-안무-커스터마이징)
6. [환경 세팅 (Setup)](#-환경-세팅-setup)
7. [실물 로봇 손 연동 (`motors.py`)](#-실물-로봇-손-연동-motorspy)
8. [기구학 및 하드웨어 사양](#️-기구학-및-하드웨어-사양-kinematics-specs)
9. [프로젝트 구조](#-프로젝트-구조)
10. [테스트 실행](#-테스트-실행)

---

## 🏛 프로젝트 아키텍처

모든 안무는 음원 시각 `t`(초)를 입력받아 7관절 목표 각도(rad)를 반환하는 **순수 함수 `choreo(t)`** 하나로 귀결됩니다. 상태를 누적하지 않으므로, 마스터 클럭(오디오 재생 위치)만 정확하면 시간이 아무리 지나도 오차가 쌓이지 않습니다.

```
grid.json (BPM·첫 박·마디 수)
   │
   ▼
grid.py          마디·박 ↔ 음원 시각(s) 변환 (순수 함수)
   │
   ▼
schedule.json    마디 구간별 동작 배정 표
schedule.py      구간 표 → 전역 타임라인(절대 시각 키프레임) 생성
   │
   ▼
motions.json     동작 A~E 키프레임 정의 (정규화 오므림량 0~1)
choreo.py        choreo(t) → 7관절 목표 각도(rad)   ★ Sim/실물 공용 순수 함수
   │
   ├─▶ validate.py   재생 전 안전 범위·속도 상한·격자 정렬·길이 자동 검증
   │
   ▼
play.py          AudioClock(재생 샘플 수 기준)을 마스터 클럭으로 MuJoCo 뷰어 구동
   │
   ├─▶ MuJoCo (run_sim.py의 scene.xml / hand.xml)   ← 현재 구현 범위
   └─▶ motors.py (실물 Dynamixel)                    ← Phase 6, 미착수
```

---

## ✨ 핵심 기능 (Key Features)

* **규칙 기반 시간표 (Time-scheduled)**
  - 실시간 오디오 반응·카메라 비전 추정을 쓰지 않습니다. `grid.json` 상수 4개(BPM, 첫 박, 박자 수, 마디 수)만으로 전체 재생 시각을 수식으로 계산합니다.
  - 동작의 **도착 시점**을 비트(8분음표)에 맞추는 것을 원칙으로, `schedule.json`의 구간 표를 하나의 전역 키프레임 타임라인으로 펼칩니다.
* **오디오 클럭 동기화 (`heartbeat/audio.py`)**
  - PortAudio 콜백이 알려주는 `outputBufferDacTime`(버퍼가 실제 스피커로 나가는 시각) 기준으로 "지금 귀에 들리는 음원 위치"를 추정 — 장치 출력 지연이 자동 보정됩니다.
  - 측정값: 12초 재생 동안 벽시계 대비 편차 0.2 ms, 시뮬-클럭 어긋남 최대 2 ms.
* **자동 안전성 검증 (`heartbeat/validate.py`)**
  - 모든 목표 각도가 안전 범위(`motors.safe_range`) 내인지, 인접 키프레임 간 **순간 최대 속도**가 3.0 rad/s를 넘지 않는지(보간 곡선별 피크 배율 반영), 도착 시각이 8분음표 격자에 정렬되는지, 시간표 길이가 음원을 넘지 않는지를 `play.py` 실행 전 자동 검사합니다.
  - **프리롤 구간**(음원 전 이동)도 조립 자세에서 첫 키프레임까지 속도 상한 안에 드는지 따로 검사합니다(`check_preroll`). 비트 격자 밖이라 시간표 검사가 닿지 않는 구간입니다.
  - 자가 충돌(규칙 5)은 `--headless` 전구간 시뮬레이션에서 바닥 외 접촉을 감지해 확인합니다.
* **MuJoCo ↔ 실물 공용 로직**
  - `choreo(t)`는 시뮬레이션과 실물 어느 쪽에서도 똑같이 쓰도록 설계되어 있습니다(Phase 6에서 `motors.py`와 연결 예정).

---

## 🚀 빠른 시작 (Quick Start)

```bash
# 1) 음원 + MuJoCo 뷰어로 재생 (기본). 스피커에서 음악이 나오고 손이 박자에 맞춰 움직입니다
python src/heartbeat/play.py

# 2) 음원·GUI 없이 전구간(45마디) 수치 검증 — 발산/자가 충돌/추종 오차를 수 초 내 확인
python src/heartbeat/play.py --headless

# 3) 오디오 장치가 없을 때: 뷰어만, 실시간 클럭으로 대체
python src/heartbeat/play.py --mute
```

> macOS GUI 뷰어는 `mjpython`을 써야 합니다. **음원 출력·뷰어·실물 모터는 윈도우 네이티브 환경을 권장**합니다(WSL2는 디스플레이/오디오 드라이버 이슈로 `--headless` 권장).

재생 구간은 안무를 분석한 **마디 1~19(음원 0.42~34.20 s)** 입니다. 마디 20~45는 영상 33초 이후 분석이 아직 없어 `schedule.json`에 비어 있으며, 구간만 추가하면 그대로 늘어납니다.

독립적인 관절 데모가 필요하면 안무 없이 코사인 궤적으로 오므리고 펴는 `run_sim.py`를 쓸 수 있습니다.

```bash
python src/run_sim.py              # 뷰어 (macOS: mjpython src/run_sim.py)
python src/run_sim.py --headless   # 수치만 확인 (WSL2/서버 등)
```

---

## 🎵 비트 동기화 재생 (`heartbeat/play.py`)

### 동기화 구조
0. **프리롤 — 음원을 틀기 전에 첫 자세를 먼저 완성합니다.** 첫 키프레임은 손가락이 바깥으로 완전히 누운 자세(손바닥쪽 `j1` 1.2 rad)라 조립 자세(0 rad)와 멉니다. 음원과 동시에 출발시키면 제어기가 첫 마디 내내 자세를 쫓느라 크게 튀고, 실물에서는 그 튐이 모터 급가속이 됩니다. 그래서 비트 격자 **바깥에서** 누운 자세로 천천히 옮기고(smoothstep) 안정화를 기다린 뒤, 그다음에 `clock.start()`로 음원을 시작합니다. 격자 밖이라 길이는 연출에 영향이 없고, 길수록 관절 속도가 낮아 안전합니다.
1. **마스터 클럭은 오디오 스트림 하나뿐**입니다(`AudioClock.t`). 재생된 샘플 수와 DAC 콜백 시각으로 "지금 귀에 들리는 음원 위치"를 계산합니다.
2. 목표 자세는 전부 `choreo(t)`로 계산합니다. 누적되는 상태가 없어 **오차가 쌓이지 않습니다.**
3. 물리 스텝이 클럭을 따라갑니다(catch-up). 0.25 s 넘게 밀리면 스텝으로 메우지 않고 시각을 바로 맞춥니다.

### 보정 상수 (`play.py` 상단)

| 상수 | 값 | 의미 / 언제 바꾸나 |
|---|---|---|
| `LEAD` | 0.050 s | 위치 제어기(kp=12, kv=0.5) 추종 지연 보정. `--headless` 추종 오차가 0.05 rad 넘을 때 `--lead`로 재탐색 |
| `AUDIO_OFFSET` | 0.0 s | **귀로 맞추는 값.** 손이 음악보다 늦으면 음수, 빠르면 양수. `--offset` 옵션 |
| `VIDEO_OFFSET` | 0.966 s | 영상↔음원 상호상관으로 측정(문서/주석용, 재생에는 미사용) |

### 프리롤 설정 (`schedule.json` → `rules`)

| 키 | 의미 / 언제 바꾸나 |
|---|---|
| `preroll_seconds` | 조립 자세 → 첫 키프레임(누운 자세) 이동 시간. 줄이면 대기가 짧아지지만 관절 속도가 올라갑니다. 너무 짧으면 `validate.check_preroll`이 필요한 최소값을 찍고 중단합니다 |
| `preroll_settle_seconds` | 도착 후 목표를 유지하며 제어기가 중력 처짐까지 잡는 시간. 음원 시작 시점의 도착 오차를 줄입니다 |

뷰어 실행 시에는 프리롤이 화면에 보이므로, 관객(과 실물 옆의 사람)이 손이 자리를 잡는 것을 확인한 뒤 음악이 시작됩니다. `--headless`도 같은 프리롤을 거친 뒤 전구간을 돌리며, 구간에서 관측된 최대 관절 속도와 도착 오차를 출력합니다.

```bash
# LEAD를 바꿔 가며 추종 오차 비교
python src/heartbeat/play.py --headless --lead 0.08

# 손이 반 박(222 ms) 늦게 보일 때
python src/heartbeat/play.py --offset -0.10
```

### 모션/시간표 점검

```bash
# 45마디 격자 시각 출력
python src/heartbeat/grid.py

# 마디별 배정 동작 표 + 전체 키프레임 수
python src/heartbeat/schedule.py

# choreo(t) 미리보기 (마디 1~20, 각 박 0·2에서의 7관절 각도)
python src/heartbeat/choreo.py

# 안전 범위·속도 상한·격자 정렬·길이 검증 (play.py가 실행 전 자동 호출)
python src/heartbeat/validate.py
```

---

## 🎛 안무 커스터마이징

- **`src/heartbeat/motions.json`** — 동작별 키프레임. `q`는 **−1~+1 정규화 오므림량**으로, **`0`이 곧게 편 자세**(가동 범위의 끝이 아니라 가운데), `+1`이 오므림 끝(`Q_CLOSE`), `−1`이 바깥으로 누운 끝(`Q_OPEN`)입니다. `A_j0`만 처음부터 rad. 키프레임에 적지 않은 관절은 직전 값을 유지합니다.
  - 곡 전반(`still`·`veil`)이 "바닥에 누움"이라 첫 키프레임이 `−1.0`(누움)입니다. 이 때문에 음원 전 프리롤이 필요합니다.
- **`src/heartbeat/schedule.json`** — 어느 마디 구간에 어느 동작을 쓸지(`sections`), 마디 첫 박 악센트 배율(`accent_first_beat_scale`), 복귀에 쓸 박 수(`outro_beats`), 프리롤 시간(`preroll_seconds`, `preroll_settle_seconds`)을 정의합니다.
- 고친 뒤에는 반드시 `validate.py`를 돌려 안전 범위·속도 상한 위반을 **어느 키프레임인지까지** 확인하세요.

> ⚠ 속도 검사는 평균이 아니라 **순간 최대 속도**로 합니다. `ease="out"`은 출발 기울기가 평균의 3배라 8분음표(222 ms) 구간에 쓰면 상한 3.0 rad/s를 넘깁니다. 짧은 구간에는 `inout`을 쓰세요. 자세한 설계 기록은 [docs/heartbeat/choreography.md](docs/heartbeat/choreography.md) 4장 참조.

---

## 🛠 환경 세팅 (Setup)

가상환경이 활성화된 상태에서 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

> **주요 설치 패키지 (`requirements.txt`)**:
> - `mujoco==3.3.0`, `numpy`: 물리 엔진 및 행렬 연산
> - `dynamixel-sdk`: 실물 Dynamixel 모터 시리얼 통신 (Phase 6용)
> - `sounddevice`, `soundfile`: 오디오 재생 마스터 클럭 및 mp3 디코딩 (ffmpeg 불필요)
>   - *참고 (Linux 환경)*: 음원 출력을 위해 PortAudio 라이브러리가 필요합니다. (`conda install -c conda-forge portaudio` 또는 `sudo apt-get install libportaudio2`). 설치 없이 실행하려면 `--mute` 또는 `--headless` 옵션을 사용합니다.
> - `pytest`: 유닛 테스트

영상/음원에서 안무를 새로 분석하거나 비트 격자를 다시 맞출 때만 추가 의존성(`requirements-analysis.txt`: `librosa`, `matplotlib`, `opencv-python` 등)이 필요합니다. **재생(`play.py`)에는 전혀 필요 없습니다.**

```bash
pip install -r requirements.txt -r requirements-analysis.txt
```

---

## 🤖 실물 로봇 손 연동 (`motors.py`)

`src/motors.py`는 이전 프로젝트에서 쓰던 실물 Dynamixel(XL430-W250-T, Protocol 2.0, 위치 제어) 드라이버를 그대로 재사용합니다. **Heartbeat 재생을 실물로 이식하는 작업(Phase 6)은 아직 미착수**이며, 현재는 캘리브레이션/수동 점검 기능만 제공합니다.

```bash
# 토크를 끈 채로 손으로 관절을 움직여 motors.json 작성
python src/motors.py calibrate --port COM3 --baud 1000000

# 토크 끈 채로 현재 관절 각도(rad)를 실시간 출력 (부호 확인용)
python src/motors.py check --config src/motors.json
```

- 영점/방향 추측 없이 손으로 직접 움직여 기록합니다: `raw(틱) = zero + sign × q(rad) × 4096/2π`.
- 목표는 항상 안전 범위(`safe_range`: 바깥쪽 `Q_OPEN` ~ 오므림 `Q_CLOSE`, `A_j0`는 ±`YAW_LIMIT`)로 잘라서 전송되고, 이동 속도는 Profile Velocity로 3.0 rad/s 이하로 제한됩니다.
- 모터 보레이트를 모를 때는 `calibrate`가 전 보레이트(57600~4000000)를 자동 스캔합니다.
- 향후 `play.py --motors` 추가 시 박 경계마다 `choreo(next_beat)`를 Time-based Profile로 Sync Write하는 방식이 계획되어 있습니다(`MOTORS_LEAD` 상수 측정 필요). 자세한 계획은 [docs/heartbeat/implementation-plan.md](docs/heartbeat/implementation-plan.md) Phase 6 참조.

---

## ⚙️ 기구학 및 하드웨어 사양 (Kinematics Specs)

* **서보 모터**: Robotis Dynamixel XL430-W250-T (7 DOF)
* **최대 토크**: `1.4 N·m` (`forcerange="-1.4 1.4"`)
* **좌표계 및 중력축**:
  - 중력 방향: **`-Y` 축** (`gravity="0 -9.81 0"`)
  - 관절 회전축: **`+X` 축** (`axis="1 0 0"`)
* **오므림(Grasp/Close) 회전 부호 규칙**:
  - **Finger A (상단 3자유도)**: 음수(`-`) 방향 회전이 오므림
  - **Finger B, C (하단 2자유도)**: 양수(`+`) 방향 회전이 오므림
* **안전 가동 범위**: 곧게 편 자세(`0 rad`)가 범위의 **가운데**이며, 오므림과 눕힘 양방향으로 열려 있습니다. 부호는 `CLOSE_SIGN`을 따릅니다.
  - 오므림 쪽 `Q_CLOSE` (손가락 간 간섭이 정함): `j1` 0.3 rad, `j2` 1.2 rad
  - 바깥쪽 `Q_OPEN` (실물 기구 정지점이 정함): `j1` 1.2 rad, `j2` 0.3 rad — 오므림과 배분이 반대이며,
    누운 자세는 손바닥쪽 관절(`j1`)에서 꺾이고 끝 마디(`j2`)는 그 연장선으로 거의 곧게 뻗습니다
  - `A_j0`(엄지 요) ±1.0472 rad, 관절 속도 상한 3.0 rad/s

세부 모델링 원칙(시각/충돌 지오메트리 분리, 자가 충돌 방지 등)은 [AGENTS.md](AGENTS.md)를 참조하세요.

---

## 📁 프로젝트 구조

```
tri_hand/
├── docs/
│   ├── mujoco.gif              # 시뮬레이션 데모
│   ├── execution_guide.md      # 실행 가이드
│   └── heartbeat/
│       ├── Heartbeat.mp3       # 재생 음원
│       ├── heartbeat.mp4       # 안무 분석 원본 영상 (실행에는 미사용)
│       ├── brainstorming.md    # 배경·제약 정리
│       ├── choreography.md     # 영상 분석 → 모션 매핑 근거
│       └── implementation-plan.md  # Phase별 구현 계획
├── src/
│   ├── scene.xml / hand.xml    # MuJoCo 기구학/동역학 모델
│   ├── meshes/                 # 3D STL 메쉬 파일
│   ├── run_sim.py              # 독립 시뮬레이션 데모 (코사인 궤적)
│   ├── motors.py / motors.json # 실물 Dynamixel 드라이버 및 캘리브레이션 설정
│   └── heartbeat/
│       ├── grid.json / grid.py       # 비트 격자 상수 및 시각 변환
│       ├── motions.json / choreo.py  # 동작 키프레임 정의 및 choreo(t)
│       ├── schedule.json / schedule.py  # 구간 표 및 전역 타임라인
│       ├── validate.py         # 재생 전 안전성 자동 검증
│       ├── audio.py            # 오디오 마스터 클럭 (AudioClock / SilentClock)
│       └── play.py             # 재생 진입점
├── tests/                      # pytest 유닛 테스트
├── AGENTS.md                   # 에이전트 작업 지침 및 하드웨어 모델링 원칙
├── requirements.txt            # 재생에 필요한 의존성
├── requirements-analysis.txt   # 안무 분석(영상/음원)에만 필요한 의존성
└── README.md
```

---

## 🧪 테스트 실행

```bash
pytest tests/
```

`tests/test_heartbeat.py`는 음원·GUI·실물 없이 격자 변환, `choreo(t)`, 시간표 검증 규칙을 모두 검사하며, `tests/test_motors.py`는 가짜 시리얼 버스로 Dynamixel 드라이버의 안전 범위/부호 로직을 검사합니다.
