"""tri_hand 실물 Dynamixel 모터 구동 (Protocol 2.0, 위치 제어 모드).

관절 이름 ↔ 모터 ID, 0 rad 위치, 회전 방향은 추측하지 않고 calibrate로 손으로 움직여서 기록함.
  raw(틱) = zero + sign × q(rad) × 4096/2π

사용법 (src/에서)
  python motors.py calibrate   # 토크 끈 채로 손으로 관절을 움직여 motors.json 작성
  python motors.py check       # 토크 끈 채로 현재 관절 각도(rad) 출력. 손으로 움직여 부호 확인

안전 장치
  - 목표는 각 관절의 [바깥쪽 run_sim.Q_OPEN, 오므림 run_sim.Q_CLOSE] 범위로 잘라서 보냄.
    A_j0(엄지 요)는 ±run_sim.YAW_LIMIT
  - 이동 속도는 모터의 Profile Velocity로 제한 (기본 max_speed=3.0 rad/s 이하)
  - 시작 시 목표 = 현재 위치로 맞춘 뒤 토크를 켬 (튀지 않게)
  - 위치 제어 모드가 아니거나 하드웨어 에러가 있으면 시작하지 않음 (EEPROM 설정은 바꾸지 않음)
  - 종료·예외 시 토크 끔
"""
import argparse
import json
import math
import sys
from pathlib import Path

from dynamixel_sdk import COMM_RX_TIMEOUT, COMM_SUCCESS, GroupSyncRead, GroupSyncWrite, PacketHandler, PortHandler
from serial import SerialException

from run_sim import CLOSE_SIGN, Q_CLOSE, Q_OPEN, YAW_LIMIT

CONFIG = Path(__file__).with_name("motors.json")
DEFAULT_PORT = "/dev/tty.usbserial-FTBIN9LO"
DEFAULT_BAUD = 1000000   # 실물 손 모터 7개(ID 1~7)의 설정값. 2026-10-09 ping으로 확인
BAUDRATES = [1000000, 57600, 115200, 2000000, 3000000, 4000000, 9600, 4500000]   # XL430/XM430 설정 가능 값
JOINT_NAMES = ["A_j0", "A_j1", "A_j2", "B_j1", "B_j2", "C_j1", "C_j2"]

# XL430/XM430 공통 Control Table (Protocol 2.0): (주소, 바이트 수)
OPERATING_MODE = (11, 1)
TORQUE_ENABLE = (64, 1)
HARDWARE_ERROR = (70, 1)
PROFILE_VELOCITY = (112, 4)
GOAL_POSITION = (116, 4)
PRESENT_POSITION = (132, 4)
POSITION_MODE = 3
MODELS = {1060: "XL430-W250", 1020: "XM430-W350", 1030: "XM430-W210"}

TICKS_PER_RAD = 4096 / (2 * math.pi)
RPM_PER_UNIT = 0.229          # Profile Velocity 단위
# 보정 없이 시험할 때의 가정: ID 1~7 = JOINT_NAMES 순서, 시작 자세 = 0 rad, 방향은 모름
TRY_MAX_ANGLE = 0.3           # rad (약 17°). 방향이 반대여도 크게 젖혀지지 않게
MIN_CALIBRATION_TICKS = 100   # 약 9°. 이보다 덜 움직이면 어느 모터인지 판단하지 않음


def safe_range(name: str) -> tuple[float, float]:
    """관절이 갈 수 있는 범위(rad): 바깥쪽 Q_OPEN ~ 오므림 Q_CLOSE. A_j0는 ±YAW_LIMIT

    곧게 편 자세(0)는 범위의 끝이 아니라 가운데다. 오므림 쪽 한계는 손가락 간 간섭이,
    바깥쪽 한계는 실물의 기구 정지점이 정한다 (run_sim.Q_OPEN 주석 참고).
    """
    finger, _, j = name.partition("_")
    if j not in Q_CLOSE:
        return -YAW_LIMIT, YAW_LIMIT
    return tuple(sorted((-CLOSE_SIGN[finger] * Q_OPEN[j],
                         CLOSE_SIGN[finger] * Q_CLOSE[j])))


def to_raw(cal: dict, q: float) -> int:
    return round(cal["zero"] + cal["sign"] * q * TICKS_PER_RAD)


def to_rad(cal: dict, raw: int) -> float:
    return (raw - cal["zero"]) * cal["sign"] / TICKS_PER_RAD


