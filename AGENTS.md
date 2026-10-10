# tri_hand MuJoCo 시뮬레이션 및 Heartbeat 프로젝트 지침 (AGENTS.md)

이 문서는 `tri_hand`(3지 다관절 로봇 손)의 MuJoCo 시뮬레이션 및 비트 연출(Heartbeat) 프로젝트를 위한 AI 에이전트 작업 지침서입니다. 에이전트는 작업 시 항상 아래 규칙과 하드웨어 명세를 준수해야 합니다.

---

## 1. 환경 및 실행 규칙 (Environment & Execution)

- **Python 가상환경**:
  - 가상환경(`.venv`)의 바이너리를 사용합니다:
    - Windows: `.\.venv\Scripts\python.exe`
    - Linux/macOS: `.venv/bin/python`
  - 패키지 설치 시: `pip install -r requirements.txt`
- **시뮬레이션 및 테스트 실행**:
  - 코드 동작 및 물리 엔진 수치 검증 시에는 빠른 검증을 위해 **헤드리스 옵션을 기본으로 사용**합니다:
    ```bash
    python src/run_sim.py --headless
    pytest tests/
    ```
  - Windows 네이티브 환경에서 음원 출력, 뷰어 GUI, 실물 모터(U2D2 COM 포트) 제어를 지원합니다.
- **XML 모델 유효성 사전 검증**:
  - `src/hand.xml` 또는 `src/scene.xml`을 수정한 후에는 시뮬레이션을 돌리기 전에 파이썬에서 XML 컴파일 에러 여부를 먼저 확인하세요:
    ```python
    import mujoco
    model = mujoco.MjModel.from_xml_path("src/scene.xml")
    ```

---

## 2. 좌표계 및 물리 단위 표준 (Coordinate & Physics Standards)

- **SI 단위계 준수**:
  - 거리: `m` (미터) - CAD 메쉬(mm) 임포트 시 `scale="0.001 0.001 0.001"` 적용 필수
  - 각도: `rad` (라디안, `compiler angle="radian"`)
  - 질량: `kg`
  - 힘 / 토크: `N` / `N·m`
- **중력 및 높이축**:
  - 이 프로젝트의 중력은 **`-Y` 방향**입니다 (`gravity="0 -9.81 0"`).
  - 바닥 평면(`scene.xml`) 및 부품 높이 배치 시 **Y축**을 기준으로 계산하세요.
- **관절 축 및 회전 부호 규칙**:
  - 모든 손가락 관절의 회전 축은 `+X`축(`axis="1 0 0"`)입니다.
  - 손가락 배치 특성에 따른 오므림(Grasp/Close) 부호:
    - **Finger A (상단)**: 음수(`-`) 방향 회전이 오므림
    - **Finger B, C (하단)**: 양수(`+`) 방향 회전이 오므림
    - **엄지 대립 관절(A_j0)**: 요(Yaw) 회전 (±1.0472 rad)

---

## 3. 실물 하드웨어 스펙 및 안전 범위 (Hardware Specs & Limits)

실제 조립된 로봇 손의 물리적 특성을 준수하며, 임의로 비현실적인 수치를 넣지 않고 안전 가동 범위를 벗어나지 않도록 합니다.

- **서보 모터 (Dynamixel XL430-W250-T)**:
  - 최대 정격 토크: `1.4 N·m` (`forcerange="-1.4 1.4"`)
  - 위치 제어 기본 게인: `kp="12"`, `kv="0.5"` (D 게인 `kv`로 오버슈트 억제)
  - 제어 입력 범위: `ctrlrange="-1.5708 1.5708"` (-90° ~ +90°)
- **안전 가동 범위 (`safe_range`)**:
  - `j1` (근위 관절): `0.0 ~ 0.3 rad` (손가락 간 간섭 방지 상한)
  - `j2` (원위 관절): `0.0 ~ 1.2 rad` (`run_sim.Q_CLOSE`)
  - `A_j0` (엄지 요): `-1.0472 ~ 1.0472 rad` (`run_sim.YAW_LIMIT`)
  - 관절 회전 속도 상한: `3.0 rad/s` 이하
