# 액추에이터 직접구동 방식 3지 로봇 핸드 개발 계획서

**일자:** 2026.08.12  
**작성:** 김연준, 이보람, 조인철  

---

## [Page 2] 프로젝트 개요 (Project Overview)

### 주요 정보

| 구분 | 내용 | 비고 |
| :--- | :--- | :--- |
| **개발 기간** | 2026년 7월 ~ 2027년 2월 (총 8개월) | 5개 단계 |
| **구동 방식** | 액추에이터 직접구동 방식 (Direct-Coupled) | 관절 직접 연결, 직접 제어성 확보 |
| **자유도 구성** | 7 DOF = 손가락 3개 × 2 DOF (MCP + PIP) + 엄지 외전 1 DOF | Power / Pinch / 구형 파지 대응(예상) |
| **액추에이터 확정** | XL430-W250-T 7축 단일 모델 | 스페어 7개 포함 |
| **제어 스택** | DYNAMIXEL SDK (Python), DYNAMIXEL Wizard 2.0, GroupSyncWrite / GroupBulkRead | FastAPI + DB 로깅 연동 |
| **협업 환경** | GitHub, Mock PortHandler, Control Table 레지스터맵, DB ERD 문서화 | |

### 목표 지표

| 지표 | 목표값 | 검증 방법 |
| :--- | :--- | :--- |
| **동시 제어 주기** | 50 Hz (7관절 GroupSyncWrite 안정 구동) | 주기 지터 로그 DB 저장 확인 |
| **파지 성공률** | 90% 이상 (3종 시나리오) | 권종별 반복 파지 통계 |
| **패킷 에러율** | 0.05% 미만 (24시간 연속 구동 상태) | SDK RX 에러 카운터 회수 |
| **시스템 가용률** | 99% 이상 (Hardware_Error 자동 복구(Reboot) 포함) | Downtime / Total time 로그 |

> **전제 요약**
> * 보드레이트 1Mbps 및 USB latency 1ms 설정 필수
> * XL430-W250-T 전축 단일 모델화로 스페어 관리·제어 테이블·펌웨어 단일화. 
> * 파지 대상 물체는 XL430의 힘 버짓(Force Budget) 안으로 정의한다.

---

## [Page 3] 추진 배경 및 필요성 (Background & Motivation)

### Manipulator 형태 비교

#### 2지 그리퍼 (2-Finger Gripper)
* **강점:** 구조 단순, 제어 용이, 저비용, 성숙한 기술
* **한계:** 비정형 물체 파지 취약, 접촉면 부족으로 안정성 낮음

#### 3지 직접구동 (3-Finger Direct-Coupled) - **본 프로젝트**
* **강점:** 3점 접촉으로 파지 안정, 구조·제어 균형, 형상 다양성 대응
* **한계:** 5지 대비 정밀 조작 한계
* **선택 근거:**
    1. **구조 단순:** 관절 수, 부품 수가 적어 유지보수 용이. 3D 프린팅으로 자체 제작 가능.
    2. **파지 안정성:** 3점 접촉으로 구형·원통형 물체에 강한 파지력 확보.
    3. **제어 균형:** 7 DoF 수준으로 실시간 동시 제어 가능. 5지 대비 소프트웨어 부담 낮음.

#### 5지 휴머노이드 (5-Finger Humanoid)
* **강점:** 사람 손 유사 (다양한 자세), 정밀 조작 가능
* **한계:** 제어 복잡, 비용 고가, 신뢰성 확보 어려움

---

## [Page 4] 프로젝트 목표 및 기대 효과 (Objectives & Expected Outcomes)

### 프로젝트 목표
* **파지 성공률 (Grasp Success Rate):** 90% 이상
* **시스템 가용률 (System Uptime):** 99% 이상
* **동시 제어 (Concurrent Control):** 7 DOF, 50 Hz GroupSyncWrite 안정 구동 (주기 지터 $< 2 \text{ ms}$)

### 기대 효과
1. **산업적 효과 (Industrial Impact)**
   * 저비용 액추에이터(XL430)와 소프트웨어 기반 내구성 보완 전략으로, 저중량 물체 이송 작업의 비용 효율적 자동화 가능성 검증.
   * 향후 관절 각도·부하·성공률 등의 시행 데이터를 구조화하여 로깅한다면, Physical AI 학습을 위한 저비용 데이터 수집 플랫폼으로도 확장 가능.
2. **운영적 효과 (Operational Impact)**
   * 자동 Reboot 시스템으로 고가용률(99%) 달성.
   * 현장 점검 소요 최소화 및 무인 운영 시간 확장.

---

## [Page 5] 평가 지표

### KPI 요약

| KPI | 목표 값 | 측정 도구 | 판정 조건 |
| :--- | :--- | :--- | :--- |
| **동시 제어 주기** | 50 Hz GroupSyncWrite 안정 구동 | 주기 지터 로그 (µs 단위) → DB | 24h 로그에서 지터 $< 2\text{ms}$, 누락 프레임 $< 0.1\%$ |
| **파지 성공률** | $\ge 90\%$ (3종 시나리오) | 권종별 반복 시행 ($n \ge 30$) 통계 | 각 유형별 성공률 $\ge 90\%$ (5초 유지 조건) |
| **패킷 에러율** | $< 0.05\%$ (24h 연속) | SDK RX Error Counter 회수 | 24h 연속 구동 후 총 패킷 대비 오류 비율 |
| **시스템 가용률** | $\ge 99\%$ (자동 복구 포함) | Downtime / Total time 로그 | Hardware_Error Reboot 자동 복구 성공 포함 계산 |