class Bus:
    """Dynamixel SDK 얇은 래퍼. 통신 실패는 예외로 올림"""

    def __init__(self, port: str, baud: int):
        self.port, self.packet = PortHandler(port), PacketHandler(2.0)
        try:
            opened = self.port.openPort()
        except SerialException:   # 장치 파일이 없으면 False 대신 예외
            opened = False
        if not opened:
            raise SystemExit(f"포트를 열 수 없음: {port} (U2D2 연결, 포트 이름 확인)")
        self.baud(baud)

    def baud(self, baud: int):
        if not self.port.setBaudRate(baud):
            self.port.closePort()
            raise SystemExit(f"통신 속도 설정 실패: {baud}")

    def _check(self, result, error, what: str):
        if result != COMM_SUCCESS:
            raise IOError(f"{what}: {self.packet.getTxRxResult(result)}")
        if error:
            raise IOError(f"{what}: {self.packet.getRxPacketError(error)}")

    def ping(self) -> dict[int, int]:
        """연결된 모터 {ID: 모델 번호}"""
        found, result = self.packet.broadcastPing(self.port)
        if result == COMM_RX_TIMEOUT:   # 아무 모터도 응답하지 않음
            return {}
        if result != COMM_SUCCESS:
            raise IOError(f"broadcast ping: {self.packet.getTxRxResult(result)}")
        return {i: info[0] for i, info in found.items()}

    def read(self, dxl_id: int, field: tuple[int, int]) -> int:
        addr, size = field
        fn = {1: self.packet.read1ByteTxRx, 2: self.packet.read2ByteTxRx, 4: self.packet.read4ByteTxRx}[size]
        value, result, error = fn(self.port, dxl_id, addr)
        self._check(result, error, f"ID {dxl_id} 읽기 {addr}")
        return value

    def write(self, dxl_id: int, field: tuple[int, int], value: int):
        addr, size = field
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}[size]
        result, error = fn(self.port, dxl_id, addr, value)
        self._check(result, error, f"ID {dxl_id} 쓰기 {addr}")

    def positions(self, ids: list[int]) -> dict[int, int]:
        group = GroupSyncRead(self.port, self.packet, *PRESENT_POSITION)
        for i in ids:
            group.addParam(i)
        result = group.txRxPacket()
        if result != COMM_SUCCESS:
            raise IOError(f"현재 위치 읽기: {self.packet.getTxRxResult(result)}")
        out = {}
        for i in ids:
            raw = group.getData(i, *PRESENT_POSITION)
            out[i] = raw - (1 << 32) if raw & (1 << 31) else raw   # 4바이트 부호 있는 정수
        return out

    def goals(self, raw: dict[int, int]):
        group = GroupSyncWrite(self.port, self.packet, *GOAL_POSITION)
        for i, v in raw.items():
            group.addParam(i, list((v & 0xFFFFFFFF).to_bytes(4, "little")))
        result = group.txPacket()
        if result != COMM_SUCCESS:
            raise IOError(f"목표 위치 쓰기: {self.packet.getTxRxResult(result)}")

    def close(self):
        self.port.closePort()


class HandMotors:
    """관절 이름 단위 목표(rad)를 실물 모터로. with 블록을 벗어나면 토크 끔"""

    def __init__(self, bus, joints: dict[str, dict], max_speed: float, max_angle: float = math.inf):
        self.bus, self.joints, self.max_angle = bus, joints, max_angle
        self.ids = [c["id"] for c in joints.values()]
        for name, c in joints.items():
            mode = bus.read(c["id"], OPERATING_MODE)
            if mode != POSITION_MODE:
                raise SystemExit(f"{name}(ID {c['id']}) 운영 모드 {mode}: 위치 제어(3)가 아님. "
                                 f"Dynamixel Wizard로 바꾼 뒤 다시 실행")
            err = bus.read(c["id"], HARDWARE_ERROR)
            if err:
                raise SystemExit(f"{name}(ID {c['id']}) 하드웨어 에러 {err:#04x}. 전원을 껐다 켜고 원인 확인")
        self.profile = max(1, int(max_speed * 60 / (2 * math.pi) / RPM_PER_UNIT))

    def __enter__(self):
        present = self.bus.positions(self.ids)
        for i in self.ids:
            self.bus.write(i, PROFILE_VELOCITY, self.profile)
            self.bus.write(i, GOAL_POSITION, present[i])   # 켜는 순간 현재 자세 유지
            self.bus.write(i, TORQUE_ENABLE, 1)
        return self

    def send(self, targets: dict[str, float]):
        """목표가 없는 관절은 보내지 않음 → 모터가 직전 목표 유지"""
        raw = {}
        for name, q in targets.items():
            c = self.joints.get(name)
            if c is None:   # 보정에서 건너뛴 관절
                continue
            lo, hi = safe_range(name)
            q = min(max(q, lo), hi)
            q = min(max(q, -self.max_angle), self.max_angle)
            raw[c["id"]] = to_raw(c, q)
        self.bus.goals(raw)

    def __exit__(self, *exc):
        for i in self.ids:
            try:
                self.bus.write(i, TORQUE_ENABLE, 0)
            except IOError as e:
                print(f"ID {i} 토크 끄기 실패: {e}", file=sys.stderr)
        self.bus.close()


def read_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{path} 없음. 먼저 python motors.py calibrate")


def load(path: Path, max_speed: float) -> HandMotors:
    """path가 "try"면 보정 없이 시험용 배정"""
    if str(path) == "try":
        return try_hand(Bus(DEFAULT_PORT, DEFAULT_BAUD), max_speed)
    cfg = read_config(path)
    return HandMotors(Bus(cfg["port"], cfg["baud"]), cfg["joints"], max_speed)


