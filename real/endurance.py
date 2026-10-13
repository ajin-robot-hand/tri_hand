"""24h 연속 구동 러너 (T-14). 실행 중인 real/server.py에 HTTP로 명령해 그립을 순환시킨다.

계획서 [Page 5] 듀티: 정적 파지 30 s + 오픈 90 s. 5분마다 사용 가능한 프리셋(3종 그립)을 순환.
Present Temperature가 상한(기본 65 °C)을 넘으면 즉시 오픈·토크 off 후 중단한다.
서버와의 통신이 일시적으로 실패하면 경고만 찍고 다음 주기에 재시도하며, 실패가
--max-outage초(기본 60 s) 넘게 이어질 때만 중단한다.

측정 산출물(지터·패킷 에러율·가용률·1 Hz 샘플)은 서버가 --log로 CSV에 남기므로, 서버를
``python real/server.py --log logs`` 로 띄운 뒤 이 러너를 붙이면 된다.

사용법
  python real/server.py --log logs &
  python real/endurance.py --hours 24
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

STATIC = 30.0    # s, 정적 파지 유지
OPEN = 90.0      # s, 오픈 유지
ROTATE = 300.0   # s, 그립을 바꾸는 주기(5분)
MAX_TEMP = 65.0  # °C, 계획서 상한
MAX_OUTAGE = 60.0  # s, 통신 실패가 이만큼 연속되면 중단
COMM_ERRORS = (OSError, ValueError)   # URLError·타임아웃·연결 끊김(OSError 계열), 깨진 JSON 응답


def phase_at(elapsed: float, n_grips: int, static=STATIC, open_s=OPEN, rotate=ROTATE):
    """경과 시간 → ("grasp"|"open", grip_index). 듀티 사이클 안에서 정적/오픈을 반복하고,
    rotate초마다 다음 그립으로 넘어간다. n_grips==0이면 grip_index는 None."""
    duty = static + open_s
    mode = "grasp" if elapsed % duty < static else "open"
    grip = int(elapsed // rotate) % n_grips if n_grips else None
    return mode, grip


def over_temp(state: dict, limit: float) -> dict:
    """상한을 넘은 관절 → 온도."""
    return {n: t for n, t in state.get("temperatures", {}).items() if t > limit}


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _req(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def state(self):
        return self._req("GET", "/state")

    def presets(self):
        return self._req("GET", "/presets")

    def set_torque(self, enabled: bool):
        return self._req("POST", "/torque", {"enabled": enabled})

    def apply_preset(self, name: str):
        return self._req("POST", f"/presets/{name}/apply")

    def grasp(self, amount: float):
        return self._req("POST", "/grasp", {"amount": amount})


def run(c: Client, hours: float, poll: float, max_temp: float,
        static=STATIC, open_s=OPEN, rotate=ROTATE, max_outage=MAX_OUTAGE) -> str:
    grips = list(c.presets())
    print(f"그립 {len(grips)}종 순환: {grips or '(프리셋 없음 → /grasp 사용)'}")
    c.set_torque(True)
    deadline = time.monotonic() + hours * 3600
    start = time.monotonic()
    last = None
    max_seen = 0.0
    reason = "완료"
    comm_failures = 0
    fail_since = None   # 연속 통신 실패가 시작된 시각, 성공하면 None
    try:
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - start
            mode, grip = phase_at(elapsed, len(grips), static, open_s, rotate)
            key = (mode, grip)
            try:
                if key != last:   # 상태가 바뀔 때만 명령 (전환 시점). 실패하면 last가 그대로라 다음 주기에 재전송
                    if mode == "grasp":
                        c.apply_preset(grips[grip]) if grips else c.grasp(1.0)
                    else:
                        c.grasp(0.0)
                    last = key
                st = c.state()
            except COMM_ERRORS as e:
                now = time.monotonic()
                comm_failures += 1
                fail_since = now if fail_since is None else fail_since
                print(f"⚠ 통신 실패 {comm_failures}회째 ({now - fail_since:.0f}s 연속): {e}", flush=True)
                if now - fail_since > max_outage:
                    reason = f"통신 두절 중단: {now - fail_since:.0f}s 연속 실패"
                    break
                time.sleep(poll)
                continue
            fail_since = None
            max_seen = max([max_seen, *st.get("temperatures", {}).values()])
            hot = over_temp(st, max_temp)
            if hot:
                reason = f"과열 중단: {hot}"
                break
            time.sleep(poll)
    except KeyboardInterrupt:
        reason = "사용자 중단"
    finally:
        try:
            c.grasp(0.0)
            c.set_torque(False)
        except COMM_ERRORS:
            pass
    hours_run = (time.monotonic() - start) / 3600
    try:
        st = c.state()
    except COMM_ERRORS as e:
        return (f"[{reason}] 구동 {hours_run:.2f} h, 통신 실패 {comm_failures}회\n"
                f"  최고 온도   : {max_seen:.0f} °C (상한 {max_temp:.0f})\n"
                f"  서버 응답 없음({e}): 나머지 지표는 서버 --log의 run.csv를 보세요")
    av = st.get("availability"), st.get("downtime_s"), st.get("reboots")
    loop = st.get("loop", {})
    pk = st.get("packets", {})
    rate = pk.get("rx_errors", 0) / pk["tx"] if pk.get("tx") else 0.0
    return (f"[{reason}] 구동 {hours_run:.2f} h, 통신 실패 {comm_failures}회\n"
            f"  최고 온도   : {max_seen:.0f} °C (상한 {max_temp:.0f})\n"
            f"  패킷 에러율 : {rate:.6f} (tx={pk.get('tx')}, rx_err={pk.get('rx_errors')})\n"
            f"  지터 p95    : {loop.get('jitter_ms_p95', 0):.3f} ms, 누락 {loop.get('dropped_frac', 0):.6f}\n"
            f"  가용률      : {av[0]} (downtime {av[1]} s, reboots {av[2]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--http-port", type=int, default=8000)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--poll", type=float, default=2.0, help="상태 확인 주기(s)")
    ap.add_argument("--max-temp", type=float, default=MAX_TEMP)
    ap.add_argument("--max-outage", type=float, default=MAX_OUTAGE, help="통신 실패가 이 시간(s) 넘게 이어지면 중단")
    args = ap.parse_args()
    c = Client(f"http://{args.host}:{args.http_port}")
    try:
        c.state()
    except urllib.error.URLError as e:
        sys.exit(f"서버에 연결할 수 없음 ({c.base}): {e}. 먼저 real/server.py를 실행하세요")
    print(run(c, args.hours, args.poll, args.max_temp, max_outage=args.max_outage))


if __name__ == "__main__":
    main()
