# tri_hand MuJoCo 시뮬레이션 프로젝트 지침 (AGENTS.md)

이 문서는 `tri_hand`(3지 다관절 로봇 손)의 실물 하드웨어를 MuJoCo로 시뮬레이션하기 위한 에이전트 작업 지침서입니다. AI 에이전트는 이 프로젝트에서 작업할 때 항상 아래 규칙과 하드웨어 명세를 준수해야 합니다.

---

## 1. 환경 및 실행 규칙 (Environment & Execution)

- **Python 가상환경**:
  - 시스템 기본 파이썬이 아닌 반드시 가상환경 바이너리를 사용하세요: `~/mujoco_env/bin/python`
  - 패키지 설치 시: `~/mujoco_env/bin/pip`
- **WSL2 환경 고려**:
  - WSL2 특성상 GUI 뷰어(`mujoco.viewer`) 실행 시 디스플레이/렌더링 드라이버 이슈로 프로세스가 멈출(hang) 수 있습니다.
  - 코드 동작 및 물리 엔진 검증 시에는 **항상 `--headless` 옵션을 기본으로 사용**하세요:
    ```bash
    ~/mujoco_env/bin/python src/run_sim.py --headless
    ```
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
  - 일반적인 시뮬레이터(Z축 높이)와 다르므로, 바닥 평면(`scene.xml`) 및 부품 높이 배치 시 **Y축**을 기준으로 계산하세요.
- **관절 축 및 회전 부호 규칙**:
  - 모든 손가락 관절의 회전 축은 `+X`축(`axis="1 0 0"`)입니다.
  - 손가락 배치 특성에 따른 오므림(Grasp/Close) 부호:
    - **Finger A (상단)**: 음수(`-`) 방향 회전이 오므림
    - **Finger B, C (하단)**: 양수(`+`) 방향 회전이 오므림

---

## 3. 실물 하드웨어 스펙 동기화 (Hardware Specs)

실제 조립된 로봇 손의 물리적 특성을 시뮬레이션에 일치시키며, 임의로 비현실적인 수치를 넣지 않습니다.

- **서보 모터 (Dynamixel XL430-W250-T)**:
  - 최대 정격 토크: `1.4 N·m` (`forcerange="-1.4 1.4"`)
  - 위치 제어 기본 게인: `kp="12"`, `kv="0.5"` (D 게인 `kv`로 오버슈트 억제)
  - 제어 입력 범위: `ctrlrange="-1.5708 1.5708"` (-90° ~ +90°)
- **링크 및 조립체 질량**:
  - 손가락 단위 유닛(`unit`): 약 `0.07 kg` (`diaginertia="2.773e-05 1.486e-05 3.344e-05"`)
  - 팜 베이스: 고정 지지대(`worldbody` 직속)

---

## 4. MuJoCo 모델링 원칙 (Modeling Best Practices)

- **시각 메쉬(Visual)와 충돌체(Collision) 분리 유지**:
  - 시각용 메쉬(`group 1`): `unit.stl`, `palm.stl` (복잡한 3D 형상 표출, `contype="0" conaffinity="0"`)
  - 충돌용 지오메트리(`group 3`): 단순 프리미티브(`box`, `cylinder` 등, `contype="1" conaffinity="1"`)
  - *이유: 복잡한 STL 메쉬를 직접 충돌체로 쓰면 관통, 튕김, 속도 저하가 발생합니다.*
- **자가 충돌(Self-Collision) 방지**:
  - 초기 조립 상태(`t=0`)에서 링크 및 팜의 collision 박스가 서로 겹쳐있지 않아야 합니다. (초기 겹침 시 시뮬레이션 폭발 원인)

---

## 5. 동작 이상 시 디버깅 프로토콜 (Troubleshooting)

시뮬레이션 동작이 실물이나 예상과 다를 경우 다음 순서로 점검합니다:

1. **기구학 점검 (Kinematics)**:
   - 관절 회전축(`axis`)과 부호(`CLOSE_SIGN`)가 실물과 일치하는가?
   - 링크 부모-자식 관계(`A_link1` -> `A_link2`) 및 회전 중심(pivot pos)이 일치하는가?
2. **초기 관통 및 충돌 간섭 점검 (Penetration & Contact)**:
   - 관절 가동 범위 내에서 손가락끼리 또는 팜과 비정상적으로 부딪히지 않는가?
3. **액추에이터 파라미터 점검 (Control Gains)**:
   - 목표 각도에 도달하지 못하면 `kp`가 부족하거나, `forcerange`(1.4 N·m) 한계에 걸린 것은 아닌가?
   - 손가락이 떨리거나 진동(chattering)하면 `kv`를 늘리거나 관절 `damping`을 조정.

---

## 6. Git & PR 워크플로우 규칙 (Automation Protocol)

사용자가 **"PR 올려줘"**, **"작업 내용 푸시해줘"** 등 작업 완료 및 제출을 요청하면, 추가 질문 없이 아래 3단계 작업을 **한 번에 연속 실행**합니다:

1. **영문 브랜치 생성**: 변경 내용을 대표하는 영문 `kebab-case` 브랜치 자동 생성 (`git checkout -b <type>/<short-desc>`)
2. **한국어 커밋 & 푸시**: Conventional Commits 규칙을 준수한 한국어 메시지로 커밋 후 푸시 (`<type>(<scope>): <한국어 요약>` -> `git push -u origin <branch>`)
3. **GitHub PR 작성**: 영문 타이틀 + [`.github/pull_request_template.md`](.github/pull_request_template.md) 규격(Summary, Key Changes, Result, Checklist)에 맞춘 PR 생성(또는 원클릭 링크 및 본문 제공)

