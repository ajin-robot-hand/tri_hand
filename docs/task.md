# tri_hand 잔여 작업 점검표 (계획서 대비 갭 분석)

**점검일:** 2026-10-12 · **점검 범위:** `docs/eval.md`(개발 계획서) 대비 리포지토리 전체
**계획서상 현재 단계:** Phase 3 (HW 통합/조립, 2026.10–11) → 다음 관문은 Phase 4 검증(2026.12)

---

## 0. 지금 돌아가는 것 (실측 확인)

점검 중 실제로 실행해 확인한 결과입니다. 아래는 **문제 없음**으로 확인된 항목입니다.

| 항목 | 명령 | 결과 |
| :--- | :--- | :--- |
| MuJoCo 모델 컴파일 | `mujoco.MjModel.from_xml_path("src/scene.xml")` | 성공, `nu=7 / nq=7 / nbody=8` (7 DOF 일치) |
| 헤드리스 물리 검증 | `python src/run_sim.py --headless` | 8초 발산 없음, `max|qvel| ≤ 0.95 rad/s` |
| 유닛 테스트 | `python -m pytest tests` | **119 passed** |
| 위치 제어 응답 | `B_j2` 0→1.0 rad 스텝 | 정착 1.0013 rad, **오버슈트 0.2%** (kp=12 / kv=0.5 적정) |
| 정적 유지 오차 | 전 관절 `ctrl=0`, 중력 −Y | 오차 0.000 rad (링크 축과 중력이 평행해 모멘트 없음) |
| 실물 설정 ↔ 시뮬 일치 | `tests/test_real.py::test_config_ranges_match_sim` | `config.json` range == `ctrlrange` 자동 검증 중 |

> 재현 시: 테스트 실행에 `httpx`가 필요합니다. `requirements-dev.txt`로 분리돼 있으니 `pip install -r requirements.txt -r requirements-dev.txt`로 같이 설치하세요 (T-07 완료).

---

## 1. 계획서 KPI 대비 갭 매트릭스

계획서 [Page 5] 평가 지표를 기준으로, **현재 코드로 측정 가능한가**를 판정했습니다.

| KPI | 목표 | 현재 상태 | 판정 |
| :--- | :--- | :--- | :--- |
| **동시 제어 주기 50 Hz** | GroupSyncWrite 안정 구동, 지터 < 2 ms | GroupSync**Read**만 구현(`real/dxl.py:150`). 목표 쓰기는 관절별 `write1/2/4ByteTxRx` 7회 왕복(`real/server.py:160`). 50 Hz **주기 제어 루프 자체가 없음**(HTTP 요청 시에만 송신) | ⏳ Phase 4(12월) 예정 |
| **패킷 에러율 < 0.05%** | SDK RX 에러 카운터 회수 | `comm_error`에 **마지막 오류 문자열 1건만** 보관(`real/server.py:94`). 누적 카운터·총 패킷 수 없음 | ⏳ Phase 4(12월) 예정 |
| **시스템 가용률 ≥ 99%** | Hardware_Error 자동 Reboot 복구 포함 | 오류 **감지**는 됨(`hw_errors`, `real/dxl.py:65`). Dynamixel **Reboot(0x08) 명령 미구현**, 자동 복구 로직·다운타임 로그 없음 | ⏳ Phase 4(12월) 예정 |
| **파지 성공률 ≥ 90% (3종)** | Power / Pinch / Spherical 각 n≥30 | 프리셋 3종 **실물에서 정의·동작 확인 완료**(`presets.json`은 `.gitignore` 대상이라 리포에 없음). 시험도 실물에서 진행 — **파지 후 90° 회전, 3초 이상 유지 = 성공** 판정, 기록은 **사진**. 별도 기록 양식·통계 하네스는 두지 않음 | ⚠ 경량 수행 (의도적 범위 축소) |
| **DB 로깅 / ERD** | 지터·Position·Load·Temp 1 Hz 적재 | **DB·로깅 모듈 자체가 없음** (`sqlite`/ORM 의존성 0건). ERD 문서 없음 | ❌ 미착수 (Phase 1 산출물 지연) |
| **온도 ≤ 65 °C 듀티 사이클** | 1 Hz 샘플링 | `present_temperature`(`real/dxl.py:43`)는 `check.py`만 읽고, 서버 폴링 구간은 주소 70~135라 **온도·전압이 빠져 있음**(`real/server.py:126`) | ⚠ 반쪽 |
| **7 DOF 동시 제어** | 손가락 3×2 + 엄지 외전 1 | 구현 완료, 시뮬·실물 모두 7축 | ✅ |
| **Mock PortHandler** | Phase 1 산출물 | `PortHandler`가 아니라 **`Bus` 계층의 `FakeBus`**로 구현(`tests/test_real_server.py:29`). 기능적으로 동등하거나 더 낫다 | ✅ (계획서 문구만 수정) |
| **FK (순기구학)** | Phase 2 산출물 | 모듈 없음. 다만 MuJoCo가 FK를 대신 수행 중이므로 "MuJoCo FK로 대체"라고 쓸 수 있음 | ⚠ 문서 정리 |

