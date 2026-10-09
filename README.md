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

## 🖥 웹 대시보드 (HTTP 제어 서버)

`src/server.py`는 시뮬레이션을 돌리면서 HTTP API와 웹 대시보드를 함께 제공합니다. (시뮬레이션 전용이며 실물 Dynamixel 모터는 제어하지 않습니다.)

```bash
cd src
python server.py --headless                  # 이 컴퓨터에서만 접속: http://127.0.0.1:8000
python server.py --headless --host 0.0.0.0   # 같은 LAN(공유기)의 다른 기기에서도 접속 허용
```

- `--headless`를 빼면 MuJoCo 뷰어도 함께 뜹니다 (macOS는 `mjpython server.py`).
- `--port`로 포트, `--presets`로 프리셋 파일 경로를 바꿀 수 있습니다 (기본 `src/presets.json`, git 추적 제외).
- **LAN 접속**: `--host 0.0.0.0`으로 실행한 뒤, 같은 네트워크의 기기에서 `http://<이 컴퓨터의 IP>:8000`을 엽니다.
  IP는 macOS에서 `ipconfig getifaddr en0`, Linux에서 `hostname -I`로 확인합니다. OS 방화벽이 막으면 직접 허용해야 합니다.
  WSL2는 기본 NAT 모드에서 외부 기기가 바로 접속할 수 없어 Windows 쪽 포트 전달 설정이 따로 필요합니다 (이 저장소는 설정하지 않음).

### 대시보드에서 보이는 값

연결 상태, 시뮬레이션 시각, 접촉 수, 그리고 모터 7개(`A_j0`, `A_j1`, `A_j2`, `B_j1`, `B_j2`, `C_j1`, `C_j2`)마다
현재 각도·목표 각도(rad), 속도(rad/s), 토크(N·m), 현재 kp·kv·토크 한계(N·m)를 0.2초마다 갱신합니다.

### 프리셋

프리셋은 모터 7개 전체의 목표 각도, kp, kv, 토크 한계를 이름을 붙여 저장한 것입니다.

1. 표 오른쪽 편집 칸에 값을 넣고 이름을 입력한 뒤 **편집 값을 프리셋으로 저장**을 누릅니다. 같은 이름이면 덮어씁니다.
   저장만 하고 시뮬레이션에는 반영하지 않습니다.
2. **프리셋** 드롭다운에서 고르면 편집 칸에 그 값이 채워질 뿐, 시뮬레이션은 바뀌지 않습니다.
3. **적용**을 눌러야 저장된 프리셋이 시뮬레이션에 반영됩니다. 저장하지 않은 편집 값은 적용되지 않습니다.

서버가 받아들이는 범위 (범위 밖이면 저장을 거부):

| 항목 | 허용 범위 |
|---|---|
| 목표 각도 | `A_j0` ±1.0472 rad, 나머지 ±1.5708 rad (각 관절 ctrlrange) |
| kp | 0 초과 ~ 100 |
| kv | 0 ~ 5 |
| 토크 한계 | 0 초과 ~ 1.4 N·m (XL430 정격) |

kp/kv 상한은 이 범위의 양 끝 값으로 최대 목표 각도까지 움직였을 때 시뮬레이션이 발산하지 않는 것을 확인한 값입니다.

프리셋은 JSON 파일에 저장되어 서버를 다시 켜도 남지만, 서버를 다시 켜면 게인은 `hand.xml` 기본값(kp=12, kv=0.5, 1.4 N·m)으로 돌아가며 프리셋은 자동 적용되지 않습니다.
`POST /reset`은 자세와 목표 각도만 초기화하고 적용된 게인은 유지합니다.

### 제한 사항

- **인증이 없습니다.** 접속할 수 있는 사람은 누구나 시뮬레이션을 조작하고 프리셋을 덮어쓸 수 있습니다. 신뢰할 수 있는 LAN에서만 `--host 0.0.0.0`을 쓰고, 공유기 포트 포워딩 등으로 인터넷에 노출하지 마세요.
- HTTPS가 아닌 HTTP입니다.
- 3D 화면과 실물 모터 제어는 포함하지 않습니다. 프리셋 삭제는 `src/presets.json`을 직접 편집해야 합니다.
- 프리셋 파일이 깨지거나 형식이 틀리면(직접 편집 실수 등) 프리셋 조회/저장/적용은 HTTP 500과 원인 메시지를 돌려주고 파일은 덮어쓰지 않습니다. 실시간 상태 표시는 계속 동작합니다. 파일을 고치거나 지우면 다시 쓸 수 있습니다.

### 테스트

```bash
pip install pytest httpx
python -m pytest tests
```

---

## 📹 카메라 원격 조종 및 실물 모터 연동

`src/teleop.py`를 사용해 웹캠으로 손을 인식(MediaPipe)하여 시뮬레이션 및 실물 Dynamixel 모터를 실시간으로 원격 조종할 수 있습니다.

```bash
# 1) 웹캠으로 시뮬레이션 손 원격 제어 (먼저 server.py 실행 필요)
python src/teleop.py

# 2) 실물 모터 캘리브레이션 (U2D2 연결 후 관절별 모터 ID/영점 기록)
python src/motors.py calibrate --port /dev/ttyUSB0 --baud 1000000

# 3) 실물 모터 및 시뮬레이션 동시 구동
python src/teleop.py --motors src/motors.json
```

> 📖 **상세 실행 매뉴얼**:  
> 환경 세팅, 관절 캘리브레이션, Sim-to-Real 미러링 및 트러블슈팅의 전체 과정은 **[docs/execution_guide.md](docs/execution_guide.md)**를 참고하세요.

---

## 📁 프로젝트 구조

```
tri_hand/
├── docs/               # 이론 배경 학습 자료, 데모 미디어 및 실행 가이드
│   ├── execution_guide.md  # 🚀 [상세] 전체 스크립트 실행 및 하드웨어 연동 가이드
│   └── mujoco.gif      # 시뮬레이션 데모 영상
├── src/                # 메인 시뮬레이션 모델 및 제어 환경
│   ├── scene.xml       # 전체 시뮬레이션 씬 (바닥, 조명, 타겟 물체 등)
│   ├── hand.xml        # 로봇 손 기구학/동역학 모델
│   ├── meshes/         # 3D STL 메쉬 파일
│   ├── run_sim.py      # 단독 시뮬레이션 실행 스크립트
│   ├── server.py       # HTTP 제어 서버 + 프리셋 API
│   ├── dashboard.html  # 웹 대시보드 (server.py가 / 에서 제공)
│   ├── teleop.py       # 웹캠(MediaPipe) 기반 비전 원격 조종
│   └── motors.py       # 실물 Dynamixel 모터 제어 및 캘리브레이션
├── tests/              # server.py API 테스트 (pytest)
├── tutorial/           # MuJoCo 모델링 기초 단계별 실습 예제
│   ├── 01_hello.xml    # 기본 세상 구성 및 자유 낙하
│   ├── 02_joints_tendon.xml # 다관절 링크 및 텐던 실습
│   └── run.py          # 튜토리얼 실행 스크립트
├── AGENTS.md           # 시뮬레이션 에이전트 지침 및 하드웨어 명세
├── requirements.txt    # 크로스 플랫폼 호환 파이썬 의존성
├── .gitignore          # 깃 추적 제외 목록 (가상환경, 캐시 등)
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
