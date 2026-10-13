"""실물 손 간섭 점검 스크립트 (today_to_do.md 2-3 단계).

실행 중인 real/server.py에 HTTP로 명령해 그립 3종(상자, 물병, 휴지심 등)과
최대 파지(Q_CLOSE)를 차례로 적용하고, 관절별 목표 도달 여부 및 토크 한계 도달(막힘 의심)을 점검합니다.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


def req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=5) as f:
        return json.loads(f.read())


def main() -> int:
    # 1. 서버 연결 확인
    try:
        req("GET", "/state")
    except urllib.error.URLError as e:
        print(f"✗ 서버에 연결할 수 없습니다 ({BASE}): {e}")
        print("  먼저 다른 터미널에서 'python real/server.py'를 실행해 서버를 켜주세요.")
        return 1

    # 2. 토크가 꺼져 있으면 먼저 활성화
    print("[준비] 전 관절 토크 활성화...")
    req("POST", "/torque", {"enabled": True})
    time.sleep(1)

    # 3. 프리셋 및 파지 목록 준비
    presets = [n for n in req("GET", "/presets") if n != "default"]
    cases = [(n, "POST", f"/presets/{urllib.parse.quote(n, safe='')}/apply", None) for n in presets]
    cases.append(("grasp 1.0 (Q_CLOSE)", "POST", "/grasp", {"amount": 1.0}))

    print(f"[진행] 점검할 그립 {len(cases)}종: {[c[0] for c in cases]}")

    for name, method, path, body in cases:
        print(f"\n▶ [{name}] 적용 중 (5초 유지)...")
        req(method, path, body)
        time.sleep(5)

        st = req("GET", "/state")
        print(f"[{name}] 점검 결과:")
        for j in sorted(st["targets"]):
            err = st["joints"][j] - st["targets"][j]
            f = st["forces"][j]
            lim = st["gains"][j]["torque_limit"]
            flag = "  <-- ⚠ 막힘 의심" if abs(err) > 0.05 and abs(f) > 0.8 * lim else ""
            print(f"  {j:4s}: 목표 {st['targets'][j]:+6.3f}  실제 {st['joints'][j]:+6.3f}  "
                  f"오차 {err:+6.3f} rad  힘 {abs(f):4.2f}/{lim:4.2f} N·m{flag}")

        print("  → 손 펴기 (3초 대기)...")
        req("POST", "/grasp", {"amount": 0.0})
        time.sleep(3)

    print("\n✅ 점검 완료! 결과를 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