**요약:** 하드웨어 제어·시뮬레이션·UI는 계획 이상으로 올라와 있습니다. KPI 4개는 아직 측정 수단이 없지만, 계획서 간트([Page 8])에서 24h 연속 구동·3종 파지 통계는 **④ 검증(2026.12) 산출물**이고 현재는 **③ HW 통합(2026.10–11)** 단계이므로 이는 *미달*이 아니라 *일정대로 미착수*입니다. 다만 ① `DB 로깅/ERD`는 **Phase 1 산출물이라 유일하게 실제 지연**이고, ② 계측 레이어 중 **`GroupSyncWrite`와 패킷 카운터는 지금 넣는 편이 유리**합니다(둘 다 `FakeBus`로 검증 가능하고, 7왕복→1패킷은 그 자체로 성능 개선). Reboot·가용률·24h 러너는 12월 범위로 둡니다.

> 계획서에 못 박힌 항목이라 임의 삭제 불가: `GroupSyncWrite`/50 Hz는 [Page 2 제어 스택]·[Page 4 목표]·[Page 5 KPI]·[Page 6 사양]·[Page 8 ② 산출물] 5곳, 패킷 에러율은 [Page 2]·[Page 5], 자동 Reboot는 [Page 2]·[Page 5] 외에 **[Page 4] 기대 효과에 "자동 Reboot 시스템으로 고가용률(99%) 달성"으로 선언**돼 있습니다. 범위를 줄이려면 코드가 아니라 `docs/eval.md`를 먼저 수정해야 합니다.

---

## 2. 프로그래밍 점검에서 나온 결함

### D-01. `Q_CLOSE` 주석이 실제 거동과 반대 (사실 오류)
`src/run_sim.py:18`의 주석은 *"이 값까지는 손가락끼리 안 부딪힘"*이라고 적혀 있으나, 실측하면 **완전 오므림에서 접촉 4개**가 발생합니다.

```
A_link2 ↔ B_link2  dist=-0.00016   (×2)
A_link2 ↔ C_link2  dist=-0.00017   (×2)
```

더 중요한 부수 효과: 이 간섭 때문에 `A_j1`이 **`forcerange` 한계 −1.4 N·m에 포화**하고 목표 −0.300 rad 대비 **정상상태 오차 −0.124 rad(약 7.1°)**가 남습니다.

| 관절 | 목표 | 실제 | 오차 | 액추에이터 힘 |
| :--- | ---: | ---: | ---: | ---: |
| `A_j1` | −0.300 | −0.176 | **−0.124** | **−1.400 (포화)** |
| `B_j1` | +0.300 | +0.253 | −0.047 | +0.569 |
| `C_j1` | +0.300 | +0.251 | −0.049 | +0.584 |