### 연속 구동 테스트 세부 사항 (패킷에러율, 시스템 가동률 세부 사항)

| 항목 | 세부사항 |
| :--- | :--- |
| **구동 시나리오** | 50 Hz 제어 루프 유지, 5분 주기로 3종 그립 순환 |
| **듀티 사이클** | 정적 파지 30s + 오픈 90s (Present Temperature $\le 65^{\circ}\text{C}$ 유지 목적) |
| **환경 조건** | 실내 상온 ($20\sim26^{\circ}\text{C}$), 벤치 고정, 가외 변인 통제 |
| **샘플링** | Position / Load / Temperature 1 Hz, 패킷 에러 이벤트 발생 시 상세 로그 |
| **자동 복구** | Hardware_Error 감지 → Reboot 5초 이내 정상 복귀 시 성공으로 계산 |
| **실패 처리** | 복구 실패 3회 연속 시 테스트 중단, 원인 분석, 재실행 |

---

## [Page 6] 제품 사양 (Specification)

### 시스템 및 액추에이터 사양

| 항목 (시스템 사양) | 사양 | 항목 (XL430-W250-T 사양) | 값 |
| :--- | :--- | :--- | :--- |
| **자유도** | 7 DoF (손가락 3×2 + 엄지 외전 1) | **Stall Torque** | 1.4 Nm @ 11.1 V |
| **서보 수량** | XL430-W250-T × 7축 (+스페어 7) | **무부하 속도** | 57 rev/min @ 11.1 V |
| **통신** | DYNAMIXEL Protocol 2.0 (TTL 1 Mbps) | **해상도** | 4,096 pulse/rev (0.088°/pulse) |
| **제어 주기** | 50 Hz (GroupSyncWrite) | **감속비** | 258.5:1 |
| **전원** | SMPS 12V 5A, U2D2 Power Hub | **무게/크기** | 57.2 g, 28.5 x 46.5 x 34 mm |
| **프레임** | 3D 프린팅 (PLA / TPU) | **입력 전압** | 6.5~12.0V (권장 11.1V) |
| | | **동작 온도** | $-5 \sim +72 ^{\circ}\text{C}$ (실사용 상한 $65^{\circ}\text{C}$) |

### 파지 성능
* **대상 무게/크기:** 200 g / $24 \sim 80 \text{ mm}$
* **검증 예정 3종 그립:** Power, Pinch, Spherical (각 30회 반복으로 통계 산출)

---

## [Page 7] 시스템 아키텍처 (System Architecture)

**데이터/제어 흐름도:**

1. **USER / OPERATOR INTERFACE**
   * GUI Controls
   * *(Target Selection and Start Command)* $\rightarrow$
2. **UPPER CONTROL SYSTEM (PC)**
   * Target Grasping Profile DB
   * 7-DOF Hand Controller Engine
   * *(API call)* $\rightarrow$
   * DYNAMIXEL SDK (Python Wrapper)
     * $\rightarrow$ SyncWrite / SyncRead Handlers
     * $\rightarrow$ Protocol 2.0 Packet Generator
3. **HARDWARE ACTUATOR SYSTEM**
   * 7-DOF 3-Finger Robot Hand (ID 1-7)
     * $\rightarrow$ Finger 1 Actuators
     * $\rightarrow$ Finger 2 Actuators
     * $\rightarrow$ Finger 3 Actuators

---

## [Page 8] 개발 로드맵 (5-Phase Roadmap, 8 Months)

### 간트 차트 (일정표)

| 단계 | 2026.07 | 2026.08 | 2026.09 | 2026.10 | 2026.11 | 2026.12 | 2027.01 | 2027.02 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 1. 기반** | 공동 학습, Dynamixel 환경 세팅, 시스템 설계 | | | | | | | |
| **Phase 2. HW 설계 및 통합** | | 실기 연동, 1st 프린팅 | | | | | | |
| **Phase 3. HW 통합/조립** | | | | 조립·캘리브레이션, 그립 프리셋 | | | | |
| **Phase 4. 검증** | | | | | | 3종 파지, 24h 연속 구동 로깅/리포트 | | |
| **Phase 5. 고도화/버퍼** | | | | | | | PID 튜닝, IK, 조립가이드 | 지연 흡수 |
| *(병렬) 기구·프린팅* | ──────── | ──────── | ──────── | ──────── | ──────── | | | |

### 단계별 산출물 요약 (6-mo 검증 완료 기준선)

| 단계 | 기간 | 핵심 산출물 |
| :--- | :--- | :--- |
| **① 기반** | 2026.07 - 08 | Mock PortHandler, servo_config, Control Table 레지스터맵, DB ERD, CAD 검토 |
| **② 제어 코어** | 2026.08 - 09 | 실기 연동, GroupSyncWrite 50Hz 루프, FK, 1st 프린팅 |
| **③ HW 통합** | 2026.10 - 11 | 최종 조립·캘리브레이션, 그립 프리셋 UI 기본, 2nd/3rd 프린팅 |
| **④ 검증** | 2026.12 | 3종 파지 통계, 24h 연속 구동·로깅 리포트 |
| **⑤ 고도화/버퍼** | 2027.01 - 02 | PID 튜닝, IK (스트레치)·조립 가이드, 지연 흡수 버퍼 |