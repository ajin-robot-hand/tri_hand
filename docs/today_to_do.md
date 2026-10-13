# 오늘 할 일: 24시간 연속 구동 시험 (2026-10-13)

실물 손을 24시간 동안 쥐었다 폈다 반복시키며 온도·통신·복구 지표를 측정합니다.
처음 하는 사람도 따라 할 수 있게 단계마다 **왜 하는지 / 무엇을 입력하는지 / 무엇을 확인하는지**를 적었습니다.

| 단계 | 내용 | 예상 시간 |
| :--- | :--- | ---: |
| 0 | 시험 방식 이해 | 5분 |
| 1 | 준비 (컴퓨터 설정, 하드웨어 점검) | 15분 |
| 2 | 사전 점검: 손가락끼리 부딪히는가 (issue #7) | 20분 |
| 3 | 15분 리허설 | 20분 |
| 4 | 본 시험 시작 | 5분 |
| 5 | 시험 중 점검 | 수시 |
| 6 | 종료 후 판정·기록 | 30분 |

> 모든 명령은 리포지토리 루트(`~/assignment/tri-hand`, 로봇 PC 경로에 맞게 바꾸세요)에서 실행합니다.
> 파이썬은 반드시 `~/mujoco_env/bin/python`을 씁니다.

---

## 0. 시험 방식 이해

**러너가 하는 일** ([`real/endurance.py`](../real/endurance.py))
- 2분(120초)을 한 사이클로 **30초 쥐기 → 90초 펴기**를 반복합니다.
- 5분마다 다음 그립 프리셋(3종)으로 바꿉니다. 프리셋은 로봇 PC의 `real/presets.json`에 있습니다 (`.gitignore` 대상이라 리포에는 없음).
- 24시간이면 약 **720번** 쥡니다.

**자동 안전장치**
- 모터 온도가 **65 °C**를 넘으면 손을 펴고 토크를 끈 뒤 멈춥니다.
- 모터에 하드웨어 오류가 생기면 서버가 그 모터를 **자동 재부팅**해 복구합니다.
- 서버와의 통신이 잠깐 실패하면 경고만 찍고 재시도합니다. 실패가 **60초 넘게 이어질 때만** 손을 펴고 멈춥니다 (`--max-outage`로 조절).

**issue #7을 오늘 같이 확인합니다**
시뮬레이션에서는 꽉 쥐면 A 손가락 끝이 B·C 손가락 끝에 부딪혀, A_j1 모터가 최대 토크(1.4 N·m)로 계속 버팁니다.
실물에서도 그렇다면 30초 × 720번 동안 **A 모터만 유독 뜨거워집니다.**
그래서 2단계에서 미리 확인하고, 24시간 동안에도 A 모터 온도를 따로 지켜봅니다.

---

## 1. 준비 (15분)

### 1-1. 컴퓨터가 24시간 동안 꺼지지 않게 하기 (시험 실패 원인 1순위)
- Windows 설정 → 전원: **절전 모드 "안 함"** (화면 끄기는 괜찮음)
- Windows 업데이트: **"업데이트 일시 중지"** (자동 재시작 방지)
- 노트북이면 충전기 연결, 덮개를 닫아도 "아무 것도 안 함"으로 설정

### 1-2. 하드웨어 점검
- 모터 12 V 전원 어댑터와 U2D2 USB 케이블이 단단히 꽂혀 있는지 확인
- WSL2를 쓰면 U2D2를 WSL에 붙이기: Windows PowerShell(관리자)에서 `usbipd attach --wsl --busid <번호>`
- 손 주변에 걸릴 물건을 치우기
- 모터가 **식은 상태**에서 시작 (손으로 만져 미지근하지 않을 것)

### 1-3. 최신 코드 받기
```bash
git pull
```
러너의 통신 재시도 수정이 들어 있어야 합니다. 아래가 보이면 OK:
```bash
~/mujoco_env/bin/python real/endurance.py --help | grep max-outage
```

### 1-4. 모터 7개가 응답하는지 확인 (읽기만 해서 안전)
```bash
~/mujoco_env/bin/python real/check.py
```
✅ 오류 없이 끝나면 통과. 오류가 하나라도 있으면 **시험하지 말고** 케이블·전원부터 확인합니다.

---

## 2. 사전 점검: 실물에서 손가락끼리 부딪히는가 (20분)

### 2-1. 끊기지 않는 터미널 열기 (tmux)
창을 닫거나 SSH가 끊겨도 프로그램이 계속 돌게 해 줍니다.
```bash
tmux new -s hand
```

| 하고 싶은 것 | 누를 키 |
| :--- | :--- |
| tmux에서 빠져나오기 (프로그램은 계속 돎) | `Ctrl+b` 누른 뒤 `d` |
| 다시 들어가기 | `tmux attach -t hand` |
| 새 창 열기 | `Ctrl+b` 누른 뒤 `c` |
| 창 이동 | `Ctrl+b` 누른 뒤 `0` / `1` |

### 2-2. 서버 켜기 (0번 창)
```bash
~/mujoco_env/bin/python real/server.py
```
손이 천천히 펴진 자세(0 rad)로 갑니다. `모든 관절 0 rad 도착, 토크 켜짐`이 나오면 정상입니다.
브라우저에서 `http://127.0.0.1:8000`을 열면 대시보드도 볼 수 있습니다.

### 2-3. 점검 스크립트 실행 (`Ctrl+b c`로 1번 창을 열고)
그립 3종과 `/grasp` 최대(= `Q_CLOSE`)를 차례로 적용하고, 5초 뒤 관절마다
**목표에 도착했는지**와 **토크를 얼마나 쓰는지**를 출력합니다.

```bash
~/mujoco_env/bin/python - <<'EOF'
import json, time, urllib.request
BASE = "http://127.0.0.1:8000"
def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=5) as f:
        return json.loads(f.read())

cases = [(n, "POST", f"/presets/{n}/apply", None) for n in req("GET", "/presets")]
cases.append(("grasp 1.0 (Q_CLOSE)", "POST", "/grasp", {"amount": 1.0}))
for name, method, path, body in cases:
    req(method, path, body)
    time.sleep(5)
    st = req("GET", "/state")
    print(f"\n[{name}]")
    for j in sorted(st["targets"]):
        err = st["joints"][j] - st["targets"][j]
        f, lim = st["forces"][j], st["gains"][j]["torque_limit"]
        flag = "  <-- 막힘 의심" if abs(err) > 0.05 and abs(f) > 0.8 * lim else ""
        print(f"  {j}: 목표 {st['targets'][j]:+.3f}  실제 {st['joints'][j]:+.3f}  "
              f"오차 {err:+.3f} rad  힘 {abs(f):.2f}/{lim:.2f} N·m{flag}")
    req("POST", "/grasp", {"amount": 0.0})
    time.sleep(3)
EOF
```

### 2-4. 결과 읽는 법

| 보이는 것 | 뜻 | 할 일 |
| :--- | :--- | :--- |
| `막힘 의심`이 하나도 없음 | 실물에서는 부딪히지 않음 | 3단계로 |
| A_j1·A_j2에 `막힘 의심` | **issue #7이 실물에서도 재현됨.** 손가락이 막혀 모터가 한계 토크로 버팀 | 아래 "대처" 먼저 |
| 다른 관절에 `막힘 의심` | 다른 곳이 걸림 | 눈으로 어디가 닿는지 확인 |

**대처 (막힘 의심이 나왔을 때)**
1. 대시보드에서 그 프리셋의 A_j1·A_j2 `torque_limit`를 **0.6 N·m 정도로 낮춰 다시 저장**합니다.
2. 2-3을 다시 돌려 힘이 낮아졌는지, 물체는 여전히 잘 쥐는지 확인합니다.
3. 출력 화면과 사진을 남깁니다. **issue #7 "정할 것"에 대한 실물 근거**가 됩니다.

끝나면 0번 창에서 `Ctrl+C`로 서버를 끕니다 (꺼질 때 토크도 자동으로 꺼짐).

---

## 3. 15분 리허설 (20분)

24시간을 걸었다가 10분 만에 실수를 발견하는 일을 막기 위한 단계입니다.

**0번 창: 로그를 켜고 서버 시작**
```bash
~/mujoco_env/bin/python real/server.py --log logs
```
`CSV 로깅: logs/<날짜시각>`이 출력되는지 확인합니다.

**1번 창: 15분만 구동** (그립 3종이 모두 한 번씩 나옴)
```bash
~/mujoco_env/bin/python real/endurance.py --hours 0.25
```

✅ 확인할 것
- [ ] 시작 시 `그립 3종 순환: [...]`이 출력된다
  - `(프리셋 없음 → /grasp 사용)`이 나오면 프리셋 파일을 못 찾은 것 → `Q_CLOSE`로 꽉 쥐게 되므로 **멈추고 원인 확인**
- [ ] 손이 30초 쥐고 90초 펴기를 반복한다
- [ ] 끝나면 요약(구동 시간·통신 실패 횟수·최고 온도·패킷 에러율·지터·가용률)이 출력된다
- [ ] `logs/<날짜시각>/` 안에 `joint_sample.csv`, `error_event.csv`, `run.csv`가 생겼다

**(선택, 2분) 통신 재시도 동작 확인**
러너를 `--hours 0.05`로 다시 띄운 뒤 0번 창에서 서버를 `Ctrl+C`로 끕니다.
러너에 `⚠ 통신 실패 N회째`가 뜨다가 약 60초 뒤 `[통신 두절 중단]`으로 끝나면 정상입니다.

리허설이 끝나면 **서버를 껐다 다시 켭니다.** 통신 카운터가 0부터 시작해야 24시간 통계가 깨끗합니다.

---

## 4. 본 시험 시작 (5분)

**0번 창**
```bash
~/mujoco_env/bin/python real/server.py --log logs
```

**1번 창** (`tee`는 화면 출력을 파일에도 저장 → 마지막 요약이 남음)
```bash
~/mujoco_env/bin/python real/endurance.py --hours 24 2>&1 | tee logs/endurance_$(date +%Y%m%d_%H%M).txt
```

> 2단계에서 `막힘 의심`이 나왔다면 `--max-outage 20`을 붙이세요.
> 통신이 끊긴 동안 손은 쥔 채로 남기 때문에, 막힌 상태로 오래 버티지 않게 하기 위함입니다.

- [ ] **시작 시각 기록:** ____:____
- 이후 `Ctrl+b d`로 tmux에서 빠져나와도 됩니다.

---

## 5. 시험 중 점검 (처음 2시간은 30분마다, 이후 몇 시간마다)

### 5-1. 관절별 최고 온도 (가장 중요)
```bash
~/mujoco_env/bin/python - <<'EOF'
import csv, glob, collections
f = sorted(glob.glob("logs/*/joint_sample.csv"))[-1]
mx = collections.defaultdict(float)
for r in csv.DictReader(open(f)):
    if r["temperature_c"]:
        mx[r["joint"]] = max(mx[r["joint"]], float(r["temperature_c"]))
print(f)
for j in sorted(mx): print(f"  {j}: 최고 {mx[j]:.0f} °C")
EOF
```
- 모든 관절이 비슷하게 오르다 어느 온도에서 멈추면 정상입니다.
- **A_j1·A_j2만 확실히 더 높으면** issue #7(손가락 충돌로 버티는 중)의 증거입니다. 60 °C에 가까워지면 미리 멈추고 `torque_limit` 하향을 검토합니다.

### 5-2. 오류 이벤트
```bash
tail -n 20 logs/*/error_event.csv
```
- 머리글 한 줄만 있으면 오류 없음
- `reboot` → 자동 복구가 일어남 (시각을 메모)
- `recover_failed` → 복구 실패 (반드시 메모)

### 5-3. 러너가 살아 있는지
`tmux attach -t hand` → 1번 창 확인.
- `⚠ 통신 실패` 경고가 가끔 보이는 것은 괜찮습니다 (자동 재시도).
- 요약이 이미 출력돼 있으면 시험이 끝난 것입니다. 첫 줄 대괄호가 이유입니다 (`[완료]`, `[과열 중단: ...]`, `[통신 두절 중단: ...]`).

### 비상 정지 (위에서부터 차례로)
1. 1번 창(러너)에서 `Ctrl+C` → 손을 펴고 토크 off
2. 반응이 없으면 0번 창(서버)에서 `Ctrl+C` → 토크 off
3. 그래도 안 되면 **모터 12 V 전원을 뽑기**

---

## 6. 종료 후 판정·기록 (30분)

러너 요약과 `run.csv` 마지막 줄을 계획서 기준과 비교합니다.

| 항목 | 합격 기준 | 어디서 보나 | 결과 |
| :--- | :--- | :--- | :--- |
| 구동 시간 | 24.00 h, 첫 줄 `[완료]` | 요약 첫 줄 | |
| 최고 온도 | ≤ 65 °C | 요약 `최고 온도`, `joint_sample.csv` | |
| 패킷 에러율 | < 0.0005 (0.05%) | 요약 `패킷 에러율` | |
| 지터 | p95 < 2 ms | 요약 `지터 p95` | |
| 누락 프레임 | < 0.001 (0.1%) | 요약 `누락` | |
| 가용률 | ≥ 0.99 | 요약 `가용률` | |
| A 모터 과열 여부 (issue #7) | A_j1·A_j2가 B·C보다 눈에 띄게 높지 않음 | 5-1 스크립트 | |

**남길 것**
- [ ] `logs/<날짜시각>/` 폴더 통째
- [ ] `logs/endurance_*.txt` (러너 요약)
- [ ] 2단계 점검 출력과 사진
- [ ] 시작·종료 시각, 대략의 실내 온도, 중간에 있었던 일 메모

이 자료로 [`docs/evaluation.md`](evaluation.md)의 KPI 표와 issue #7 답변을 채웁니다.

---

## 7. (별도) 시연용 teleop.py 웹캠 점검 — Windows PC

시연은 Windows 컴퓨터에서 하는데, 지금까지는 WSL2 환경에서 [`src/teleop.py`](../src/teleop.py)를 돌리다가 `cap.read()`에서 멈춰 Ctrl+C로 끊어야 했던 적이 있습니다. 원인이 GUI(Qt) 쪽인지 웹캠 프레임 전달 자체가 막히는 것인지 아직 특정 못 했으므로, 실제 시연 PC에서 미리 확인이 필요합니다.

**증상 요약**
- TFLite/MediaPipe 경고(`feedback manager`, `NORM_RECT` 등)와 `QFontDatabase: Cannot find font directory ...cv2/qt/fonts` 경고는 무해한 로그 노이즈 → 무시 가능
- 몇 프레임 처리 후 `cap.read()`가 응답 없이 멈춤 → Ctrl+C로만 종료됨 (WSL2에서 웹캠을 usbipd로 패스스루할 때 자주 생기는 현상)

**확인할 것**
- [ ] 시연 PC(Windows)에서 WSL2 없이 **Windows 네이티브 파이썬**으로 `teleop.py`를 돌릴 수 있는지 먼저 검토 (웹캠 접근이 훨씬 안정적)
  - 이 경우 `--url`을 WSL2 쪽 서버 IP(`http://<WSL2 IP>:8000`)로 지정해야 함
- [ ] 굳이 WSL2에서 돌려야 한다면: `usbipd attach --wsl --busid <번호>`로 웹캠을 붙인 뒤 `/dev/video0` 등이 보이는지 확인
- [ ] `~/mujoco_env/bin/python src/teleop.py --no-preview`로 먼저 돌려서, GUI(`cv2.imshow`) 없이도 똑같이 멈추는지 확인 → 멈추면 웹캠/드라이버 쪽 문제, 안 멈추면 GUI 쪽 문제로 범위를 좁힘
- [ ] 몇 분 이상 끊김 없이 프레임을 받는지 (짧게 돌다 멈추는 패턴이 재현되는지)

**재현되면 그때 고칠 것**
- [ ] `run()`의 while 루프를 `try/finally`로 감싸서 Ctrl+C로 끊겨도 `cap.release()`가 항상 불리게 수정
- [ ] 필요하면 `cap.read()`에 타임아웃/워치독을 둬서 무한 대기 대신 에러 메시지를 내고 종료하게 수정
