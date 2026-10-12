# tri_hand 평가 요소 정리 서류

**작성일:** 2026-10-12 · **기준 커밋:** `feat/eval-tasks` (T-01~T-07 적용 후) · **계획서:** [`docs/eval.md`](eval.md) · **갭 분석:** [`docs/task.md`](task.md)

이 문서는 "README는 어떻게 쓰는가, `evaluation.md`는 계획서([docs/eval.md](eval.md)) 약속을 어디까지 지켰는가"를 분리해 다룹니다. 수치는 모두 이 저장소에서 재실행해 얻은 출력이며, 추정값에는 그 사실을 명시합니다.

---

## 1. 평가 지표 추적표

계획서 [Page 5] 4대 KPI 기준입니다.

| KPI | 목표 | 측정 정의 | 측정 도구/명령 | 현재값 | 판정 | 근거 파일·커밋 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **동시 제어 주기 50 Hz** | GroupSyncWrite 안정 구동, 지터 < 2 ms, 누락 프레임 < 0.1% | 50 Hz 루프에서 `monotonic_ns` 기준 주기 편차를 기록 | `/state`의 `loop`(`LoopStats`), 24h 수치는 `run.csv` | 목표 송신은 `GroupSyncWrite` 1패킷으로 전환됨(T-08). 50 Hz 고정 데드라인 루프 + 지터 측정 **구현·단위테스트 완료**(T-11, `jitter_ms_p95`/`dropped_frac` 노출). **실물 24h 지터 수치는 미측정** — 송신은 HTTP 요청 때만(측정만 하는 범위로 합의) | ⏳ 측정 수단 완비, 실물 수치는 Phase 4(12월) | `docs/task.md` T-08/T-11 |
| **파지 성공률 ≥ 90% (3종)** | Power/Pinch/Spherical 각 n≥30, 판정 기준 적용 | 실물에서 그립 적용 후 유지 시험 | 실물 하드웨어 (`/presets`, [src/server.py:353](../src/server.py#L353)) | 3종 프리셋 **실물에서 정의·동작 확인 완료**. 판정 기준은 계획서 n≥30·5초 유지가 아니라 **파지 후 90° 회전, 3초 이상 유지 = 성공**으로 경량화해 적용. 기록은 사진, 별도 통계 하네스 없음 | ⚠ 경량 수행 (의도적 범위 축소, `docs/task.md` §3 제외 사유 참조) | `docs/task.md` D-04, §3 "제외됨" |
| **패킷 에러율 < 0.05%** | SDK RX 에러 카운터를 24h 누적해 총 패킷 대비 비율 산출 | `/state`의 `packets.{tx,rx_errors}`, 24h 누적은 `run.csv`의 `packet_error_rate` | 누적 `tx_count`/`rx_error_count` 카운터(T-10) + CSV 영속화(T-12) **구현 완료**. 인메모리 값은 재시작 시 리셋되나 `run.csv` 스냅샷으로 24h 비율이 남음. **실물 24h 수치는 미측정** | ⏳ 측정 수단 완비, 실물 수치는 Phase 4(12월) | `docs/task.md` T-10/T-12 |
| **시스템 가용률 ≥ 99%** | Hardware_Error 자동 Reboot 포함 Downtime/Total time | `/state`의 `availability`/`downtime_s`/`reboots`, 24h는 `run.csv` | Reboot(0x08) 래퍼 + 자동 복구(5초 내 복귀 판정) + 다운타임 누적 → 가용률 산출 **구현·단위테스트 완료**(T-13). reboot 후 모드/게인/토크/목표 재설정 포함. **실물 복구 성공 검증은 미실시** | ⏳ 측정 수단 완비, 실물 수치는 Phase 4(12월) | `docs/task.md` T-13 |

> 계획서 간트([Page 8])에서 24h 연속 구동·3종 파지 통계는 **④ 검증(2026.12)** 산출물이고 현재는 **③ HW 통합(2026.10–11)** 단계이므로, 위 KPI의 ⏳ 표시는 *미달*이 아니라 *일정대로 미착수*입니다. 50 Hz 지터·패킷 에러율·가용률의 **측정/복구/로깅 레이어는 이제 모두 구현·단위테스트까지 완료**(T-11~T-14)되어, 남은 것은 실물 24h 구동으로 수치를 채우는 일뿐입니다. DB 로깅은 계획서 Phase 1 산출물 지연이었으나 **CSV 로깅(T-12)으로 해소**했습니다(아래 범위 축소 참조).

---

## 2. 달성 근거 (재현 명령과 출력)

모두 `~/mujoco_env/bin/python`으로 재실행해 확인했습니다.

**모델 컴파일**
```
$ python -c "import mujoco; m = mujoco.MjModel.from_xml_path('src/scene.xml'); print(f'nu={m.nu} nq={m.nq} nbody={m.nbody}')"
nu=7 nq=7 nbody=8
```
7 DOF(손가락 3×2 + 엄지 외전 1) 설계와 일치.

**유닛 테스트**
```
$ python -m pytest tests -q
119 passed, 1 warning in 3.43s
```
(경고 1건은 `starlette.testclient`의 `httpx` deprecation 안내이며 테스트 실패 아님)

**헤드리스 물리 검증**
```
$ python src/run_sim.py --headless
...
✅ 헤드리스 시뮬레이션 검증 완료 (수치 안정성 및 발산 없음)
```
8초간 `max|qvel| ≤ 0.95 rad/s`, 발산 없음.

**위치 제어 스텝 응답** (`B_j2` 0→1.0 rad, kp=12/kv=0.5)
```
target=1.0  peak=1.0020  final(settled)=1.0013  overshoot=0.195%
```
오버슈트 0.2% 수준, 게인이 적정함을 재확인.

**정적 유지 오차** (전 관절 `ctrl=0`, 중력 `-Y`, 5초)
```
static hold: max|qpos|=0.000000  max|qvel|=0.000000
```
링크 축과 중력이 평행해 모멘트가 걸리지 않으므로 오차 0.

**완전 오므림 자가 간섭 재측정** (`src/run_sim.py` T-03 참조)
```
t=8.000s  ncon=4
  contact: body A_link2 <-> body B_link2  dist=-0.000157 (x2)
  contact: body A_link2 <-> body C_link2  dist=-0.000166 (x2)
A_j1: target=-0.3000 actual=-0.1747 err=+0.1253 force=-1.4000 (saturated)
B_j1: target=+0.3000 actual=+0.2540 err=-0.0460 force=+0.5519
C_j1: target=+0.3000 actual=+0.2527 err=-0.0473 force=+0.5670
```
`docs/task.md` D-01의 수치(접촉 4개, `A_j1` −1.4 N·m 포화, 오차 약 −0.125 rad)와 일치. §4 리스크 등록부 ①에 반영.

**실물 설정 ↔ 시뮬 일치**
```
tests/test_real.py::test_config_ranges_match_sim  — PASS (119건 중 1건)
```
`real/config.json`의 `range`와 시뮬 `ctrlrange`가 자동 검증 중.

---

## 3. 계측 레이어 현황과 남은 일

계측·복구·로깅 레이어는 모두 구현되어 `FakeBus` 단위테스트까지 통과합니다. 남은 것은 실물 24h 구동으로 수치를 채우는 검증(Phase 4)과 선택 항목입니다.

| 항목 | 상태 | 비고 | 연결 작업 |
| :--- | :--- | :--- | :--- |
| GroupSyncWrite (목표 송신) | ✅ 구현 | 7왕복 → 1패킷 전환 | T-08 |
| 패킷 에러율 계측 | ✅ 구현 | 누적 tx/rx 카운터 + `run.csv` 영속화 | T-10, T-12 |
| 온도/전압 폴링 | ✅ 구현 | `poll_slow`가 1 Hz로 70~146 구간을 읽음(주소 144/146 포함) | T-09 |
| 50 Hz 루프 + 지터 측정 | ✅ 구현 | 고정 데드라인 루프 + `LoopStats`. 송신은 HTTP 때만(측정만 범위로 합의) | T-11 |
| CSV 로깅 | ✅ 구현 | `joint_sample`/`error_event`/`run` 3종. SQLite+ERD 대신 CSV로 범위 축소(합의) | T-12 |
| Reboot 자동 복구 / 가용률 | ✅ 구현 | `Bus.reboot` + 5초 복귀 판정 + 다운타임 누적. reboot 후 설정 재적용 | T-13 |
| 24h 연속 구동 러너 | ✅ 구현 | `real/endurance.py`, HTTP 제어, 65 °C 자동 중단 | T-14 |
| **실물 24h 수치 채우기** | ⏳ Phase 4 | 위 레이어로 지터·패킷 에러율·가용률 실측 — 12월 | T-11~T-14 검증 |
| 파지 성공률 자동 집계 | ⚠ 선택 | 실물 시험을 사진 기록으로 경량화, 통계 하네스는 필수 아님 | T-15 (선택) |

---

## 4. 리스크 등록부

| # | 리스크 | 상세 | 완화/추적 |
| :--- | :--- | :--- | :--- |
| ① | 완전 오므림 시 자가 간섭 → 토크 포화 → 과열 위험 | `Q_CLOSE`(j1=0.3, j2=1.2 rad) 완전 오므림에서 `A_link2`가 `B_link2`·`C_link2`와 접촉(ncon=4), `A_j1`이 forcerange −1.4 N·m에 포화돼 목표 대비 약 −0.125 rad(≈7°) 정상상태 오차. 실물에서 이 자세를 정적으로 유지하면 XL430이 정지 토크로 계속 버티며 과열(계획서 상한 65°C)로 직결 | [issue #7], `src/run_sim.py` 주석 정정(T-03) 완료. 코드상 `Q_CLOSE` 값 자체는 변경하지 않음(거동 변경은 범위 밖) |
| ② | 7왕복 쓰기로 인한 50 Hz 지터 | `real/server.py` `set_targets()`가 관절마다 `bus.write()`를 호출(응답 대기 TxRx), 7관절=7왕복. 20ms 폴링 스레드와 같은 `RLock`을 공유해 지터 가중 | GroupSyncWrite 전환(T-08)으로 7왕복→1패킷 |
| ③ | 실물 바깥쪽 가동한계 미측정 | 합 86°는 **시뮬 합의값**일 뿐 실물 측정값이 없음 — 실물에서 바깥쪽 한계를 재본 기록이 없음 | 실물 캘리브레이션 시 바깥쪽 한계 실측 필요 |

---

## 5. 시뮬 ↔ 실물 대응표

같은 REST API(`/state`, `/joints`, `/velocities`, `/torque`, `/presets`)를 쓰지만, **게인의 단위가 다릅니다.** 평가자가 가장 오해하기 쉬운 지점이므로 명시합니다 (README [입력 허용 범위 및 제어 스펙](../README.md#입력-허용-범위-및-제어-스펙) 절과 동일 내용).

| 항목 | 시뮬레이션 (`src/server.py`) | 실물 (`real/server.py`) |
| :--- | :--- | :--- |
| `kp` 단위 | `N·m/rad` (MuJoCo position actuator 게인) | XL430 Position P Gain **레지스터 값**(무단위 정수) |
| `kp` 범위 | 0 초과 ~ 100 | 0 초과 ~ 16383 (`GAIN_MAX`) |
| `kv` 단위 | `N·m·s/rad` | XL430 Position D Gain **레지스터 값** |
| `kv` 범위 | 0 ~ 5 | 0 ~ 16383 (`GAIN_MAX`) |
| 목표 각도 범위 | `ctrlrange` 동일 | `ctrlrange` 동일 |
| 토크 한계 | 0 초과 ~ 1.4 N·m | 0 초과 ~ 1.4 N·m |

같은 숫자를 양쪽에 입력해도 물리적 의미가 다르므로, 시뮬에서 튜닝한 `kp=12`를 실물 레지스터에 그대로 넣으면 안 됩니다.

---

## 6. 범위 밖 선언

다음은 이번 평가 범위(Phase 3, 2026.10–11)에 포함하지 않습니다.

- **IK (역기구학)** — 계획서상 Phase 5 스트레치 목표. FK는 MuJoCo가 대신 수행 중("MuJoCo FK로 대체").
- **전류 제어 모드** — 현재는 위치 제어 모드만 구현·검증.
- **접촉 센서** — `contacts: null`, 접촉력 피드백 기반 그립 제어는 범위 밖.
- **3종 그립 성공률의 시뮬레이션 재현/통계화** — MuJoCo가 실물과 동일한 접촉 환경이 아니므로 투입 대비 효용이 낮다고 판단해 의도적으로 가볍게 진행(§1 참조). 실물 시험(90° 회전 3초 유지, 사진 기록)으로 대체.
