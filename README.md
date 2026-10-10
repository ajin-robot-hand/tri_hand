# tri_hand MuJoCo 시뮬레이션

3지 다관절 로봇 손(`tri_hand`)의 물리 시뮬레이션을 위한 MuJoCo 프로젝트입니다.

<p align="center">
  <img src="docs/mujoco.gif" alt="tri_hand MuJoCo 시뮬레이션 데모" width="100%">
  <br>
  <em>🎬 시뮬레이션 데모 </em>
</p>

---

## 💻 지원 OS 및 환경 요건

- **권장 Python 버전**: **Python 3.10**
- **지원 운영체제**:
  - **Linux** (Ubuntu 20.04 / 22.04 등)
  - **macOS** (Apple Silicon M1/M2/M3/M4 및 Intel)
  - **Windows** (반드시 **WSL2** 환경에서 실행)

---

## 🛠 OS별 환경 세팅 가이드

### 1. Linux (Ubuntu/Debian)

```bash
# 1) Python 3.10 및 venv 설치
sudo apt update
sudo apt install -y python3.10 python3.10-venv

# 2) 가상환경 생성 및 활성화
python3.10 -m venv mujoco_env
source mujoco_env/bin/activate

# 3) 의존성 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt
```

> 💡 **42 Cluster 환경 안내**:  
> 42 Cluster 컴퓨터(NFS / Non-sudo 환경)에서도 Python 가상환경 구축 및 MuJoCo 실행이 가능합니다. 관련 세팅 가이드 및 자동화 스크립트는 `feat/cluster_com` 브랜치를 참고해 주세요. 

---

### 2. macOS (Homebrew)

```bash
# 1) Homebrew를 통해 Python 3.10 설치
brew install python@3.10

# 2) 가상환경 생성 및 활성화
python3.10 -m venv mujoco_env
source mujoco_env/bin/activate

# 3) 의존성 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 3. Windows (WSL2 사용자)

> ⚠️ **주의**: Windows 호스트 터미널에서 직접 실행하지 마시고, **WSL2(Ubuntu)** 내부에서 실행해야 합니다.

1. WSL2 터미널을 실행합니다.
2. 위의 **[1. Linux]** 가이드와 동일하게 `python3.10-venv` 설치 후 가상환경을 생성하고 실행합니다.

---

## 🚀 시뮬레이션 실행 방법

OS 및 환경에 따라 뷰어 실행 명령어가 다릅니다.

### 📌 OS별 뷰어(GUI) 실행 명령어

- **macOS**:
  macOS의 UI 이벤트 루프 특성상 `python` 대신 MuJoCo에서 제공하는 `mjpython`을 사용해야 뷰어가 정상 실행됩니다.
  ```bash
  mjpython src/run_sim.py
  ```

- **Linux (데스크탑 GUI 환경)**:
  ```bash
  python src/run_sim.py
  ```

- **WSL2 / 헤드리스 서버 (터미널 수치 확인)**:
  WSL2 환경에서는 그래픽 드라이버 이슈로 GUI 창이 멈출 수 있으므로, 물리 엔진 검증 시 `--headless` 옵션을 권장합니다.
  ```bash
  python src/run_sim.py --headless
  ```

---

## 🧪 테스트 실행

```bash
pytest tests
```

---

## 🦾 실물 모터 연동 (`src/motors.py`)

Dynamixel XL430-W250-T 서보 모터(ID 1~7)를 U2D2 인터페이스를 통해 직접 제어합니다.

```bash
# 1) 실물 모터 캘리브레이션 (U2D2 연결 후 관절별 모터 ID/영점 기록)
python src/motors.py calibrate --port COM3 --baud 1000000

# 2) 모터 현재 위치 및 부호 확인
python src/motors.py check
```

---

## 📁 프로젝트 구조

```
tri_hand/
├── docs/               # 이론 배경 학습 자료 및 Heartbeat 프로젝트 자산
│   └── heartbeat/      # Heartbeat 음악/모션 동기화 자산 및 계획
│       ├── Heartbeat.mp3
│       ├── heartbeat.mp4
│       └── brainstorming.md
├── src/                # 메인 시뮬레이션 모델 및 제어 환경
│   ├── scene.xml       # 전체 시뮬레이션 씬 (바닥, 조명, 타겟 물체 등)
│   ├── hand.xml        # 로봇 손 기구학/동역학 모델
│   ├── meshes/         # 3D STL 메쉬 파일
│   ├── run_sim.py      # 단독 시뮬레이션 실행 스크립트
│   └── motors.py       # 실물 Dynamixel 모터 제어 및 캘리브레이션
├── tests/              # 단위 테스트 (pytest)
│   └── test_motors.py  # 모터 통신 및 안전 제어 검증
├── AGENTS.md           # 시뮬레이션 에이전트 지침 및 하드웨어 명세
├── requirements.txt    # 핵심 의존성 목록
├── .gitignore          # 깃 추적 제외 목록
└── README.md           # 프로젝트 안내서
```

---

## ⚙️ 좌표계 및 제어 규칙 (개발 참고)

- **중력 방향**: `-Y` 축 (`gravity="0 -9.81 0"`)
- **손가락 관절 회전축**: `+X` 축
- **오므림(Grasp) 부호**:
  - **Finger A (상단)**: 음수(`-`) 방향
  - **Finger B, C (하단)**: 양수(`+`) 방향
- **모터 스펙 (Dynamixel XL430-W250-T)**: 최대 토크 `1.4 N·m` (`forcerange="-1.4 1.4"`)
