# tri_hand 프로젝트 실행 및 운영 가이드 (Execution Guide)

이 문서는 `tri_hand` 프로젝트의 `src/` 디렉토리에 포함된 모든 실행 스크립트(`run_sim.py`, `server.py`, `motors.py`, `teleop.py`)의 구동 방법, 파이프라인 연계 및 하드웨어 제어 과정을 정리한 종합 가이드입니다.

---

## 📋 목차
1. [사전 준비 및 환경 설정](#1-사전-준비-및-환경-설정)
2. [전체 시스템 아키텍처 및 스크립트 역할](#2-전체-시스템-아키텍처-및-스크립트-역할)
3. [가상 시뮬레이션 실행](#3-가상-시뮬레이션-실행)
   - [3.1 독립 시뮬레이션 데모 (`run_sim.py`)](#31-독립-시뮬레이션-데모-run_simpy)
   - [3.2 HTTP 제어 서버 및 웹 대시보드 (`server.py`)](#32-http-제어-서버-및-웹-대시보드-serverpy)
   - [3.3 음원 동기 비트 연출 (`heartbeat/play.py`)](#33-음원-동기-비트-연출-heartbeatplaypy)
4. [카메라 기반 손 원격 조종 (`teleop.py`)](#4-카메라-기반-손-원격-조종-teleoppy)
   - [4.1 관절 매핑 및 동작 원리](#41-관절-매핑-및-동작-원리)
   - [4.2 시뮬레이션 연동 실행](#42-시뮬레이션-연동-실행)
   - [4.3 주요 실행 옵션](#43-주요-실행-옵션)
5. [실물 모터 연동 및 캘리브레이션 (`motors.py`)](#5-실물-모터-연동-및-캘리브레이션-motorspy)
   - [5.1 하드웨어 준비 및 연결](#51-하드웨어-준비-및-연결)
   - [5.2 관절 캘리브레이션 (`calibrate`)](#52-관절-캘리브레이션-calibrate)
   - [5.3 관절 각도 실시간 검증 (`check`)](#53-관절-각도-실시간-검증-check)
6. [실물 로봇 손 텔레오퍼레이션 (Sim-to-Real)](#6-실물-로봇-손-텔레오퍼레이션-sim-to-real)
7. [자주 묻는 문제 및 문제 해결 (Troubleshooting)](#7-자주-묻는-문제-및-문제-해결-troubleshooting)

---

## 1. 사전 준비 및 환경 설정

### 1.1 Python 가상환경 활성화
본 프로젝트는 **Python 3.10** 가상환경(`~/mujoco_env`) 사용을 표준으로 합니다.

```bash
# 가상환경 활성화
source ~/mujoco_env/bin/activate

# 의존성 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt
```

> **주요 설치 패키지 (`requirements.txt`)**:
> - `mujoco==3.3.0`, `numpy`: 물리 엔진 및 행렬 연산
> - `fastapi`, `uvicorn`: HTTP REST API 및 웹 대시보드 서빙
> - `mediapipe>=0.10.30`, `opencv-contrib-python`: 웹캠 손 랜드마크 추출 및 영상 처리
> - `dynamixel-sdk>=3.7`: 실물 로보티즈 Dynamixel 모터 시리얼 통신

### 1.2 OS별 필수 실행 도구 및 장치 권한
- **macOS**: GUI 뷰어를 띄울 때 OS 이벤트 루프 특성상 `python` 대신 `mjpython`을 사용해야 합니다.
- **Linux (Ubuntu)**:
  - U2D2 시리얼 장치(`/dev/ttyUSB*`) 접근을 위해 다이얼아웃 그룹 권한이 필요합니다:
    ```bash
    sudo usermod -aG dialout $USER
    # 적용 후 로그아웃 후 재로그인 필요
    ```
- **Windows (WSL2)**:
  - WSL2는 디스플레이 드라이버 호환성으로 인해 GUI 뷰어가 멈출 수 있으므로, 기본적으로 `--headless` 모드를 권장합니다.
  - 외부 USB 장치(웹캠, U2D2)를 WSL2에 전달하려면 Windows 파워셸(관리자)에서 `usbipd` 명령을 사용합니다:
    ```powershell
    usbipd list
    usbipd wsl attach --busid <BUSID>
    ```

---

## 2. 전체 시스템 아키텍처 및 스크립트 역할

`src/` 디렉토리의 파일들은 모듈형으로 유기적으로 연결되어 있습니다:

```
[웹캠 / 영상] ──(cv2 / MediaPipe)──> [ teleop.py ]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
          HTTP POST (/joints)                         Serial (Protocol 2.0)
                   │                                           │
                   ▼                                           ▼
       [ server.py ] (포트 8000)                       [ motors.py ]
       ├── MuJoCo 물리 시뮬레이션                        └── U2D2 / XL430 모터 (실물)
       └── dashboard.html (웹 대시보드)
```

| 스크립트 파일 | 역할 | 주요 입출력 |
|---|---|---|
| [`run_sim.py`](file:///home/erdos/workspace/tri-hand/src/run_sim.py) | 단독 시뮬레이션 데모 | MuJoCo 내장 주기적 궤적 생성 → 물리 엔진 구동 |
| [`server.py`](file:///home/erdos/workspace/tri-hand/src/server.py) | HTTP 제어 서버 & 웹 대시보드 | REST API 수신 (`POST /joints`) → 시뮬레이션 반영 |
| [`teleop.py`](file:///home/erdos/workspace/tri-hand/src/teleop.py) | 비전 손 추적 원격 조종 | 웹캠 영상 → 사람 손 관절 각도 계산 → 서버 / 모터 전송 |
| [`motors.py`](file:///home/erdos/workspace/tri-hand/src/motors.py) | 실물 모터 캘리브레이션/제어 | 관절 각도(rad) ↔ 모터 엔코더(tick) 변환 및 U2D2 통신 |

---

## 3. 가상 시뮬레이션 실행

### 3.1 독립 시뮬레이션 데모 (`run_sim.py`)
사전 정의된 주기 함수(코사인 파형)에 따라 손가락 3개와 엄지 요(대립) 관절이 자동으로 오므리고 펴지는 기본 동작을 시뮬레이션합니다.

```bash
# 1) 데스크탑 GUI 환경 (Linux)
python src/run_sim.py

# macOS 환경 (반드시 mjpython 사용)
mjpython src/run_sim.py

# 2) WSL2 / 터미널 헤드리스 환경 (수치 모니터링)
python src/run_sim.py --headless
```

- **헤드리스 모드 출력**: 접촉 수(`contacts`), 엄지 각도(`A_j0`), 관절 최대 속도(`max|qvel|`) 등이 초당 1회 출력되며 수치 발산 여부를 검증합니다.

---

### 3.2 HTTP 제어 서버 및 웹 대시보드 (`server.py`)
외부 제어 명령을 수신할 수 있는 FastAPI 백엔드와 시뮬레이션 실시간 뷰/모니터링 대시보드를 제공합니다.

#### 기본 실행 명령어
```bash
# 로컬 전용 실행 (GUI 뷰어 포함, 기본 포트 8000)
python src/server.py

# 헤드리스 모드 (WSL2 권장)
python src/server.py --headless

# 같은 공유기(LAN)의 다른 기기/태블릿 접속 허용
python src/server.py --headless --host 0.0.0.0 --port 8000
```

#### 웹 대시보드 접속 및 활용
- 브라우저를 열고 `http://127.0.0.1:8000`에 접속합니다.
- **모니터링 항목**: 7개 관절(`A_j0`, `A_j1`, `A_j2`, `B_j1`, `B_j2`, `C_j1`, `C_j2`)의 현재 각도, 목표 각도, 속도, 토크, 게인(kp, kv).
- **프리셋 관리**:
  1. 대시보드 우측에서 원하는 각도와 게인을 설정하고 이름 입력 후 **프리셋 저장** 클릭 (`src/presets.json`에 저장됨).
  2. 드롭다운에서 프리셋 선택 후 **적용**을 누르면 시뮬레이션 관절에 즉시 일괄 반영.

#### 주요 REST API 예시
```bash
# 관절 목표 각도 제어 (일부 관절만 지정 가능)
curl -X POST http://localhost:8000/joints \
  -H "Content-Type: application/json" \
  -d '{"A_j1": -0.3, "B_j1": 0.3, "C_j1": 0.3}'

# 전체 손가락 일괄 파지 (0: 완전 펼침 ~ 1: 완전 오므림)
curl -X POST http://localhost:8000/grasp \
  -H "Content-Type: application/json" \
  -d '{"amount": 0.7}'

# 시뮬레이션 자세 초기화
curl -X POST http://localhost:8000/reset
```

---

### 3.3 음원 동기 비트 연출 (`heartbeat/play.py`)
`docs/heartbeat/Heartbeat.mp3`를 재생하면서, 영상(`heartbeat.mp4`) 0~33초 구간의 안무를 옮긴
모션을 135 BPM 박자에 맞춰 시뮬레이션에서 재생합니다. 재생 범위는 **마디 1~19 (음원 0.42~34.20 s)** 입니다.

안무를 어떻게 읽어 모션으로 옮겼는지는 [heartbeat/choreography.md](heartbeat/choreography.md) 참조.

#### 기본 실행 명령어
```bash
# 1) 음원 + 뷰어 (기본). 스피커에서 음악이 나오고 손이 박자에 맞춰 움직입니다
.\.venv\Scripts\python.exe src\heartbeat\play.py

# 2) 음원·GUI 없이 전구간 수치 검증 (빠름, 수 초)
.\.venv\Scripts\python.exe src\heartbeat\play.py --headless

# 3) 오디오 장치가 없을 때 뷰어만 (실시간 클럭으로 대체)
.\.venv\Scripts\python.exe src\heartbeat\play.py --mute
```

> macOS는 GUI 뷰어에 `mjpython`을 써야 합니다. 음원 출력·뷰어·실물 모터는 **윈도우 네이티브** 환경을 권장합니다(WSL2 아님).

#### 동기화 구조
1. **마스터 클럭은 오디오 스트림 하나뿐**입니다. PortAudio가 콜백마다 알려주는 `outputBufferDacTime`
   (그 버퍼가 스피커로 나가는 시각)으로 "지금 귀에 들리는 음원 위치"를 계산합니다.
   출력 장치 지연(MME 기준 91 ms)이 여기서 자동으로 보정됩니다.
2. 목표 자세는 전부 `choreo(t)`로 계산합니다. 누적되는 상태가 없어 **오차가 쌓이지 않습니다.**
3. 물리 스텝이 클럭을 따라갑니다. 0.25 s 넘게 밀리면 스텝으로 메우지 않고 시각을 바로 맞춥니다.

측정값: 12초 재생 동안 오디오 클럭의 벽시계 대비 편차 **0.2 ms**, 시뮬-클럭 어긋남 최대 **2 ms**.

#### 보정 상수 (`play.py` 상단)
| 상수 | 값 | 언제 바꾸나 |
|---|---|---|
| `LEAD` | 0.050 s | `--headless` 추종 오차가 0.05 rad을 넘을 때. `--lead` 옵션으로 즉시 실험 가능 |
| `AUDIO_OFFSET` | 0.0 s | **귀로 맞추는 값.** 손이 음악보다 늦으면 음수, 빠르면 양수. `--offset` 옵션 |

```bash
# LEAD를 바꿔 가며 추종 오차 비교
.\.venv\Scripts\python.exe src\heartbeat\play.py --headless --lead 0.08

# 손이 반 박(222 ms) 늦게 보일 때
.\.venv\Scripts\python.exe src\heartbeat\play.py --offset -0.10
```

#### 모션/시간표 점검
```bash
# 45마디 격자 시각 출력
.\.venv\Scripts\python.exe src\heartbeat\grid.py

# 마디별 배정 동작 표
.\.venv\Scripts\python.exe src\heartbeat\schedule.py

# 안전 범위·속도 상한·격자 정렬·길이 검증 (play.py가 실행 전 자동 호출)
.\.venv\Scripts\python.exe src\heartbeatalidate.py

# 단위 테스트
.\.venv\Scripts\python.exe -m pytest tests	est_heartbeat.py -q
```

#### 안무를 고치고 싶을 때
- `src/heartbeat/motions.json` — 동작별 키프레임. `q`는 0~1 정규화 오므림량(0=펼침, 1=`Q_CLOSE`),
  `A_j0`만 rad. 적지 않은 관절은 직전 값을 유지합니다.
- `src/heartbeat/schedule.json` — 어느 마디에 어느 동작을 쓸지.
- 고친 뒤 `validate.py`를 돌리면 안전 범위·속도 상한 위반을 **어느 키프레임인지까지** 짚어 줍니다.

> ⚠ 속도 검사는 평균이 아니라 **순간 최대 속도**로 합니다. `ease="out"`은 출발 기울기가 평균의 3배라
> 8분음표(222 ms) 구간에 쓰면 상한 3.0 rad/s를 넘깁니다. 짧은 구간에는 `inout`을 쓰세요.

---

## 4. 카메라 기반 손 원격 조종 (`teleop.py`)

### 4.1 관절 매핑 및 동작 원리
`src/teleop.py`는 웹캠 영상에서 MediaPipe를 통해 사람 손의 21개 3D 랜드마크를 추출하고, 이를 `tri_hand`의 관절 각도로 실시간 리타겟팅합니다.

- **사람 손가락 ↔ 로봇 손가락 대응**:
  - **사람 검지** ➡️ **Finger A** (상단 3자유도)
  - **사람 중지** ➡️ **Finger B** (하단 2자유도)
  - **사람 약지** ➡️ **Finger C** (하단 2자유도)
  - *엄지와 새끼손가락은 손가락 굴곡 매핑에는 사용하지 않습니다.*
- **마디별 굴곡 대응**:
  - 사람 손허리손가락관절(MCP, 첫째 마디) 굽힘 ➡️ `j1`
  - 사람 PIP + DIP(둘째·셋째 마디) 굽힘 합 ➡️ `j2`
- **엄지 좌우 벌림 ↔ A_j0 (요/대립 관절)**:
  - 사람 엄지를 손바닥 면에서 바깥으로 벌리거나 안으로 모으는 각도를 측정하여 엄지 베이스 요 관절(`A_j0`)을 조작합니다.
- **안전 기능**:
  - 손을 카메라 시야에서 벗어나면(`no hand`) 목표 각도 전송을 중단하고 직전 자세를 안전하게 유지합니다.
  - 급격한 변화를 막기 위해 지수 평활(Exponential Smoothing) 및 최대 속도 제한(`MAX_SPEED = 3.0 rad/s`)이 적용됩니다.

---

### 4.2 시뮬레이션 연동 실행
가장 일반적인 사용 시나리오로, 웹캠으로 시뮬레이션 속 로봇 손을 실시간 조종합니다.

```bash
# [터미널 1] 먼저 HTTP 제어 서버를 실행합니다.
python src/server.py --headless

# [터미널 2] 텔레오퍼레이션 스크립트를 실행합니다.
python src/teleop.py
```
> 최초 실행 시 MediaPipe 손 인식 모델(`src/models/hand_landmarker.task`)이 자동으로 다운로드됩니다.  
> 화면에 뜨는 미리보기 창에서 `q` 키를 누르면 종료됩니다.

---

### 4.3 주요 실행 옵션

```bash
# 1) 다른 카메라 장치 지정 (기본값: 0)
python src/teleop.py --source 1

# 2) 녹화된 비디오 파일 입력으로 테스트
python src/teleop.py --source demo_hand.mp4

# 3) 서버 URL 변경 (원격 PC에서 서버가 돌아갈 때)
python src/teleop.py --url http://192.168.0.10:8000

# 4) GUI 미리보기 창 없이 터미널 모드로 실행 (WSL2 또는 원격 환경)
python src/teleop.py --no-preview
```

---

## 5. 실물 모터 연동 및 캘리브레이션 (`motors.py`)

Robotis Dynamixel XL430-W250-T 서보 모터(7개)를 사용할 때는 각 모터의 ID 배정, 영점(0 rad) 및 회전 방향(sign)을 기록하는 캘리브레이션 과정이 필수적입니다.

### 5.1 하드웨어 준비 및 연결
1. **장치 구성**: PC ── USB ──> U2D2 ── TTL ──> XL430 데이지 체인 (ID 1~7) + 12V 외부 전원(SMPS/Power Hub)
2. **주의사항**: U2D2는 신호 변환기이므로 모터 구동 전원(12V)이 반드시 별도로 공급되어야 합니다.
3. 기본 통신 속도는 **1,000,000 bps (1 Mbps)** 입니다.

---

### 5.2 관절 캘리브레이션 (`calibrate`)
모터의 토크를 끈 상태에서 손으로 로봇 관절을 직접 움직여 설정 파일(`src/motors.json`)을 생성합니다.

```bash
# 캘리브레이션 모드 실행 (포트 지정)
python src/motors.py calibrate --port /dev/ttyUSB0 --baud 1000000
```

#### 진행 순서:
1. 스크립트가 실행되면 버스 핑을 통해 7개의 모터 ID를 자동 감지하고 토크를 끕니다.
2. **영점 설정**: 로봇 손의 모든 손가락을 일직선으로 곧게 펴고 엄지 요 관절을 정중앙(시뮬레이션 초기 자세)에 맞춘 후 `Enter`를 누릅니다.
3. **관절별 매핑**: 터미널 안내에 따라 각 관절(`A_j0`부터 `C_j2`까지)을 하나씩 손으로 20° 이상 움직인 후 `Enter`를 누르면 이동량이 가장 큰 모터를 해당 관절로 자동 등록합니다.
4. 완료 시 `src/motors.json`이 자동 생성됩니다.

---

### 5.3 관절 각도 실시간 검증 (`check`)
캘리브레이션이 올바르게 되었는지 토크가 꺼진 상태에서 각도를 확인합니다.

```bash
python src/motors.py check --config src/motors.json
```
- 손으로 관절을 움직였을 때 터미널에 출력되는 각도(rad)가 다음 부호 규칙과 일치하는지 확인합니다:
  - **오므리는 방향**:
    - `Finger A`: 음수(`-`)로 증가
    - `Finger B, C`: 양수(`+`)로 증가
  - 각도가 반대로 움직인다면 `motors.json` 파일에서 해당 관절의 `"sign"` 값을 `-1`로 수정합니다.
- `Ctrl + C`를 누르면 안전하게 종료됩니다.

---

## 6. 실물 로봇 손 텔레오퍼레이션 (Sim-to-Real)

캘리브레이션이 완료되면 웹캠을 통해 실물 로봇 손을 직접 조종하거나, 시뮬레이션과 동시에 미러링 구동할 수 있습니다.

```bash
# 방법 1) 시뮬레이션과 실물 모터를 동시에 연동 (미러링)
# 터미널 1: 시뮬레이션 서버 실행
python src/server.py --headless
# 터미널 2: 텔레옵 실행 (모터 설정 파일 지정)
python src/teleop.py --motors src/motors.json

# 방법 2) 시뮬레이션 없이 실물 모터만 단독 구동
python src/teleop.py --motors src/motors.json --url ""

# 방법 3) 캘리브레이션 파일 없이 간이 시험 모드 (Try Mode)
# * 로봇 손을 완전히 편 채로 시작해야 하며, 안전을 위해 각도가 ±0.3 rad(~17°)로 제한됩니다.
python src/teleop.py --motors try --url ""
```

---

## 7. 자주 묻는 문제 및 문제 해결 (Troubleshooting)

### Q1. `포트를 열 수 없음: /dev/ttyUSB0` 또는 `Permission denied`
- **원인**: 시리얼 장치 권한 부족 또는 장치 경로 불일치.
- **해결**:
  ```bash
  # 권한 부여
  sudo chmod 666 /dev/ttyUSB0
  # 또는 현재 계정을 dialout 그룹에 추가
  sudo usermod -aG dialout $USER
  ```
  `ls /dev/ttyUSB*` 명령어로 올바른 포트 번호를 확인하세요.

### Q2. `모든 통신 속도에서 모터가 응답하지 않음`
- **원인**:
  1. 12V 외부 전원이 연결되어 있지 않음 (U2D2만 연결된 경우 모터가 동작하지 않습니다).
  2. 전원 허브 스위치가 꺼져 있거나 배선이 느슨함.
- **해결**: 전원 연결 상태 및 LED 점등 여부를 확인하세요.

### Q3. WSL2 환경에서 웹캠이 열리지 않음 (`카메라/파일을 열 수 없음: 0`)
- **원인**: Windows 호스트의 웹캠 장치가 WSL2에 마운트되지 않음.
- **해결**:
  1. Windows PowerShell(관리자)에서 `usbipd list`로 웹캠 BUSID 확인.
  2. `usbipd wsl attach --busid <BUSID>` 실행 후 WSL2에서 `ls /dev/video*` 확인.
  3. 필요 시 `--no-preview` 옵션으로 GUI 창 없이 실행.

### Q4. MediaPipe 손 인식 모델 다운로드 에러
- **해결**: 인터넷 연결이 불안정할 경우 수동으로 모델을 다운로드하여 배치할 수 있습니다:
  ```bash
  mkdir -p src/models
  curl -o src/models/hand_landmarker.task https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
  ```

### Q5. 특정 관절이 오므릴 때 시뮬레이션/실제 손과 반대로 움직임
- **해결**: `src/motors.json`을 열어 해당 관절의 `"sign"` 값을 `1` ↔ `-1`로 반전시킵니다.
