"""U2D2에 연결된 XL430들이 config.json과 맞는지 확인. 토크나 설정값은 바꾸지 않고 읽기만 함.

사용법
  python real/check.py            # 설정된 ID를 확인. 응답 없는 ID가 있으면 전 보레이트 스캔
  python real/check.py --scan     # 항상 전 보레이트 스캔 (ID/보레이트가 바뀐 모터 찾기)
  python real/check.py --watch    # 현재 각도를 계속 출력. 토크가 꺼진 손가락을 손으로 움직여
                                  # 어느 ID가 어느 관절인지, zero/sign이 맞는지 확인
  python real/check.py --port /dev/tty.usbserial-XXXX --config other.json

종료 코드: 오류가 하나라도 있으면 1
"""
import argparse
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import config as cfgmod
from dxl import (BAUDRATES, OPERATING_MODES, TICKS_PER_REV, VOLTAGE_RANGE, XL430_W250_MODEL, Bus, DxlError,
                 hw_errors, pick_port, rad_to_tick, tick_to_rad)

RANGE_MARGIN = 0.05   # rad, 현재 각도가 관절 범위를 이만큼 넘으면 경고 (손으로 밀린 정도는 허용)
TEMP_MARGIN = 5       # °C, 온도 제한까지 이만큼 남으면 경고


@dataclass
class MotorReport:
    joint: str
    id: int
    values: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def inspect_motor(joint: str, j: cfgmod.JointCfg, read: Callable[[str], int]) -> MotorReport:
    """모터 하나의 레지스터를 읽어 config와 비교. read(레지스터 이름) → 값."""
    r = MotorReport(joint, j.id)
    try:
        for name in ("model_number", "operating_mode", "drive_mode", "torque_enable", "hardware_error_status",
                     "min_position_limit", "max_position_limit", "present_position", "present_input_voltage",
                     "present_temperature", "temperature_limit"):
            r.values[name] = read(name)
    except DxlError as e:
        r.errors.append(str(e))
        return r
    v = r.values

    if v["model_number"] != XL430_W250_MODEL:
        r.errors.append(f"모델 번호 {v['model_number']} (XL430-W250은 {XL430_W250_MODEL})")
    if v["hardware_error_status"]:
        r.errors.append(f"하드웨어 오류: {', '.join(hw_errors(v['hardware_error_status']))}. 전원을 껐다 켜거나 재부팅 필요")
    if v["operating_mode"] != 3:
        mode = OPERATING_MODES.get(v["operating_mode"], v["operating_mode"])
        r.warnings.append(f"운영 모드가 {mode} (기본 위치 제어는 position=3)")
    if v["drive_mode"] & 1:
        r.warnings.append("Drive Mode 역방향 비트가 켜져 있음: 회전 방향이 뒤집히므로 sign과 함께 확인")

    lo_t, hi_t = sorted(rad_to_tick(q, j.zero, j.sign) for q in j.range)
    if lo_t < 0 or hi_t >= TICKS_PER_REV:
        r.errors.append(f"zero/range로 계산한 위치 [{lo_t}, {hi_t}] tick이 한 바퀴(0~{TICKS_PER_REV - 1})를 벗어남")
    elif lo_t < v["min_position_limit"] or hi_t > v["max_position_limit"]:
        r.warnings.append(f"모터 위치 제한 [{v['min_position_limit']}, {v['max_position_limit']}] tick이 "
                          f"관절 범위 [{lo_t}, {hi_t}] tick보다 좁아 목표가 잘림")

    q = tick_to_rad(v["present_position"], j.zero, j.sign)
    if not j.range[0] - RANGE_MARGIN <= q <= j.range[1] + RANGE_MARGIN:
        r.warnings.append(f"현재 각도 {q:+.2f} rad가 관절 범위 [{j.range[0]:+.2f}, {j.range[1]:+.2f}] 밖: "
                          "zero/sign 또는 ID 배정 확인")

    volt = v["present_input_voltage"] / 10
    if not VOLTAGE_RANGE[0] <= volt <= VOLTAGE_RANGE[1]:
        r.warnings.append(f"입력 전압 {volt:.1f} V가 동작 범위 {VOLTAGE_RANGE} V 밖")
    if v["present_temperature"] >= v["temperature_limit"] - TEMP_MARGIN:
        r.warnings.append(f"온도 {v['present_temperature']}°C, 제한 {v['temperature_limit']}°C에 가까움")
    return r