def try_hand(bus, max_speed: float) -> HandMotors:
    """ID 1~7을 JOINT_NAMES 순서로, 지금 자세를 0 rad로 보고, 각도를 ±TRY_MAX_ANGLE로 제한"""
    expected = list(range(1, len(JOINT_NAMES) + 1))
    found = sorted(bus.ping())
    if found != expected:
        bus.close()
        raise SystemExit(f"응답한 모터 ID {found}: 시험 모드는 ID {expected}가 필요. calibrate를 쓰세요")
    present = bus.positions(expected)
    joints = {n: {"id": i, "zero": present[i], "sign": 1} for n, i in zip(JOINT_NAMES, expected)}
    return HandMotors(bus, joints, max_speed, max_angle=TRY_MAX_ANGLE)


def detect(before: dict[int, int], after: dict[int, int], taken: set[int]) -> tuple[int, int] | None:
    """가장 많이 움직인 (아직 배정 안 된) 모터의 (ID, 이동 틱). 충분히 안 움직였으면 None"""
    moved = {i: after[i] - before[i] for i in after if i not in taken}
    if not moved:
        return None
    i = max(moved, key=lambda k: abs(moved[k]))
    return (i, moved[i]) if abs(moved[i]) >= MIN_CALIBRATION_TICKS else None


def motor_sign(name: str, close_delta: int) -> int:
    """오므림 방향으로 굽혔을 때의 틱 변화 → sign. 시뮬레이션의 오므림이 CLOSE_SIGN 방향이므로
    sign = 실제 이동 방향 × CLOSE_SIGN. A_j0는 오므림 방향이 없어 +1. 시뮬레이션과 반대로 돌면 motors.json에서 -1로"""
    finger, _, j = name.partition("_")
    if j not in Q_CLOSE:
        return 1
    return (1 if close_delta > 0 else -1) * int(CLOSE_SIGN[finger])


def calibrate(port: str, baud: int, path: Path):
    bus = Bus(port, baud)
    try:
        found = bus.ping()
        if not found:
            for other in BAUDRATES:
                if other == baud:
                    continue
                bus.baud(other)
                if bus.ping():
                    raise SystemExit(f"{baud}에서는 응답 없고 {other}에서 응답함. --baud {other} 로 다시 실행")
            raise SystemExit("모든 통신 속도에서 모터가 응답하지 않음. 모터 전원(U2D2는 신호만 전달, "
                             "Power Hub나 SMPS 필요)과 배선을 확인")
        for i, m in sorted(found.items()):
            print(f"ID {i}: {MODELS.get(m, f'모델 번호 {m}')}")
        ids = sorted(found)
        for i in ids:
            bus.write(i, TORQUE_ENABLE, 0)
        input("\n토크를 껐습니다. 모든 손가락을 곧게 펴고 엄지 요를 가운데로 (시뮬레이션 시작 자세) 둔 뒤 Enter")
        zero = bus.positions(ids)
        joints, taken = {}, set()
        for name in JOINT_NAMES:
            how = "엄지를 좌우 어느 쪽으로든 돌리고" if name == "A_j0" else "오므리는 방향으로 20° 이상 굽히고"
            while True:
                answer = input(f"\n[{name}] 곧게 편 상태에서 Enter, 건너뛰려면 s 입력 후 Enter: ")
                if answer.strip().lower() == "s":
                    break
                before = bus.positions(ids)
                input(f"[{name}] 그 관절만 손으로 {how} Enter")
                hit = detect(before, bus.positions(ids), taken)
                if hit is None:
                    print("충분히 움직인 모터가 없음. 다시")
                    continue
                i, delta = hit
                sign = motor_sign(name, delta)
                joints[name] = {"id": i, "zero": zero[i], "sign": sign}
                taken.add(i)
                print(f"[{name}] → ID {i} (이동 {delta:+d} 틱, sign {sign:+d})")
                break
        path.write_text(json.dumps({"port": port, "baud": baud, "joints": joints}, indent=2), encoding="utf-8")
        print(f"\n저장: {path}. 배정 안 된 모터: {sorted(set(ids) - taken)}")
    finally:
        bus.close()


def check(path: Path):
    """토크를 끈 채로 관절 각도를 계속 출력. Ctrl+C로 종료"""
    cfg = read_config(path)
    bus = Bus(cfg["port"], cfg["baud"])
    try:
        ids = [c["id"] for c in cfg["joints"].values()]
        for i in ids:
            bus.write(i, TORQUE_ENABLE, 0)
        while True:
            raw = bus.positions(ids)
            print("  ".join(f"{n} {to_rad(c, raw[c['id']]):+.2f}" for n, c in cfg["joints"].items()), end="\r")
    except KeyboardInterrupt:
        print()
    finally:
        bus.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["calibrate", "check"])
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--config", type=Path, default=CONFIG)
    args = ap.parse_args()
    if args.command == "calibrate":
        calibrate(args.port, args.baud, args.config)
    else:
        check(args.config)
