"""지금 자세를 각 관절의 0 rad로 만듦: 모터의 Homing Offset(EEPROM)을 바꿔 현재 위치가 중앙(2048 tick)으로 읽히게 함.

위치 모드에서 Homing Offset은 ±1024 tick까지만 먹으므로(넘으면 값은 저장돼도 위치에 반영 안 됨),
남는 차이는 config.json의 zero로 보정함. 토크가 꺼진 상태에서만 쓸 수 있으므로
서버를 끄고(토크 꺼짐) 손을 원하는 자세로 맞춘 뒤 실행.

사용법
  python real/center.py                 # 바꿀 값만 보여 줌 (쓰지 않음)
  python real/center.py --apply         # Homing Offset 씀
  python real/center.py --apply A_j1 B_j2   # 지정한 관절만
  python real/center.py --reset --apply     # Homing Offset 0, zero 2048로 되돌림

종료 코드: 오류가 하나라도 있으면 1
"""
import argparse
import re
import sys
from pathlib import Path

import config as cfgmod
from dxl import TICKS_PER_REV, Bus, DxlError, pick_port


CENTER = TICKS_PER_REV // 2
OFFSET_LIMIT = 1024   # tick, 위치 모드에서 Homing Offset이 반영되는 범위


def plan(present: int, offset: int) -> tuple[int, int]:
    """현재 자세를 0 rad로 만드는 (Homing Offset, config zero). 한 바퀴 안의 실제 위치 기준이라 전원을 껐다 켜도 같음."""
    actual = (present - offset) % TICKS_PER_REV
    new = max(-OFFSET_LIMIT, min(OFFSET_LIMIT, CENTER - actual))
    return new, actual + new


def write_zeros(path: Path, zeros: dict[str, int]):
    """config.json의 zero 값만 바꿈. 한 줄에 관절 하나인 기존 형식을 유지."""
    text = path.read_text(encoding="utf-8")
    for n, z in zeros.items():
        text, count = re.subn(rf'("{n}":\s*{{[^}}]*"zero":\s*)-?\d+', rf"\g<1>{z}", text)
        if count != 1:
            raise ValueError(f"{path}에서 {n}의 zero를 찾지 못함")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("joints", nargs="*", help="바꿀 관절 (기본: 전부)")
    ap.add_argument("--config", type=Path, default=cfgmod.CONFIG_PATH)
    ap.add_argument("--port", help="기본: config의 port, 없으면 자동 탐색")
    ap.add_argument("--apply", action="store_true", help="실제로 EEPROM에 씀 (없으면 보여 주기만 함)")
    ap.add_argument("--reset", action="store_true", help="Homing Offset을 0으로 되돌림")
    args = ap.parse_args()

    try:
        cfg = cfgmod.load(args.config)
    except (OSError, ValueError, KeyError) as e:
        print(f"✗ 설정 파일 문제: {e}")
        return 1
    unknown = set(args.joints) - set(cfg.joints)
    if unknown:
        print(f"✗ 없는 관절: {sorted(unknown)} (가능: {list(cfg.joints)})")
        return 1
    names = args.joints or list(cfg.joints)

    ok, zeros = True, {}
    try:
        port = pick_port(args.port, cfg.port)
        print(f"포트 {port}, config {args.config}" + ("" if args.apply else "  (미리 보기: --apply로 씀)"))
        with Bus(port, cfg.baudrate) as bus:
            for n in names:
                j = cfg.joints[n]
                try:
                    if bus.read(j.id, "torque_enable"):
                        print(f"  {n:5s} ID {j.id:3d}  ✗ 토크가 켜져 있음: 서버를 끄고 다시 실행")
                        ok = False
                        continue
                    present, old = bus.read(j.id, "present_position"), bus.read(j.id, "homing_offset")
                    new, zero = (0, CENTER) if args.reset else plan(present, old)
                    line = f"  {n:5s} ID {j.id:3d}  tick {present:5d}  offset {old:+5d} → {new:+5d}  zero {j.zero} → {zero}"
                    if args.apply:
                        if new != old:   # EEPROM은 쓰기 횟수에 수명이 있어 다를 때만 씀
                            bus.write(j.id, "homing_offset", new)
                        after = bus.read(j.id, "present_position")
                        expected = CENTER if args.reset else zero
                        if abs(after - expected) > 5:   # 손으로 잡고 있어 조금 흔들리는 정도는 허용
                            line += f"  ✗ 쓴 뒤 tick {after} (예상 {expected})"
                            ok = False
                        else:
                            line += f"  → tick {after} ✓"
                            if zero != j.zero:
                                zeros[n] = zero
                    print(line)
                except DxlError as e:
                    print(f"  {n:5s} ID {j.id:3d}  ✗ {e}")
                    ok = False
    except DxlError as e:
        print(f"✗ {e}")
        return 1
    if zeros:
        write_zeros(args.config, zeros)
        print(f"config zero 수정: {zeros}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