README는 이를 [issue #7]로 이미 알고 있으나, `run_sim.py` 주석은 반대로 말하고 있습니다. **실물에서 이 자세를 유지하면 XL430이 정지 토크로 계속 버티게 되어 과열(계획서 상한 65 °C)로 직결됩니다.** 계획서 듀티 사이클(정적 파지 30 s)과 충돌하므로 24h 시험 전에 반드시 정리해야 합니다.

### D-02. 목표 송신이 GroupSyncWrite가 아니다 (계획서 명시 사항 위반)
`real/server.py:176 set_targets()`는 관절마다 `bus.write()`를 호출하고, 각 호출은 **상태 패킷을 기다리는 TxRx 왕복**입니다. 7관절 = 7왕복. 여기에 20 ms 주기 폴링 스레드가 같은 `RLock`으로 버스를 공유합니다(`real/server.py:468`). 1 Mbps + FTDI latency를 감안하면 50 Hz에서 지터가 커지는 구조이며, 계획서가 지정한 GroupSyncWrite(응답 없는 단일 패킷)로 바꾸면 7왕복 → 1패킷이 됩니다.

### D-03. 폴링이 불필요한 레지스터를 과하게 읽고, 필요한 것은 빼먹는다
`real/server.py:126`은 주소 70~135(**66 바이트/모터**)를 20 ms마다 읽습니다. 이 구간에는 `goal_position`, `profile_velocity`, `position_p_gain` 등 **변하지 않는 값**이 포함됩니다. 반면 KPI에 필요한 `present_temperature`(146)·`present_input_voltage`(144)는 **구간 밖이라 못 읽습니다**. 상태 응답의 `hw_errors`는 있지만 온도가 없어 대시보드로 열 감시가 불가능합니다.

### D-04. `/grasp` 단독으로는 3종 그립이 안 됨 → **프리셋으로 이미 해결됨**
`real/server.py` `/grasp`와 `src/server.py` `/grasp`는 `close_sign × Q_CLOSE × amount`를 세 손가락에 **균등 적용**하므로 그 자체로는 Power 1종만 표현합니다. 다만 Pinch·Spherical은 **`/presets` 기능(`src/server.py:353`~)으로 이미 실물에서 정의·동작 확인이 끝났습니다.** 저장 파일 `presets.json`이 `.gitignore` 대상이라 리포지토리에서 보이지 않을 뿐이므로 **코드 작업은 필요 없습니다.** 평가 서류에만 "3종 그립은 프리셋으로 제공"이라고 쓰면 됩니다.

### D-05. README의 사실 오류 (평가 서류로 그대로 못 씀)
- `README.md:51`, `README.md:303`: **존재하지 않는 `tutorial/` 디렉터리**를 핵심 기능·구조도에 명시 (`0e6a84f chore: remove unnecessary files`에서 삭제됨)
- `README.md:216`, `README.md:251`: 링크가 **다른 사람 로컬 절대경로** `file:///home/erdos/workspace/...` — 클론한 사람에게 깨진 링크
- `README.md:264`: 실물 `kp` 허용 범위를 **0~100**이라 적었으나, 실제 `real/server.py`는 `GAIN_MAX = 16383`(XL430 레지스터 범위). 대시보드는 `/limits`를 읽어 정상 동작하므로 **문서만 틀림**
- 아키텍처 Mermaid의 공용 API를 `/status, /target`으로 적었으나 실제 엔드포인트는 `/state, /joints`
- `docs/`를 "이론 배경 학습 자료"라 적었으나 실제 내용은 계획서·데모 GIF·스펙 문서

### D-06. 계획서(`docs/eval.md`) 자체의 정리 필요 항목
- L26, L83: 파지 성공률 검증 방법이 **"권종별 반복 파지"** — 지폐(권종) 용어가 남아 있습니다. "그립 유형별"로 수정.
- L18: 제어 스택에 `GroupBulkRead`라 적혀 있으나 구현은 `GroupSyncRead`.
- L32: "전축 단일 모델화" → "전 축".
- L27: "0.05% 미만"과 L84 "< 0.05%"는 일치하나, L27 표기가 "미만"/"미만" 혼용.

### D-07. 테스트 의존성이 `requirements.txt`에 없다
`fastapi.testclient`는 `httpx`를 요구하는데 `requirements.txt`에 없습니다. 깨끗한 환경에서 `pytest tests`가 **수집 단계에서 2개 파일 에러**로 죽습니다(실측). README는 `pip install pytest httpx`를 따로 안내하지만, 평가자가 requirements만 설치하면 재현 실패합니다.

---

## 3. 작업 목록

우선순위: **P0 = 오늘·내일 안에 반드시**, **P1 = 가능하면 내일까지**, **P2 = Phase 4(12월) 전까지**

### P0 — 오늘·내일 (문서 정합성 + 평가 서류, 코드 리스크 없음)

- [x] **T-01** `README.md` 사실 오류 5건 수정 (D-05)
  - `tutorial/` 언급 2곳 삭제, `file:///home/erdos/...` → 리포 상대경로, 실물/시뮬 `kp`·`kv` 범위를 열로 분리해 정정(실물 0~16383, 시뮬 kp 0~100/kv 0~5), Mermaid API 이름을 `/state`·`/joints`·`/velocities`·`/torque`·`/presets`로(+`/reset`은 시뮬 전용 표기), `docs/` 설명 현실화
  - *완료 기준:* README에 등장하는 모든 경로·엔드포인트·수치가 리포지토리와 일치 — 충족 (commit `28da75d`)
- [x] **T-02** `docs/evaluation.md` 신설 — **평가 요소 정리 서류** (§4 구성안 참조)
  - *완료 기준:* 계획서 4개 KPI마다 ①측정 정의 ②측정 도구/명령 ③현재 달성도 ④판정 근거 파일이 한 줄로 추적됨 — 충족, §4~6(리스크 등록부·시뮬↔실물 대응표·범위 밖 선언)까지 포함 (commit `8cdfbd2`)
- [x] **T-03** `src/run_sim.py:18` 주석 정정 + 간섭 수치 명문화 (D-01)
  - 주석을 "완전 오므림에서 A가 B·C와 접촉하며 `A_j1`이 토크 포화된다(issue #7)"로 교체하고, `docs/evaluation.md`의 리스크 항목에 과열 위험으로 등재
  - *완료 기준:* 주석과 실측(`ncon=4`, `A_j1` −1.4 N·m)이 모순되지 않음 — 충족, 헤드리스로 재측정(`ncon=4`, 오차 −0.125 rad)해 반영 (commit `0f1f6fe`)
- [x] **T-04** `docs/eval.md` 용어 정정 (D-06) — "권종별"→"그립 유형별", `GroupBulkRead`→`GroupSyncRead`, "전축"→"전 축" (commit `f094492`, KPI 수치는 변경하지 않음)
- [x] **T-07** `requirements.txt`에 테스트 의존성 분리 추가 (D-07) — `httpx`, `pytest` (또는 `requirements-dev.txt`)
  - *완료 기준:* 새 venv에서 `pip install -r requirements.txt && pytest tests` → 104 passed — 충족, `requirements-dev.txt` 신설(`-r requirements.txt`가 아니라 별도 파일로 분리, README에 두 파일 함께 설치하도록 안내) (commit `9f6dd5f`)
- [x] **T-16** pytest 통과 개수 표기 최신화 (§0 표·§4 구성안 "104 passed" → "106 passed") + httpx 재현 안내 갱신
  - T-08~T-10 커밋(`6494eab`)이 테스트 2개를 추가하면서 §0 요약표·§4 구성안의 숫자와 "httpx가 requirements.txt에 없음" 경고(T-07 완료로 이미 해소)가 갱신되지 않고 남아 있던 것을 발견해 수정
  - *완료 기준:* `~/mujoco_env/bin/python -m pytest tests` 재실행 결과(106 passed)와 문서 표기가 일치, T-07 완료 상태를 반영한 재현 안내로 교체 — 충족

> **제외됨 (2026-10-12 판단):** 3종 그립 프리셋 정의와 파지 성공률 시험 절차서는 작업 목록에서 **뺍니다.**
> - 프리셋은 **이미 실물에서 3종 모두 정의·동작 확인 완료**. 저장 위치인 `presets.json`은 `.gitignore` 대상(`.gitignore:21-22`)이라 리포지토리에 보이지 않을 뿐입니다.
> - 파지 성공률도 **실물에서 이미 시험 완료**: 파지 후 **90° 회전시켜 3초 이상 유지되면 성공**으로 판정. 기록은 **실물 사진**이고 별도 양식·통계 하네스는 두지 않았습니다.
> - 사유: MuJoCo가 실물과 동일한 접촉 환경이 아니므로 시뮬레이션 쪽 파지 재현/통계화는 투입 대비 효용이 낮다고 보고 **의도적으로 가볍게 진행**한 항목입니다.

### P1 — 내일까지 여력이 되면 (계측의 최소 뼈대)

- [x] **T-08** `real/dxl.py`에 **GroupSyncWrite** 추가 + `Hand.set_targets`가 이를 사용 (D-02)
  - `Bus.sync_write(name, {id: value})` 형태, 응답 대기 없음. 호출 하나(`/joints`, `/velocities`, `/grasp`, 프리셋 적용)의 전 관절이 같은 레지스터(위치 또는 속도)인 것을 `_require`가 보장하므로 혼합 호출은 발생하지 않음
  - *완료 기준:* `FakeBus`에 `sync_write` 추가 + 기존 테스트 통과 + "7관절 1패킷, 개별 `goal_position` 왕복 0건" 테스트(`test_targets_sent_as_single_sync_write`) 추가 — 충족
- [x] **T-09** 폴링 구간 정정 (D-03): 상태 폴링은 `present_load`~`present_position`(126~135, 10 B)로 좁히고, **온도/전압/hw_error는 1 Hz 별도 폴링(`poll_slow`)**으로 분리. `/state`에 `temperatures`, `voltages` 추가
  - *완료 기준:* 대시보드 카드에 관절별 온도 표시, 20 ms 폴링 1회당 전송량이 66 B → 10 B/모터 — 충족. 1 Hz 쪽은 `hardware_error_status`~`present_temperature`(77 B) 단일 구간을 그대로 읽음 — 1 Hz에서는 바이트 수보다 구현 단순성이 우선이라는 판단(의도적, 오버엔지니어링 아님)
  - ⚠ `test_poll_errors`가 `poll()`/`poll_slow()` 분리에 맞게 재작성됨(기존 로직은 그대로, 호출만 나눔)
- [x] **T-10** **패킷 통계 카운터**: `Bus`에 `tx_count` / `rx_error_count`를 두고 `/state`로 노출 (D-02 KPI)
  - 별도 `/stats` 엔드포인트는 만들지 않음 — 대시보드가 이미 `/state`를 폴링하므로 거기에 `packets: {tx, rx_errors}`로 추가하는 편이 더 단순함
  - *완료 기준:* 24h 시험 없이도 `에러/총 패킷` 비율이 API 한 번으로 읽힘(`test_packet_stats_exposed_in_state`) — 충족. ⚠ 프로세스 재시작 시 0으로 리셋되는 인메모리 값(영속화는 T-12 DB 몫, 지금 끌어오지 않음)

### P2 — Phase 4(2026.12) 검증 전까지

- [x] **T-11** 50 Hz 제어 루프 + 지터 측정 (`monotonic_ns` 기준 주기 편차 기록). 계획서 판정 조건: 지터 < 2 ms, 누락 프레임 < 0.1%
  - `poll_loop`를 고정 데드라인 스케줄러로 바꿔 드리프트를 없애고, `LoopStats`가 매 주기 편차를 0.1 ms 히스토그램으로 누적(24h·50 Hz 샘플 수백만 개라 메모리 고정). `/state`의 `loop`에 `hz/jitter_ms_p95/dropped_frac` 노출
  - *범위 축소(합의):* 목표 **송신은 지금처럼 HTTP 요청 때만** — 루프는 폴링+지터 측정만. "GroupSyncWrite 50 Hz 상시 구동"은 실물 검증 때 재논의
- [x] **T-12** ~~SQLite 로깅 + DB ERD 문서~~ → **CSV 로깅**(`real/runlog.py`)으로 범위 축소(합의). Phase 1 산출물 지연 해소
  - 계획서 [Page 5] 샘플링 요구는 *Position / Load / Temperature 1 Hz + 패킷 에러 이벤트 상세*뿐이므로 append-only CSV 3종으로 충족: `joint_sample.csv`(1 Hz) + `error_event.csv`(통신/HW/Reboot) + `run.csv`(지터·패킷 에러율·가용률 스냅샷, ERD 대신 메타 행)
  - 서버 `--log DIR`로 opt-in. 매 write flush라 24h 중 크래시해도 측정이 남음(인메모리 카운터 리셋 한계를 영속 로그로 덮음)
  - *완료 기준:* ~~ERD 1장~~ CSV 스키마 표 + `joint_sample`에 온도가 들어옴(**T-09는 `poll_slow`가 이미 폴링 중이라 충족**)
- [x] **T-13** Dynamixel **Reboot(0x08)** 구현 + Hardware_Error 자동 복구 (5초 내 복귀 성공 판정) + 다운타임 누적 → 가용률 산출
  - `Bus.reboot()` 래퍼 + `Hand.check_recovery()`(1 Hz): 장애 감지 → reboot → 복귀 성공/실패 판정, reboot 후 운영 모드·게인·토크·목표 **재설정**(`_restore`). `/state`에 `availability/downtime_s/reboots` 노출, `--no-recover`로 끌 수 있음
- [x] **T-14** 24h 연속 구동 러너 (`real/endurance.py`, 5분 주기 3종 그립 순환, 정적 30 s / 오픈 90 s 듀티, 온도 65 °C 초과 시 자동 중단)
  - HTTP로 서버 제어(의존성 없이 stdlib `urllib`), 프리셋은 `/presets`에서 동적으로 읽어 순환. 종료 시 최고 온도·패킷 에러율·지터·가용률 요약 출력
  - **주의:** T-11~T-14 모두 `FakeBus` 단위 테스트까지만 완료 — 실물 24h 구동·실제 Reboot 검증은 Phase 4(12월) 몫
- [ ] **T-15** *(선택)* 파지 성공률 자동 집계 스크립트 (시행 기록 → 유형별 성공률·신뢰구간) — 실물 시험을 사진 기록으로 가볍게 끝내기로 했으므로 **필수 아님**. 계획서 `n≥30` 통계를 서류로 요구받을 때만 착수

---

## 4. 평가 요소 서류 구성안 (`docs/evaluation.md`)

README는 "어떻게 쓰는가"를 담고 있으니, **"계획서 약속을 어디까지 지켰는가"**는 별도 문서로 분리하는 편이 평가자에게 읽히기 좋습니다. 아래 골격을 제안합니다.

1. **평가 지표 추적표** — 계획서 KPI 4개 × (목표 / 측정 정의 / 측정 명령 / 현재값 / 판정 / 근거 파일·커밋)
2. **달성 근거** — 재현 명령과 그 출력 (XML 컴파일, `pytest 119 passed`, 헤드리스 발산 없음, 스텝 응답 0.2% 오버슈트)
3. **미달 항목과 사유** — 계측 레이어 부재를 숨기지 않고 T-11~T-15로 연결
4. **리스크 등록부** — ① 완전 오므림 시 A↔B·C 자가 간섭과 `A_j1` 토크 포화 → 과열 위험(issue #7) ② 7왕복 쓰기로 인한 50 Hz 지터 ③ 실물 바깥쪽 가동한계 미측정(합 86° 는 시뮬 합의값일 뿐)
5. **시뮬 ↔ 실물 대응표** — 같은 API를 쓰지만 **게인 단위가 다름**(시뮬 `kp` N·m/rad vs 실물 Position P Gain 레지스터). 평가자가 가장 오해하기 쉬운 지점이므로 명시
6. **범위 밖 선언** — IK(계획서상 Phase 5 스트레치), 전류 제어 모드, 접촉 센서(`contacts: null`)

---

## 5. 오늘·내일 추천 진행 순서

1. **T-01 → T-04** (문서 정합성, 30~60분): 틀린 사실을 먼저 없앤다. 평가 서류가 틀린 README를 인용하면 전부 틀어진다.
2. **T-07** (5분): 평가자가 테스트를 재현할 수 있게 만든다.
3. **T-02** (반나절): 위 결과를 모아 `docs/evaluation.md` 작성. 3종 그립과 파지 시험은 **이미 실물에서 끝난 일**이므로, 새로 만들 것 없이 판정 기준(90° 회전 3초 유지)과 사진 기록을 근거로 적으면 된다.
4. 여력이 남으면 **T-08 → T-10**. T-11~T-15는 분량상 오늘·내일 범위가 아니며, 12월 Phase 4 일정으로 남겨 두는 것이 정직하다.