def scan(bus: Bus) -> dict[int, dict[int, int]]:
    """전 보레이트에서 broadcast ping. 보레이트 → {ID: 모델 번호}. 끝나면 원래 보레이트로 되돌림."""
    original, found = bus.baudrate, {}
    try:
        for baud in BAUDRATES.values():
            try:
                bus.set_baudrate(baud)
            except DxlError:
                print(f"  - {baud} bps: 이 OS/드라이버에서 설정할 수 없어 건너뜀")   # macOS FTDI는 4.5M 불가
                continue
            ids, corrupt = bus.broadcast_ping()
            if ids or corrupt:
                found[baud] = ids
                if corrupt:
                    print(f"  ⚠ {baud} bps: 응답이 겹쳐 깨짐. 같은 ID를 가진 모터가 여럿일 수 있음 (출고 기본값은 모두 ID 1)")
    finally:
        bus.set_baudrate(original)
    return found


def print_scan(found: dict[int, dict[int, int]], cfg: cfgmod.Config):
    by_id = {j.id: n for n, j in cfg.joints.items()}
    if not found:
        print("  어떤 보레이트에서도 응답한 모터가 없음: 전원(12V), 케이블, U2D2 TTL 포트 확인")
    for baud, ids in found.items():
        note = "" if baud == cfg.baudrate else f"  ← config의 {cfg.baudrate} bps와 다름"
        print(f"  {baud} bps{note}")
        for i, model in sorted(ids.items()):
            print(f"    ID {i:3d}  model {model}  config: {by_id.get(i, '(없음)')}")


def check(bus: Bus, cfg: cfgmod.Config, force_scan: bool) -> bool:
    """config의 각 관절을 확인하고 결과를 출력. 오류가 없으면 True."""
    ok = True
    print(f"\n[1] 설정된 ID 응답 ({bus.baudrate} bps)")
    missing = []
    for n, j in cfg.joints.items():
        model = bus.ping(j.id)
        print(f"  {n:5s} ID {j.id:3d}  " + ("응답 없음 ✗" if model is None else f"model {model}"))
        if model is None:
            missing.append(n)
            ok = False

    found, _ = bus.broadcast_ping()
    extra = sorted(set(found) - {j.id for j in cfg.joints.values()})
    if extra:
        print(f"  ⚠ config에 없는 ID가 응답함: {extra}")

    if missing or force_scan:
        print("\n[2] 전 보레이트 스캔 (ID나 보레이트가 바뀐 모터 찾기)")
        print_scan(scan(bus), cfg)
        if missing:
            print("  → 모터 쪽 값을 바꾸려면 Dynamixel Wizard, 배선이 바뀐 거라면 config.json의 id/baudrate를 수정")

    print("\n[3] 모터 상태와 config 비교")
    for n, j in cfg.joints.items():
        if n in missing:
            continue
        r = inspect_motor(n, j, lambda name, i=j.id: bus.read(i, name))
        v = r.values
        if "present_position" in v:
            q = tick_to_rad(v["present_position"], j.zero, j.sign)
            print(f"  {n:5s} ID {j.id:3d}  {q:+.3f} rad ({math.degrees(q):+6.1f}°)  tick {v['present_position']:5d}  "
                  f"{v['present_input_voltage'] / 10:4.1f} V  {v['present_temperature']:2d}°C  "
                  f"토크 {'켜짐' if v['torque_enable'] else '꺼짐'}")
        else:
            print(f"  {n:5s} ID {j.id:3d}")
        for e in r.errors:
            print(f"        ✗ {e}")
        for w in r.warnings:
            print(f"        ⚠ {w}")
        ok = ok and not r.errors
    return ok


def watch(bus: Bus, cfg: cfgmod.Config):
    names = list(cfg.joints)
    print("Ctrl+C로 종료. 손으로 관절을 움직이며 각도 변화를 확인 (tick은 config의 zero 값 후보)")
    print("  ".join(f"{n:>16s}" for n in names))
    try:
        while True:
            cells = []
            for n in names:
                j = cfg.joints[n]
                try:
                    t = bus.read(j.id, "present_position")
                    cells.append(f"{tick_to_rad(t, j.zero, j.sign):+6.2f}rad {t:5d}t")
                except DxlError:
                    cells.append(f"{'-':>16s}")
            print("\r" + "  ".join(cells), end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=cfgmod.CONFIG_PATH)
    ap.add_argument("--port", help="기본: config의 port, 없으면 자동 탐색")
    ap.add_argument("--scan", action="store_true", help="전 보레이트 스캔을 항상 수행")
    ap.add_argument("--watch", action="store_true", help="현재 각도를 계속 출력")
    args = ap.parse_args()

    try:
        cfg = cfgmod.load(args.config)
    except (OSError, ValueError, KeyError) as e:
        print(f"✗ 설정 파일 문제: {e}")
        return 1

    try:
        port = pick_port(args.port, cfg.port)
        print(f"포트 {port}, config {args.config}")
        with Bus(port, cfg.baudrate) as bus:
            if args.watch:
                watch(bus, cfg)
                return 0
            ok = check(bus, cfg, args.scan)
    except DxlError as e:
        print(f"✗ {e}")
        return 1
    print("\n✅ 모든 관절이 config와 일치" if ok else "\n✗ 오류가 있음: 위 내용을 확인")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
