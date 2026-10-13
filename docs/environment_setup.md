# 환경 및 가상환경 세팅 가이드 (Environment Setup)

`tri_hand` 프로젝트를 로컬 시뮬레이션 및 실물 하드웨어(Real Robot) 환경에서 구동하기 위한 개발 환경 세팅 가이드입니다.

---

## 1. 운영체제별 지원 정책 (OS Policy)

본 프로젝트는 **Linux, macOS, Windows**를 모두 지원하며 환경별 특성은 다음과 같습니다:

| 운영체제 | 지원 상태 | 권장 용도 및 비고 |
| :--- | :---: | :--- |
| **Windows 10/11** | **공식 권장 (네이티브)** | **내장 웹캠 원격 조종(`teleop.py`) + U2D2(USB) 실물 제어 동시 구동 시 필수**.<br>WSL2는 내장 웹캠 접근 불가 및 프레임 프리징 이슈가 있어 호스트 Windows 사용. |
| **Linux (Ubuntu)** | **검증 완료** | 실물 로봇 장기 내구 시험(24h headless) 및 서버 환경 |
| **macOS** | **검증 완료** | 개발 및 시뮬레이션 (GUI 실행 시 `mjpython` 필요) |

> ⚠ **Windows에서 WSL2를 사용하지 않는 이유**:  
> 노트북 내장 카메라는 메인보드 내부 버스로 연결되어 있어 WSL2 가상머신에 패스스루할 수 없으며, 외장 웹캠을 `usbipd`로 붙이더라도 프레임 수신 중 `cap.read()`가 멈추는 현상이 발생합니다. 따라서 **내장 카메라와 실물 로봇을 함께 구동하려면 반드시 Windows 네이티브 환경(PowerShell/CMD)**을 사용해야 합니다.

---

## 2. Windows 네이티브 환경 세팅 (공식 권장)

처음 사용하는 분들도 오류 없이 따라 할 수 있도록 **사전 준비부터 패키지 설치까지 1단계씩 순서대로** 진행합니다.  
Windows PowerShell 또는 Windows Terminal을 열고 시작하세요.

### 2-1. 사전 준비 (코드 다운로드 & Python 3.10 설치)

1. **프로젝트 코드 다운로드 (Git Clone)**:
   ```powershell
   # 원하는 작업 폴더로 이동 후 클론
   git clone https://github.com/ajin-robot-hand/tri_hand.git
   cd tri_hand
   ```
   *(Git이 설치되어 있지 않다면 GitHub 웹페이지의 Code → [Download ZIP]으로 내려받아 압축을 푼 뒤 해당 폴더로 이동합니다. 폴더명이 `tri-hand`인 경우 `cd tri-hand`로 이동하세요.)*

