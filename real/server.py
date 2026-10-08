"""tri_hand 실물 HTTP 제어 서버: src/server.py와 같은 API로 U2D2에 연결된 XL430을 제어.

대시보드(src/dashboard.html)를 그대로 씀.

사용법
  python real/server.py                     # http://127.0.0.1:8000
  python real/server.py --port /dev/tty.usbserial-XXXX --host 0.0.0.0

시뮬레이션 서버와 다른 점
  - 시작하면 전 관절 토크를 끄고 위치 모드로 둠. 서버를 끌 때도 토크를 끔
  - 시작할 때 모터의 Min/Max Position Limit를 config의 관절 범위로 맞춤 (다를 때만 EEPROM에 씀)
  - kp, kv는 XL430 Position P/D Gain 레지스터 값 그대로 (0~16383, 출고값 640/0).
    시뮬레이션의 N·m/rad 단위와 다르므로 프리셋 파일도 따로 씀 (real/presets.json)
  - torque_limit(N·m)은 Goal PWM으로 근사: 1.4 N·m(12V 정지 토크) = PWM 885
  - forces는 Present Load(정격 대비 %)를 1.4 N·m에 곱한 근사값
  - contacts는 센서가 없어 null. /reset 없음
  - state에 hw_errors(관절별 하드웨어 오류)와 comm_error(마지막 통신 오류, 없으면 null)가 추가됨
  - 현재 각도가 관절 범위 밖이면 토크를 켤 수 없음 (409). POST /torque는 그 관절만 건너뛰고
    나머지를 켠 뒤 skipped(관절 → 현재 각도)로 알려 줌
"""
import argparse
import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator

import config as cfgmod
from dxl import VEL_UNIT, Bus, DxlError, hw_errors, pick_port, rad_to_tick, tick_to_rad

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from run_sim import CLOSE_SIGN, Q_CLOSE  # noqa: E402

DASHBOARD = SRC / "dashboard.html"
PRESETS_PATH = Path(__file__).with_name("presets.json")   # --presets 로 변경 가능

STALL_TORQUE = 1.4   # N·m, XL430-W250 12V 정지 토크 (hand.xml forcerange와 같음)
PWM_MAX = 885        # Goal PWM 100%
GAIN_MAX = 16383     # Position P/D Gain 레지스터 범위
MODE_CODE = {"position": 3, "velocity": 1}   # Operating Mode 레지스터 값
POLL_PERIOD = 0.02   # s, 상태 읽기 주기

ModeName = Literal["position", "velocity"]


class Conflict(Exception):
    """요청이 현재 서보 상태와 맞지 않음 (HTTP 409)."""


@dataclass
class Servo:
    kp: int                 # Position P Gain
    kv: int                 # Position D Gain
    torque_limit: float     # N·m, Goal PWM으로 적용
    vel_limit: float        # rad/s, 모터의 Velocity Limit
    mode: ModeName = "position"
    torque: bool = False
    target: float = 0.0     # 마지막 목표 (모드 단위: rad 또는 rad/s)


def pwm_from_torque(tl: float) -> int:
    return round(tl / STALL_TORQUE * PWM_MAX)