- **링크 및 조립체 질량**:
  - 손가락 단위 유닛(`unit`): 약 `0.07 kg` (`diaginertia="2.773e-05 1.486e-05 3.344e-05"`)
  - 팜 베이스: 고정 지지대(`worldbody` 직속)

---

## 4. Heartbeat 모션 & 비트 동기화 규칙 (Heartbeat Standards)

- **규칙 기반 시간표 사전 생성 (Time-scheduled)**:
  - 실시간 오디오 반응이나 카메라 비전 추정을 사용하지 않습니다.
  - 미리 계산된 비트 시각(`beats.json`)과 모션 정의(`motions.json`)를 바탕으로 규칙 기반 시간표(`schedule.py`)를 사전 생성하여 순차 실행합니다.
- **모션 도착 시점 비트 정렬**:
  - 동작의 시작이 아니라 **도착 시점을 비트(또는 8분음표)에 일치**시키는 것이 시각적 싱크의 원칙입니다.
- **마스터 클럭 누적 오차 방지**:
  - 음원 재생 시작 시각 `t0 = time.perf_counter()`를 기준으로, 모든 목표값을 `t - t0`의 함수로 계산합니다.
- **모션 안전성 자동 검증 (Verification Rules)**:
  1. 모든 목표 각도가 `safe_range` 범위 내인가?
  2. 인접 키프레임 간 속도 `|Δq| / Δt ≤ 3.0 rad/s`를 만족하는가? (박 길이 안에 도달 가능한가?)
  3. 모든 모션의 도착 시각이 비트 그리드에 정렬되는가?
  4. 시간표 총 길이가 음원 재생 구간(≈1:14)을 초과하지 않는가?

---

## 5. MuJoCo 모델링 원칙 (Modeling Best Practices)

- **시각 메쉬(Visual)와 충돌체(Collision) 분리 유지**:
  - 시각용 메쉬(`group 1`): `unit.stl`, `palm.stl` (복잡한 3D 형상 표출, `contype="0" conaffinity="0"`)
  - 충돌용 지오메트리(`group 3`): 단순 프리미티브(`box`, `cylinder` 등, `contype="1" conaffinity="1"`)
  - *이유: 복잡한 STL 메쉬를 직접 충돌체로 쓰면 관통, 튕김, 속도 저하가 발생합니다.*
- **자가 충돌(Self-Collision) 방지**:
  - 초기 조립 상태(`t=0`)에서 링크 및 팜의 collision 박스가 서로 겹쳐있지 않아야 합니다. (초기 겹침 시 시뮬레이션 폭발 원인)

---

## 6. 동작 이상 시 디버깅 프로토콜 (Troubleshooting)

시뮬레이션 동작이 실물이나 예상과 다를 경우 다음 순서로 점검합니다:

1. **기구학 점검 (Kinematics)**:
   - 관절 회전축(`axis`)과 부호(`CLOSE_SIGN`)가 실물과 일치하는가?
   - 링크 부모-자식 관계(`A_link1` -> `A_link2`) 및 회전 중심(pivot pos)이 일치하는가?
2. **초기 관통 및 충돌 간섭 점검 (Penetration & Contact)**:
   - 관절 가동 범위 내에서 손가락끼리 또는 팜과 비정상적으로 부딪히지 않는가?
3. **액추에이터 파라미터 점검 (Control Gains & Limits)**:
   - 목표 각도에 도달하지 못하면 `kp`가 부족하거나, `forcerange`(1.4 N·m) 한계에 걸린 것은 아닌가?
   - 손가락이 떨리거나 진동(chattering)하면 `kv`를 늘리거나 관절 `damping`을 조정.
