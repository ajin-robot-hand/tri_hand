"""어느 모터 ID가 어느 관절인지, 회전 방향(sign)은 어떤지 손으로 관절을 하나씩 움직여 찾음.

모든 모터의 토크를 끈 뒤 관절마다 "편 상태 → 그 관절만 굽힘"을 시켜, 가장 많이 움직인 모터를 그 관절로 정함.
config.json의 id와 sign만 정하고, zero(0점)는 center.py, range는 건드리지 않음.

사용법
  python real/calibrate.py            # 끝에 바뀔 값을 보여 주고, y를 입력하면 config.json에 씀
  python real/calibrate.py --port /dev/tty.usbserial-XXXX --config other.json

종료 코드: 오류가 하나라도 있으면 1
"""
import argparse
import dataclasses
import sys
from pathlib import Path

import config as cfgmod
from dxl import XL430_W250_MODEL, Bus, DxlError, pick_port

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from run_sim import CLOSE_SIGN, Q_CLOSE  # noqa: E402

MIN_TICKS = 100   # tick (약 9°), 이보다 적게 움직였으면 그 관절을 못 찾은 것으로 봄


def detect(before: dict[int, int], after: dict[int, int], taken: set[int]) -> tuple[int, int] | None:
    """가장 많이 움직인, 아직 배정 안 된 모터의 (ID, 이동 tick). 충분히 안 움직였으면 None."""
    moved = {i: after[i] - before[i] for i in after if i not in taken}
    if not moved:
        return None
    i = max(moved, key=lambda k: abs(moved[k]))
    return (i, moved[i]) if abs(moved[i]) >= MIN_TICKS else None


def joint_sign(name: str, delta: int, old_sign: int) -> int:
    """오므리는 방향으로 굽혔을 때의 tick 변화 → sign. 시뮬레이션에서 오므림은 CLOSE_SIGN 방향.
    A_j0(엄지 좌우)는 기준 방향이 없어 기존 sign을 유지."""
    finger, _, j = name.partition("_")
    if j not in Q_CLOSE:
        return old_sign
    return (1 if delta > 0 else -1) * int(CLOSE_SIGN[finger])


def ask_joints(bus: Bus, ids: list[int], cfg: cfgmod.Config) -> dict[str, cfgmod.JointCfg]:
    """관절마다 손으로 움직이게 해서 id/sign을 정함. 건너뛴 관절은 기존 값 그대로."""
    def positions() -> dict[int, int]:
        return {i: v["present_position"] for i, v in bus.sync_read(ids, "present_position", "present_position").items()}

    joints, taken = dict(cfg.joints), set()
    for n, j in cfg.joints.items():
        how = "좌우 어느 쪽으로든 돌리고" if n.partition("_")[2] not in Q_CLOSE else "오므리는 방향으로 20° 이상 굽히고"
        while True:
            if input(f"\n[{n}] 곧게 편 상태에서 Enter, 건너뛰려면 s: ").strip().lower() == "s":
                print(f"  {n} 건너뜀: ID {j.id}, sign {j.sign:+d} 유지")
                break
            before = positions()
            input(f"[{n}] 그 관절만 손으로 {how} Enter: ")
            hit = detect(before, positions(), taken)
            if hit is None:
                print(f"  ✗ {MIN_TICKS} tick 이상 움직인 모터가 없음. 다시")
                continue
            i, delta = hit
            sign = joint_sign(n, delta, j.sign)
            joints[n] = dataclasses.replace(j, id=i, sign=sign)
            taken.add(i)
            print(f"  ✓ {n} → ID {i} (이동 {delta:+d} tick, sign {sign:+d})")
            if n.partition("_")[2] not in Q_CLOSE:
                print(f"  {n}는 기준 방향이 없어 sign {sign:+d} 유지: python real/check.py --watch로 방향 확인")
            break
    unused = sorted(set(ids) - taken)
    if unused:
        print(f"\n배정 안 된 모터: {unused}")
    return joints


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=cfgmod.CONFIG_PATH)
    ap.add_argument("--port", help="기본: config의 port, 없으면 자동 탐색")
    args = ap.parse_args()

    try:
        cfg = cfgmod.load(args.config)
    except (OSError, ValueError, KeyError) as e:
        print(f"✗ 설정 파일 문제: {e}")
        return 1

    try:
        port = pick_port(args.port, cfg.port)
        print(f"포트 {port}, {cfg.baudrate} bps, config {args.config}")
        with Bus(port, cfg.baudrate) as bus:
            found, corrupt = bus.broadcast_ping()
            if corrupt:
                print("✗ 응답이 깨짐: 같은 ID의 모터가 여럿일 수 있음. python real/check.py --scan 으로 확인")
                return 1
            if not found:
                print(f"✗ {cfg.baudrate} bps에서 응답한 모터가 없음. python real/check.py --scan 으로 보레이트/ID 확인")
                return 1
            for i, m in sorted(found.items()):
                print(f"  ID {i:3d}  {'XL430-W250' if m == XL430_W250_MODEL else f'모델 번호 {m}'}")
            ids = sorted(found)
            for i in ids:
                bus.write(i, "torque_enable", 0)
            print("토크를 껐습니다: 손가락이 힘 없이 늘어집니다")
            joints = ask_joints(bus, ids, cfg)
    except DxlError as e:
        print(f"✗ {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n중단: config.json은 그대로")
        return 1

    print()
    for n, new in joints.items():
        old = cfg.joints[n]
        print(f"  {n:5s} ID {old.id:3d} → {new.id:3d}  sign {old.sign:+d} → {new.sign:+d}")
    errors = cfgmod.validate(dataclasses.replace(cfg, joints=joints))
    if errors:
        print("✗ 쓰지 않음:\n  " + "\n  ".join(errors))
        return 1
    try:
        answer = input(f"{args.config}에 쓸까요? [y/N]: ")
    except (KeyboardInterrupt, EOFError):
        answer = ""
    if answer.strip().lower() != "y":
        print("쓰지 않음: config.json은 그대로")
        return 0
    cfgmod.update(args.config, {n: {"id": j.id, "sign": j.sign} for n, j in joints.items()})
    print(f"✓ {args.config}에 씀. 다음 단계:")
    print("  python real/center.py --apply   # 0점 맞추기")
    print("  python real/check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