class Hand:
    """모터 7개의 상태와 제어. bus는 dxl.Bus 또는 같은 메서드를 가진 테스트용 가짜."""

    def __init__(self, bus, cfg: cfgmod.Config):
        self.bus, self.cfg = bus, cfg
        self.lock = threading.RLock()   # 폴링 스레드와 HTTP 요청이 버스를 함께 씀
        self.t0 = time.monotonic()
        self.ids = [j.id for j in cfg.joints.values()]
        self.servos: dict[str, Servo] = {}
        self.reading = {n: {"q": 0.0, "qd": 0.0, "f": 0.0} for n in cfg.joints}
        self.errors: dict[str, list[str]] = {n: [] for n in cfg.joints}
        self.comm_error: str | None = None
        with self.lock:
            for n, j in cfg.joints.items():
                self._setup(n, j)
        self.poll()

    def _setup(self, n: str, j: cfgmod.JointCfg):
        b = self.bus
        b.write(j.id, "torque_enable", 0)   # 운영 모드와 위치 제한(EEPROM)은 토크가 꺼져 있어야 바뀜
        if b.read(j.id, "operating_mode") != MODE_CODE["position"]:
            b.write(j.id, "operating_mode", MODE_CODE["position"])
        lo, hi = sorted(rad_to_tick(q, j.zero, j.sign) for q in j.range)
        for name, v in (("min_position_limit", lo), ("max_position_limit", hi)):
            if b.read(j.id, name) != v:   # EEPROM은 쓰기 횟수에 수명이 있어 다를 때만 씀
                b.write(j.id, name, v)
        self.servos[n] = Servo(
            kp=b.read(j.id, "position_p_gain"), kv=b.read(j.id, "position_d_gain"),
            torque_limit=min(STALL_TORQUE, b.read(j.id, "goal_pwm") / PWM_MAX * STALL_TORQUE),
            vel_limit=b.read(j.id, "velocity_limit") * VEL_UNIT,
            target=tick_to_rad(b.read(j.id, "present_position"), j.zero, j.sign))

    def range(self, n: str, mode: ModeName) -> tuple[float, float]:
        if mode == "position":
            return self.cfg.joints[n].range
        v = self.servos[n].vel_limit
        return (-v, v)

    def poll(self):
        """현재 각도/속도/부하와 하드웨어 오류를 읽어 둠. 실패하면 이전 값을 유지하고 comm_error에 남김."""
        with self.lock:
            try:
                # 한 번에 읽음: macOS FTDI 드라이버는 읽기마다 약 16 ms 지연이 있음
                regs = self.bus.sync_read(self.ids, "hardware_error_status", "present_position")
            except DxlError as e:
                self.comm_error = str(e)
                return
            self.comm_error = None
            for n, j in self.cfg.joints.items():
                m = regs[j.id]
                self.reading[n] = {"q": tick_to_rad(m["present_position"], j.zero, j.sign),
                                   "qd": j.sign * m["present_velocity"] * VEL_UNIT,
                                   "f": j.sign * m["present_load"] / 1000 * STALL_TORQUE}
                self.errors[n] = hw_errors(m["hardware_error_status"])

    def state(self) -> dict:
        with self.lock:
            return {
                "time": time.monotonic() - self.t0,
                "joints": {n: r["q"] for n, r in self.reading.items()},
                "targets": {n: s.target for n, s in self.servos.items()},
                "velocities": {n: r["qd"] for n, r in self.reading.items()},
                "forces": {n: r["f"] for n, r in self.reading.items()},
                "gains": {n: {"kp": s.kp, "kv": s.kv, "torque_limit": s.torque_limit} for n, s in self.servos.items()},
                "modes": {n: s.mode for n, s in self.servos.items()},
                "torque": {n: s.torque for n, s in self.servos.items()},
                "contacts": None,
                "hw_errors": dict(self.errors),
                "comm_error": self.comm_error,
            }

    def _require(self, names, mode: ModeName):
        bad = sorted(n for n in names if not (self.servos[n].torque and self.servos[n].mode == mode))
        if bad:
            label = {"position": "위치", "velocity": "속도"}[mode]
            raise Conflict(f"{label} 모드이면서 토크가 켜진 관절만 목표를 받음: {bad}")

    def _send_goal(self, n: str, value: float):
        j, s = self.cfg.joints[n], self.servos[n]
        if s.mode == "position":
            self.bus.write(j.id, "goal_position", rad_to_tick(value, j.zero, j.sign))
        else:
            self.bus.write(j.id, "goal_velocity", round(j.sign * value / VEL_UNIT))
        s.target = value

    def _hold(self, n: str):
        """지금 상태를 유지하는 목표를 보냄: 위치 모드는 현재 각도, 속도 모드는 0."""
        j = self.cfg.joints[n]
        if self.servos[n].mode == "position":
            self._send_goal(n, tick_to_rad(self.bus.read(j.id, "present_position"), j.zero, j.sign))
        else:
            self._send_goal(n, 0.0)

    def set_targets(self, targets: dict[str, float], mode: ModeName) -> dict:
        applied, clipped = {}, []
        with self.lock:
            self._require(targets, mode)
            for n, v in targets.items():
                lo, hi = self.range(n, mode)
                c = min(max(v, lo), hi)
                if c != v:
                    clipped.append(n)
                self._send_goal(n, c)
                applied[n] = c
        return {"applied": applied, "clipped": clipped}

    def outside_range(self, names) -> dict[str, float]:
        """토크를 켜면 모터가 목표를 거부할 관절 → 현재 각도. 위치 모드이면서 꺼져 있고 위치 제한 밖인 관절."""
        out = {}
        for n in names:
            j, s = self.cfg.joints[n], self.servos[n]
            if s.mode == "position" and not s.torque:
                q = tick_to_rad(self.bus.read(j.id, "present_position"), j.zero, j.sign)
                if not j.range[0] <= q <= j.range[1]:
                    out[n] = q
        return out

    def set_torque(self, names, enabled: bool, skip_outside: bool = False) -> dict[str, float]:
        """범위 밖 관절이 있으면 409. skip_outside면 그 관절만 건너뛰고 나머지를 켬. 건너뛴 관절 → 현재 각도."""
        with self.lock:
            outside = self.outside_range(names) if enabled else {}
            if outside and not skip_outside:
                raise Conflict(f"현재 각도가 관절 범위 밖이라 토크를 켤 수 없음: "
                               f"{[f'{n} {q:+.2f} rad' for n, q in outside.items()]}. "
                               "손으로 범위 안쪽으로 옮기거나 config의 zero/sign 확인")
            for n in names:
                if n in outside:
                    continue
                s = self.servos[n]
                if enabled and not s.torque:
                    self._hold(n)   # 켜는 순간 관절이 튀지 않게
                self.bus.write(self.cfg.joints[n].id, "torque_enable", int(enabled))
                s.torque = enabled
            return outside

    def set_mode(self, n: str, mode: ModeName):
        with self.lock:
            s = self.servos[n]
            if s.torque:
                raise Conflict(f"{n}: 토크가 켜져 있어 모드를 바꿀 수 없음. 먼저 토크를 끄세요")
            self.bus.write(self.cfg.joints[n].id, "operating_mode", MODE_CODE[mode])
            s.mode = mode
            self._hold(n)   # 이전 모드 단위의 목표가 남지 않게

    def set_gains(self, n: str, kp: int, kv: int, torque_limit: float):
        with self.lock:
            i, s = self.cfg.joints[n].id, self.servos[n]
            self.bus.write(i, "position_p_gain", kp)
            self.bus.write(i, "position_d_gain", kv)
            self.bus.write(i, "goal_pwm", pwm_from_torque(torque_limit))
            s.kp, s.kv, s.torque_limit = kp, kv, torque_limit

    def shutdown(self):
        with self.lock:
            for n, j in self.cfg.joints.items():
                try:
                    self.bus.write(j.id, "torque_enable", 0)
                    self.servos[n].torque = False
                except DxlError as e:
                    print(f"✗ {n} 토크 끄기 실패: {e}")


