"""Dynamixel XL430-W250-T (Protocol 2.0) 통신과 단위 변환. U2D2 + dynamixel-sdk.

레지스터 주소는 ROBOTIS e-Manual의 XL430-W250 Control Table 기준.
"""
import glob
import math
from typing import NamedTuple

XL430_W250_MODEL = 1060
TICKS_PER_REV = 4096
VEL_UNIT = 0.229 * 2 * math.pi / 60   # rad/s, Goal/Present Velocity 1 단위
VOLTAGE_RANGE = (6.5, 12.0)   # V, XL430 동작 전압 (권장 11.1V)


class Reg(NamedTuple):
    addr: int
    size: int
    signed: bool = False


REG = {
    "model_number": Reg(0, 2),
    "baud_rate": Reg(8, 1),
    "drive_mode": Reg(10, 1),             # bit0: 역방향
    "operating_mode": Reg(11, 1),
    "homing_offset": Reg(20, 4, True),    # Present Position = 실제 위치 + 이 값
    "temperature_limit": Reg(31, 1),      # °C
    "velocity_limit": Reg(44, 4),          # 0.229 rpm
    "max_position_limit": Reg(48, 4),
    "min_position_limit": Reg(52, 4),
    "torque_enable": Reg(64, 1),
    "hardware_error_status": Reg(70, 1),
    "position_d_gain": Reg(80, 2),
    "position_p_gain": Reg(84, 2),
    "goal_pwm": Reg(100, 2, True),         # 885 = 100%
    "goal_velocity": Reg(104, 4, True),    # 0.229 rpm
    "profile_velocity": Reg(112, 4),       # 0.229 rpm, 위치 모드 이동 속도 (0 = 제한 없음)
    "goal_position": Reg(116, 4, True),
    "present_load": Reg(126, 2, True),     # 0.1 %
    "present_velocity": Reg(128, 4, True),  # 0.229 rpm
    "present_position": Reg(132, 4, True),
    "present_input_voltage": Reg(144, 2),  # 0.1 V
    "present_temperature": Reg(146, 1),    # °C
}

BAUDRATES = {0: 9600, 1: 57600, 2: 115200, 3: 1_000_000, 4: 2_000_000, 5: 3_000_000, 6: 4_000_000,
             7: 4_500_000}
OPERATING_MODES = {1: "velocity", 3: "position", 4: "extended_position", 16: "pwm"}
HW_ERROR_BITS = {0: "입력 전압", 2: "과열", 3: "모터 엔코더", 4: "전기적 충격", 5: "과부하"}

# U2D2(FTDI)가 잡히는 장치 이름: macOS, Linux
PORT_PATTERNS = ["/dev/tty.usbserial-*", "/dev/ttyUSB*"]


def tick_to_rad(tick: int, zero: int, sign: int) -> float:
    """zero: 관절 0 rad일 때의 tick. sign: 모터 증가 방향이 관절 +방향이면 +1."""
    return sign * (tick - zero) * 2 * math.pi / TICKS_PER_REV


def rad_to_tick(rad: float, zero: int, sign: int) -> int:
    return round(zero + sign * rad * TICKS_PER_REV / (2 * math.pi))


def hw_errors(status: int) -> list[str]:
    return [label for bit, label in HW_ERROR_BITS.items() if status >> bit & 1]


def find_ports() -> list[str]:
    return sorted(p for pat in PORT_PATTERNS for p in glob.glob(pat))


def pick_port(*candidates: str | None) -> str:
    """처음으로 지정된 값(인자 → config 순), 없으면 자동 탐색한 첫 포트."""
    for c in candidates:
        if c:
            return c
    ports = find_ports()
    if not ports:
        raise DxlError("U2D2 포트를 찾지 못함: USB 연결 확인 (WSL2는 usbipd로 연결 필요)")
    if len(ports) > 1:
        print(f"  포트가 여럿 있어 첫 번째를 사용: {ports}  (--port로 지정 가능)")
    return ports[0]