2. **Python 3.10 설치 및 확인**:
   - [Python 3.10 공식 다운로드 페이지](https://www.python.org/downloads/release/python-31011/)에서 Windows installer (64-bit)를 받아 설치하거나, PowerShell에서 `winget install Python.Python.3.10`을 실행합니다.
   - ⚠ **매우 중요**: 설치 마법사 첫 화면 맨 아래의 **`Add python.exe to PATH` (환경 변수 추가)**를 반드시 체크해야 터미널에서 `python` 명령어를 정상 인식합니다.
   - 버전 확인:
     ```powershell
     python --version
     # 출력 예시: Python 3.10.x
     ```
     *(만약 `python` 입력 시 Microsoft Store 창이 뜨거나 명령어를 찾지 못하면 설치 시 `Add to PATH`가 누락된 것이므로 설치 프로그램을 다시 실행해 Modify/Repair를 진행하세요.)*

### 2-2. PowerShell 스크립트 실행 권한 허용 (최초 1회 필수)
Windows 기본 보안 정책상 PowerShell에서는 외부 스크립트 실행이 차단되어 있어, 가상환경 활성화 시 `이 시스템에서 스크립트를 실행할 수 없으므로...` 오류가 발생합니다. 아래 명령어로 현재 사용자에게 권한을 부여하세요:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
*(실행 정책 변경 여부를 묻는 메시지가 나타나면 `Y`를 누르고 엔터를 칩니다. 이 설정은 컴퓨터당 최초 1회만 수행하면 됩니다.)*

### 2-3. 가상환경 생성 (최초 1회 필수)
프로젝트 상위 디렉토리(또는 프로젝트 폴더)에 가상환경(`mujoco_env`)을 생성합니다:
```powershell
python -m venv ..\mujoco_env
```
- 상위 폴더(`c:\workspace\`)에 `mujoco_env` 디렉토리가 생성됩니다. (이 폴더는 `.gitignore`에 등록되어 있어 Git 관리 대상에서 자동으로 제외됩니다.)

### 2-4. 가상환경 활성화
터미널 환경에 맞는 명령어를 입력해 가상환경으로 진입합니다:

```powershell
# Windows PowerShell (권장):
..\mujoco_env\Scripts\Activate.ps1

# Windows 명령 프롬프트(CMD):
..\mujoco_env\Scripts\activate.bat

# Windows Git Bash:
source ../mujoco_env/Scripts/activate
```

✅ **정상 진입 확인**:  
명령어 줄 맨 앞에 **`(mujoco_env)`** 표시가 붙었다면 가상환경에 성공적으로 들어온 것입니다!

### 2-5. 필수 의존성 패키지 설치 (가상환경 생성 후 필수 단계)
새로 생성한 가상환경에는 패키지가 전혀 설치되어 있지 않습니다. 아래 명령어로 프로젝트 실행에 필요한 라이브러리를 일괄 설치합니다:

```powershell
# 1. pip 최신 버전으로 업그레이드
python -m pip install --upgrade pip

# 2. 필수 패키지 일괄 설치 (MuJoCo, FastAPI, Dynamixel SDK, MediaPipe 등)
pip install -r requirements.txt
```
*(유닛 테스트 및 개발 도구가 필요한 경우: `pip install -r requirements-dev.txt` 추가 설치)*

---

### 2-6. 하드웨어 점검 (선택 사항)
> 💡 **시뮬레이션만 구동하려는 경우**:  
> 실물 로봇(U2D2)이나 카메라가 없어도 MuJoCo 가상 시뮬레이션은 즉시 실행할 수 있습니다. 하드웨어가 없다면 이 항목을 건너뛰고 **[5. 환경 정상 여부 검증]**으로 바로 이동하세요.

#### ① 내장 웹캠 (Camera Teleop)
Windows 환경에서는 별도 드라이버 설치 없이 0번 기본 인덱스로 내장 웹캠이 즉시 구동됩니다:
```powershell
# 기본 내장 카메라로 손 인식 원격 조종 실행
python src/teleop.py

# 외장 웹캠이 연결되어 있어 카메라를 전환할 경우
python src/teleop.py --source 1
```

#### ② U2D2 USB 시리얼 통신 (실물 로봇 제어)
1. U2D2 USB를 PC에 꽂고 모터 12V 전원을 연결합니다.
2. Windows **장치 관리자** → **포트 (COM & LPT)** 항목에서 `USB Serial Port (COM3)` 등으로 인식되었는지 확인합니다.
3. 통신 점검:
   ```powershell
   # 포트를 자동 탐색하여 모터 7개 상태를 점검합니다
   python real/check.py
   ```
   *(포트가 여러 개이거나 직접 지정할 때는 `python real/check.py --port COM3` 처럼 입력합니다.)*

---

## 3. Linux / macOS 환경 세팅 (검증 완료)

<details>
<summary><b>Linux (Ubuntu) 설정 방법 접기/펼치기</b></summary>

```bash
# 1) 패키지 설치
sudo apt update && sudo apt install -y python3.10 python3.10-venv python3-pip

# 2) 가상환경 생성 및 활성화
python3.10 -m venv ~/mujoco_env
source ~/mujoco_env/bin/activate

# 3) 의존성 설치
pip install -r requirements.txt
```
</details>

<details>
<summary><b>macOS 설정 방법 접기/펼치기</b></summary>

```bash
# 1) Homebrew로 Python 3.10 설치
brew install python@3.10

# 2) 가상환경 생성 및 활성화
python3.10 -m venv ~/mujoco_env
source ~/mujoco_env/bin/activate

# 3) 의존성 설치
pip install -r requirements.txt
```

> **macOS GUI 뷰어 실행 주의사항**:  
> macOS의 UI 스레드 특성상 MuJoCo 3D 화면을 띄울 때는 일반 `python` 대신 `mjpython`을 사용해야 합니다:  
> ```bash
> mjpython src/run_sim.py
> ```
</details>

---

## 4. `uv` 초고속 패키지 관리자 사용 (선택 사항)

[`uv`](https://github.com/astral-sh/uv)를 사용하면 가상환경 생성과 패키지 다운로드를 수 초 내에 마칠 수 있습니다.

```powershell
# 1) uv 설치 (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) Python 3.10 가상환경 생성 및 활성화
uv python install 3.10
uv venv ..\mujoco_env --python 3.10
..\mujoco_env\Scripts\Activate.ps1

# 3) 패키지 설치
uv pip install -r requirements.txt
```

---

## 5. 환경 정상 여부 검증 (Verification)

가상환경을 활성화(`(mujoco_env)` 표시 확인)한 상태에서 아래 명령어로 정상 설치 여부를 확인합니다.

### 5-1. 기본 시뮬레이션 환경 검증 (필수, 하드웨어 불필요)
실물 하드웨어나 웹캠이 없어도 아래 3개 명령어가 정상 통과해야 합니다:

```powershell
# 1. Python 버전 확인 (3.10.x 인지 확인)
python --version

# 2. MuJoCo 물리 엔진 로드 및 버전 확인
python -c "import mujoco; print('MuJoCo version:', mujoco.__version__)"

# 3. 로봇 손 모델 XML 컴파일 검증
python -c "import mujoco; m = mujoco.MjModel.from_xml_path('src/scene.xml'); print('MuJoCo XML 로드 성공!')"
```

### 5-2. 카메라 원격 조종 패키지 검증 (선택)
웹캠을 이용한 손 인식 원격 조종을 사용할 경우 검증합니다:
```powershell
# OpenCV 및 MediaPipe 임포트 확인
python -c "import cv2, mediapipe; print('OpenCV & MediaPipe 정상 로드')"
```

### 5-3. 실물 로봇 U2D2 통신 검증 (선택)
U2D2 인터페이스를 연결한 경우 포트 탐색을 확인합니다:
```powershell
# Dynamixel SDK 및 COM 포트 자동 탐색 검증
python -c "import sys; sys.path.insert(0, 'real'); import dxl; print('U2D2 포트 탐색 결과:', dxl.find_ports())"
# U2D2가 연결되어 있지 않은 경우 빈 리스트([])가 출력되는 것이 정상이니 안심하세요.
```

### 5-4. 첫 실행 테스트 (가상 시뮬레이션 서버 띄우기)
모든 세팅이 끝났다면 아래 명령어로 시뮬레이션 서버를 띄워 웹 대시보드가 열리는지 확인합니다:
```powershell
python src/server.py --headless
```
터미널에 `Application startup complete`가 뜨면 웹 브라우저에서 **`http://127.0.0.1:8000`**에 접속해 봅니다. 로봇 손 대시보드가 정상 표시되면 세팅 완료입니다! (종료는 터미널에서 `Ctrl + C`)