class Motor(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    target: float                                             # rad, 관절별 범위는 Preset에서 검사
    kp: int = Field(gt=0, le=GAIN_MAX)                        # Position P Gain
    kv: int = Field(ge=0, le=GAIN_MAX)                        # Position D Gain
    torque_limit: float = Field(gt=0, le=STALL_TORQUE)        # N·m


def create_app(hand: Hand, presets_path: Path = PRESETS_PATH) -> FastAPI:
    joints = hand.cfg.joints
    presets_lock = threading.Lock()
    app = FastAPI(title="tri_hand real control")

    @app.exception_handler(RequestValidationError)
    def _validation_error(request, exc):
        # 기본 응답은 입력값을 되돌려 주는데, NaN이 들어오면 JSON 직렬화가 실패해 500이 됨
        return JSONResponse(status_code=422, content={"detail": [
            {k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]})

    @app.exception_handler(Conflict)
    def _conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(DxlError)
    def _dxl_error(request, exc):
        return JSONResponse(status_code=502, content={"detail": f"모터 명령 실패: {exc}"})

    def check_targets(targets: dict[str, float]):
        unknown = set(targets) - set(joints)
        if unknown:
            raise HTTPException(400, f"알 수 없는 관절: {sorted(unknown)}. 사용 가능: {list(joints)}")
        non_finite = sorted(n for n, q in targets.items() if not math.isfinite(q))
        if non_finite:
            raise HTTPException(400, f"유한하지 않은 값: {non_finite}")

    def joint(name: str) -> str:
        if name not in joints:
            raise HTTPException(404, f"알 수 없는 관절: {name}. 사용 가능: {list(joints)}")
        return name

    def close_sign(n: str) -> float | None:
        finger, _, suffix = n.partition("_")
        return CLOSE_SIGN[finger] if suffix in Q_CLOSE else None

    @app.get("/")
    def dashboard():
        return FileResponse(DASHBOARD)

    @app.get("/state")
    def get_state():
        return hand.state()

    @app.get("/joints")
    def list_joints():
        return {n: {"ctrlrange": list(hand.range(n, "position")), "velocity_range": list(hand.range(n, "velocity")),
                    "forcerange": [-STALL_TORQUE, STALL_TORQUE], "close_sign": close_sign(n), "id": j.id}
                for n, j in joints.items()}

    @app.get("/limits")
    def limits():
        return {"kp": [0, GAIN_MAX], "kv": [0, GAIN_MAX], "torque_limit": [0.0, STALL_TORQUE],
                "exclusive_min": ["kp", "torque_limit"]}

    @app.post("/joints")
    def set_joints(targets: dict[str, float]):
        check_targets(targets)
        return hand.set_targets(targets, "position")

    @app.post("/velocities")
    def set_velocities(targets: dict[str, float]):
        check_targets(targets)
        return hand.set_targets(targets, "velocity")

    class GraspRequest(BaseModel):
        amount: float = Field(ge=0, le=1)

    @app.post("/grasp")
    def grasp(req: GraspRequest):
        targets = {n: close_sign(n) * Q_CLOSE[n.rpartition("_")[2]] * req.amount
                   for n in joints if close_sign(n) is not None}
        return hand.set_targets(targets, "position")

    class TorqueRequest(BaseModel):
        enabled: bool

    @app.post("/joints/{name}/torque")
    def set_torque(req: TorqueRequest, name: str):
        hand.set_torque([joint(name)], req.enabled)
        return hand.state()

    @app.post("/torque")
    def set_all_torque(req: TorqueRequest):
        """범위 밖 관절 하나 때문에 전부 막히지 않게, 그 관절만 건너뛰고 skipped로 알려 줌."""
        skipped = hand.set_torque(list(joints), req.enabled, skip_outside=True)
        return {**hand.state(), "skipped": skipped}

    class ModeRequest(BaseModel):
        mode: ModeName

    @app.post("/joints/{name}/mode")
    def set_mode(req: ModeRequest, name: str):
        hand.set_mode(joint(name), req.mode)
        return hand.state()

    class Preset(RootModel[dict[str, Motor]]):
        """7개 관절 전체 값. 일부만 있으면 적용 후 상태가 이전 값에 따라 달라지므로 거부."""

        @model_validator(mode="after")
        def _check(self):
            names = set(self.root)
            if names != set(joints):
                raise ValueError(f"관절 7개가 모두 필요: 누락 {sorted(set(joints) - names)}, "
                                 f"알 수 없음 {sorted(names - set(joints))}")
            for n, m in self.root.items():
                lo, hi = joints[n].range
                if not lo <= m.target <= hi:
                    raise ValueError(f"{n} target {m.target}가 범위 [{lo}, {hi}] 밖")
            return self

    preset_name = PathParam(min_length=1, max_length=40, pattern=r"^[\w-]+(?: [\w-]+)*$")

    def load_presets() -> dict[str, Preset]:
        try:
            raw = json.loads(presets_path.read_text(encoding="utf-8"))
            return {name: Preset.model_validate(p) for name, p in raw.items()}
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValidationError) as e:
            raise HTTPException(500, f"프리셋 파일 {presets_path.name}을 읽을 수 없음 ({type(e).__name__}). "
                                     f"파일을 고치거나 지운 뒤 다시 시도하세요")

    @app.get("/presets")
    def list_presets():
        with presets_lock:
            return {n: p.model_dump() for n, p in load_presets().items()}

    @app.put("/presets/{name}")
    def save_preset(preset: Preset, name: str = preset_name):
        with presets_lock:
            presets = load_presets()
            created = name not in presets
            presets[name] = preset
            tmp = presets_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({n: p.model_dump() for n, p in presets.items()}, ensure_ascii=False,
                                      indent=2), encoding="utf-8")
            os.replace(tmp, presets_path)
        return {"name": name, "created": created}

    @app.post("/presets/{name}/apply")
    def apply_preset(name: str = preset_name):
        with presets_lock:
            preset = load_presets().get(name)
        if preset is None:
            raise HTTPException(404, f"프리셋 없음: {name}")
        with hand.lock:
            hand._require(preset.root, "position")
            for n, m in preset.root.items():
                hand.set_gains(n, m.kp, m.kv, m.torque_limit)
            hand.set_targets({n: m.target for n, m in preset.root.items()}, "position")
        return hand.state()

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=cfgmod.CONFIG_PATH)
    ap.add_argument("--port", help="기본: config의 port, 없으면 자동 탐색")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--http-port", type=int, default=8000)
    ap.add_argument("--presets", type=Path, default=PRESETS_PATH, help="프리셋 JSON 파일 경로")
    args = ap.parse_args()

    cfg = cfgmod.load(args.config)
    with Bus(pick_port(args.port, cfg.port), cfg.baudrate) as bus:
        hand = Hand(bus, cfg)
        print("모든 관절 토크 꺼짐, 위치 모드. 대시보드에서 토크를 켜세요")

        stop = threading.Event()

        def poll_loop():
            while not stop.is_set():
                hand.poll()
                stop.wait(POLL_PERIOD)

        poller = threading.Thread(target=poll_loop, daemon=True)
        poller.start()
        try:
            uvicorn.run(create_app(hand, args.presets), host=args.host, port=args.http_port)
        finally:
            stop.set()
            poller.join()   # 포트를 닫기 전에 폴링을 멈춤
            hand.shutdown()
            print("모든 관절 토크 꺼짐")


if __name__ == "__main__":
    main()