def _signed(value: int, reg: Reg) -> int:
    if reg.signed and value >= 1 << (8 * reg.size - 1):
        value -= 1 << (8 * reg.size)
    return value


class DxlError(Exception):
    pass


class Bus:
    """U2D2 포트 하나. 읽기 실패는 DxlError로 올림."""

    def __init__(self, port: str, baudrate: int):
        import dynamixel_sdk as sdk   # 하드웨어 없이 단위 변환만 쓰는 곳(테스트)에서는 필요 없음
        self._sdk = sdk
        self.port = sdk.PortHandler(port)
        self.packet = sdk.PacketHandler(2.0)
        if not self.port.openPort():
            raise DxlError(f"포트를 열 수 없음: {port}")
        self.set_baudrate(baudrate)

    def set_baudrate(self, baudrate: int):
        if not self.port.setBaudRate(baudrate):
            raise DxlError(f"보레이트 설정 실패: {baudrate}")
        self.baudrate = baudrate

    def close(self):
        self.port.closePort()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def ping(self, dxl_id: int) -> int | None:
        """응답하면 모델 번호, 없으면 None."""
        model, result, _ = self.packet.ping(self.port, dxl_id)
        return model if result == self._sdk.COMM_SUCCESS else None

    def broadcast_ping(self) -> tuple[dict[int, int], bool]:
        """(ID → 모델 번호, 응답이 깨졌는지). 같은 ID가 여럿이면 응답이 겹쳐서 깨짐."""
        found, result = self.packet.broadcastPing(self.port)
        return {i: v[0] for i, v in found.items()}, result == self._sdk.COMM_RX_CORRUPT

    def read(self, dxl_id: int, name: str) -> int:
        reg = REG[name]
        fn = {1: self.packet.read1ByteTxRx, 2: self.packet.read2ByteTxRx, 4: self.packet.read4ByteTxRx}[reg.size]
        value, result, error = fn(self.port, dxl_id, reg.addr)
        if result != self._sdk.COMM_SUCCESS:
            raise DxlError(f"ID {dxl_id} {name} 읽기 실패: {self.packet.getTxRxResult(result)}")
        if error:
            raise DxlError(f"ID {dxl_id} {name} 오류 응답: {self.packet.getRxPacketError(error)}")
        return _signed(value, reg)

    def write(self, dxl_id: int, name: str, value: int):
        reg = REG[name]
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}[reg.size]
        result, error = fn(self.port, dxl_id, reg.addr, value & ((1 << 8 * reg.size) - 1))
        if result != self._sdk.COMM_SUCCESS:
            raise DxlError(f"ID {dxl_id} {name} 쓰기 실패: {self.packet.getTxRxResult(result)}")
        if error:
            raise DxlError(f"ID {dxl_id} {name} 오류 응답: {self.packet.getRxPacketError(error)}")

    def sync_read(self, ids: list[int], first: str, last: str) -> dict[int, dict[str, int]]:
        """first~last 주소 구간에 있는 레지스터를 여러 모터에서 한 번에 읽음. ID → {이름: 값}."""
        start, end = REG[first].addr, REG[last].addr + REG[last].size
        names = [n for n, r in REG.items() if start <= r.addr and r.addr + r.size <= end]
        group = self._sdk.GroupSyncRead(self.port, self.packet, start, end - start)
        for i in ids:
            group.addParam(i)
        result = group.txRxPacket()
        if result != self._sdk.COMM_SUCCESS:
            raise DxlError(f"일괄 읽기 실패 ({first}~{last}): {self.packet.getTxRxResult(result)}")
        out = {}
        for i in ids:
            if not group.isAvailable(i, start, end - start):
                raise DxlError(f"ID {i} 일괄 읽기 응답 없음 ({first}~{last})")
            out[i] = {n: _signed(group.getData(i, REG[n].addr, REG[n].size), REG[n]) for n in names}
        return out
