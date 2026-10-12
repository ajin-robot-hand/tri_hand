"""tri_hand 실물 HTTP 제어 서버: src/server.py와 같은 API로 U2D2에 연결된 XL430을 제어.

대시보드(src/dashboard.html)를 그대로 씀.

사용법
  python real/server.py                     # http://127.0.0.1:8000
  python real/server.py --port /dev/tty.usbserial-XXXX --host 0.0.0.0

  python real/server.py --no-home           # 시작할 때 움직이지 않고 토크를 끈 채로 둠

시뮬레이션 서버와 다른 점
  - 시작하면 위치 모드로 두고 전 관절 토크를 켠 뒤 0 rad(config의 zero tick)로 천천히 옮김.
    --no-home이면 토크를 끈 채로 둠. 서버를 끌 때는 토크를 끔
  - 시작할 때 모터의 Min/Max Position Limit를 config의 관절 범위로 맞춤 (다를 때만 EEPROM에 씀)
  - kp, kv는 XL430 Position P/D Gain 레지스터 값 그대로 (0~16383, 출고값 640/0).
    시뮬레이션의 N·m/rad 단위와 다르므로 프리셋 파일도 따로 씀 (real/presets.json)
  - torque_limit(N·m)은 Goal PWM으로 근사: 1.4 N·m(12V 정지 토크) = PWM 885
  - forces는 Present Load(정격 대비 %)를 1.4 N·m에 곱한 근사값
  - contacts는 센서가 없어 null. /reset 없음
  - state에 hw_errors(관절별 하드웨어 오류), temperatures(°C)/voltages(V, 1 Hz 갱신),
    comm_error(마지막 통신 오류, 없으면 null), packets(tx/rx_errors 누적 카운터)가 추가됨
  - 목표 전송(/joints, /velocities, /grasp, 프리셋 적용)은 GroupSyncWrite로 관절 전체를 한 패킷에 보냄.
    상태 폴링은 20 ms(위치/속도/부하)와 1 Hz(온도/전압/하드웨어 오류)로 나눠서 읽음
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
from dxl import TICKS_PER_REV, VEL_UNIT, Bus, DxlError, hw_errors, pick_port, rad_to_tick, tick_to_rad

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from run_sim import CLOSE_SIGN, Q_CLOSE  # noqa: E402

DASHBOARD = SRC / "dashboard.html"
PRESETS_PATH = Path(__file__).with_name("presets.json")   # --presets 로 변경 가능

STALL_TORQUE = 1.4   # N·m, XL430-W250 12V 정지 토크 (hand.xml forcerange와 같음)
PWM_MAX = 885        # Goal PWM 100%
GAIN_MAX = 16383     # Position P/D Gain 레지스터 범위
MODE_CODE = {"position": 3, "velocity": 1}   # Operating Mode 레지스터 값
POLL_PERIOD = 0.02   # s, 상태(위치/속도/부하) 읽기 주기
SLOW_POLL_TICKS = 50  # POLL_PERIOD 기준 50회 = 1 s, 온도/전압/하드웨어 오류 읽기 주기
HOME_SPEED = 0.5     # rad/s, 시작할 때 0 rad로 옮기는 속도
HOME_TIMEOUT = 10.0  # s
HOME_TOLERANCE = 20  # tick (약 1.8°), 도착으로 보는 오차
RECOVERY_TIMEOUT = 5.0  # s, Hardware_Error 감지 후 이 시간 안에 복귀하면 성공 (계획서 KPI)

ModeName = Literal["position", "velocity"]

JITTER_BIN_US = 100       # 지터 히스토그램 한 칸 (0.1 ms)
JITTER_BINS = 200         # 0~20 ms 범위, 넘으면 오버플로 칸
OVERRUN_FACTOR = 1.5      # 한 주기가 period×이 값을 넘으면 누락 프레임으로 셈


class LoopStats:
    """제어 루프 주기 편차(지터) 집계 (T-11). monotonic_ns 간격을 누적해 평균/최대/p95와
    누락 프레임(과주기)을 산출. 계획서 판정: 지터 < 2 ms, 누락 프레임 < 0.1%.

    24h·50 Hz면 샘플이 수백만 개라 편차를 리스트로 들지 않고 0.1 ms 히스토그램으로 담음
    (메모리 고정, p95는 누적합에서 상한 추정값으로 읽음).
    """

    def __init__(self, period: float):
        self.period_ns = round(period * 1e9)
        self.overrun_ns = round(self.period_ns * OVERRUN_FACTOR)
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self._last: int | None = None
            self._first: int | None = None
            self.count = 0            # 측정된 주기 간격 수(= tick 수 - 1)
            self.dropped = 0
            self._dev_sum_ns = 0.0
            self.max_dev_ns = 0
            self._hist = [0] * (JITTER_BINS + 1)   # 마지막 칸은 20 ms 초과 오버플로

    def tick(self, now_ns: int):
        with self.lock:
            if self._last is not None:
                dt = now_ns - self._last
                dev = abs(dt - self.period_ns)
                self.count += 1
                self._dev_sum_ns += dev
                self.max_dev_ns = max(self.max_dev_ns, dev)
                if dt > self.overrun_ns:
                    self.dropped += 1
                b = min(dev // (JITTER_BIN_US * 1000), JITTER_BINS)
                self._hist[b] += 1
            else:
                self._first = now_ns
            self._last = now_ns

    def _p95_ns(self) -> int:
        """히스토그램에서 95번째 백분위 편차의 상한(칸 윗경계)."""
        target = self.count * 0.95
        cum = 0
        for b, n in enumerate(self._hist):
            cum += n
            if cum >= target:
                return (b + 1) * JITTER_BIN_US * 1000
        return 0

    def summary(self) -> dict:
        with self.lock:
            if self.count == 0:
                return {"hz": 0.0, "samples": 0, "jitter_ms_mean": 0.0, "jitter_ms_max": 0.0,
                        "jitter_ms_p95": 0.0, "dropped_frames": 0, "dropped_frac": 0.0}
            span_s = (self._last - self._first) / 1e9
            return {
                "hz": self.count / span_s if span_s > 0 else 0.0,
                "samples": self.count,
                "jitter_ms_mean": self._dev_sum_ns / self.count / 1e6,
                "jitter_ms_max": self.max_dev_ns / 1e6,
                "jitter_ms_p95": self._p95_ns() / 1e6,
                "dropped_frames": self.dropped,
                "dropped_frac": self.dropped / self.count,
            }


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

    def __init__(self, bus, cfg: cfgmod.Config, auto_recover: bool = True):
        self.bus, self.cfg = bus, cfg
        self.auto_recover = auto_recover
        self.lock = threading.RLock()   # 폴링 스레드와 HTTP 요청이 버스를 함께 씀
        self.t0 = time.monotonic()
        self.ids = [j.id for j in cfg.joints.values()]
        self.servos: dict[str, Servo] = {}
        self.reading = {n: {"q": 0.0, "qd": 0.0, "f": 0.0} for n in cfg.joints}
        self.errors: dict[str, list[str]] = {n: [] for n in cfg.joints}
        self.temperatures: dict[str, float] = {n: 0.0 for n in cfg.joints}
        self.voltages: dict[str, float] = {n: 0.0 for n in cfg.joints}
        self.comm_error: str | None = None
        self.loop_stats = LoopStats(POLL_PERIOD)
        self.fault_since: dict[str, float | None] = {n: None for n in cfg.joints}   # 관절별 현재 장애 시작 시각
        self.fault_failed: dict[str, bool] = {n: False for n in cfg.joints}         # 5초 내 미복귀로 실패 집계됨
        self.sys_fault_since: float | None = None   # 하나라도 장애면 시스템 다운 시작 시각
        self.downtime_s = 0.0                       # 닫힌 시스템 다운 구간 누적
        self.reboots = {"attempts": 0, "successes": 0, "failures": 0}
        self.logger = None          # runlog.CsvLogger, main()에서 --log일 때만 연결 (T-12)
        self._comm_logged = False
        with self.lock:
            for n, j in cfg.joints.items():
                self._setup(n, j)
        self.poll()
        self.poll_slow()

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
        """현재 각도/속도/부하를 읽어 둠(20 ms 주기, present_load~present_position 10 B/모터).

        실패하면 이전 값을 유지하고 comm_error에 남김. 온도/전압/하드웨어 오류는 변화가 느려
        poll_slow()가 1 Hz로 따로 읽음(D-03: 20 ms 핫루프에 불필요한 바이트를 올리지 않음).
        """
        with self.lock:
            try:
                regs = self.bus.sync_read(self.ids, "present_load", "present_position")
            except DxlError as e:
                self.comm_error = str(e)
                return
            self.comm_error = None
            for n, j in self.cfg.joints.items():
                m = regs[j.id]
                self.reading[n] = {"q": tick_to_rad(m["present_position"], j.zero, j.sign),
                                   "qd": j.sign * m["present_velocity"] * VEL_UNIT,
                                   "f": j.sign * m["present_load"] / 1000 * STALL_TORQUE}

    def poll_slow(self):
        """온도/전압/하드웨어 오류를 읽어 둠(1 Hz 주기). 실패해도 이전 값을 유지하고 comm_error에 남김.

        hardware_error_status(70)~present_temperature(146) 구간을 한 번에 읽음 — 1 Hz에서는
        바이트 수가 중요하지 않으므로 중간의 운동 레지스터까지 함께 읽히는 것은 허용(단순함 우선).
        """
        with self.lock:
            try:
                regs = self.bus.sync_read(self.ids, "hardware_error_status", "present_temperature")
            except DxlError as e:
                self.comm_error = str(e)
                if self.logger and not self._comm_logged:
                    self.logger.error_event(time.monotonic() - self.t0, "comm", "", str(e))
                    self._comm_logged = True
                return
            self.comm_error = None
            self._comm_logged = False
            for n, j in self.cfg.joints.items():
                m = regs[j.id]
                self.errors[n] = hw_errors(m["hardware_error_status"])
                self.temperatures[n] = m["present_temperature"]
                self.voltages[n] = m["present_input_voltage"] / 10
            if self.logger:
                self.logger.joint_sample(time.monotonic() - self.t0, self.reading,
                                         self.temperatures, self.voltages)

    def _reboot(self, n: str):
        self.reboots["attempts"] += 1
        try:
            self.bus.reboot(self.cfg.joints[n].id)
        except DxlError as e:
            self.comm_error = str(e)

    def _restore(self, n: str):
        """Reboot 뒤 되돌아간 설정(운영 모드/게인/토크/목표)을 마지막 상태로 다시 씀."""
        j, s = self.cfg.joints[n], self.servos[n]
        try:
            self.bus.write(j.id, "operating_mode", MODE_CODE[s.mode])
            self.bus.write(j.id, "position_p_gain", s.kp)
            self.bus.write(j.id, "position_d_gain", s.kv)
            self.bus.write(j.id, "goal_pwm", pwm_from_torque(s.torque_limit))
            if s.torque:
                self.bus.write(j.id, "torque_enable", 1)
                self._send_goal(n, s.target)
        except DxlError as e:
            self.comm_error = str(e)

    def check_recovery(self, now: float | None = None) -> list[dict]:
        """poll_slow가 읽어 둔 hw_errors를 보고 자동 Reboot·복구 판정·다운타임을 집계(T-13).

        장애 감지 → Reboot 1회 → 다음 slow tick에서 오류가 사라졌으면 복구 성공(RECOVERY_TIMEOUT
        이내면 성공, 넘기면 실패로 셈). 반환값은 이번 호출에서 일어난 이벤트(T-12 error_event 로깅용).
        """
        now = time.monotonic() if now is None else now
        events: list[dict] = []
        with self.lock:
            for n in self.cfg.joints:
                faulted = bool(self.errors[n])
                if faulted and self.fault_since[n] is None:
                    self.fault_since[n] = now
                    self.fault_failed[n] = False
                    if self.auto_recover:
                        self._reboot(n)
                    events.append({"kind": "reboot", "joint": n, "detail": ",".join(self.errors[n])})
                elif faulted and not self.fault_failed[n] and now - self.fault_since[n] > RECOVERY_TIMEOUT:
                    self.fault_failed[n] = True
                    self.reboots["failures"] += 1
                    events.append({"kind": "recover_failed", "joint": n,
                                   "detail": f"{now - self.fault_since[n]:.1f}s"})
                elif not faulted and self.fault_since[n] is not None:
                    if not self.fault_failed[n]:
                        self.reboots["successes"] += 1
                        events.append({"kind": "recover_ok", "joint": n,
                                       "detail": f"{now - self.fault_since[n]:.1f}s"})
                    self.fault_since[n] = None
                    if self.auto_recover:
                        self._restore(n)
            any_fault = any(self.fault_since[n] is not None for n in self.cfg.joints)
            if any_fault and self.sys_fault_since is None:
                self.sys_fault_since = now
            elif not any_fault and self.sys_fault_since is not None:
                self.downtime_s += now - self.sys_fault_since
                self.sys_fault_since = None
        if self.logger:
            for e in events:
                self.logger.error_event(now - self.t0, e["kind"], e["joint"], e["detail"])
        return events

    def availability(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        with self.lock:
            total = now - self.t0
            open_down = (now - self.sys_fault_since) if self.sys_fault_since is not None else 0.0
            downtime = self.downtime_s + open_down
            return {"availability": 1 - downtime / total if total > 0 else 1.0,
                    "downtime_s": downtime, "reboots": dict(self.reboots)}

    def log_run_summary(self):
        """현재 지터·패킷·가용률을 run.csv에 스냅샷으로 남김 (주기적 호출 + 종료 시)."""
        if self.logger:
            self.logger.run_summary(time.monotonic() - self.t0,
                                    {"tx": self.bus.tx_count, "rx_errors": self.bus.rx_error_count},
                                    self.loop_stats.summary(), self.availability())

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
                "temperatures": dict(self.temperatures),
                "voltages": dict(self.voltages),
                "comm_error": self.comm_error,
                "packets": {"tx": self.bus.tx_count, "rx_errors": self.bus.rx_error_count},
                "loop": self.loop_stats.summary(),
                **self.availability(),
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
        """여러 관절의 목표를 GroupSyncWrite 1패킷으로 동시에 보냄(D-02: 관절별 TxRx 왕복 제거).

        한 호출의 모든 목표가 같은 모드(= 같은 레지스터: goal_position 또는 goal_velocity)이므로
        단일 sync_write로 묶을 수 있음 — _require가 이를 보장.
        """
        reg_name = "goal_position" if mode == "position" else "goal_velocity"
        applied, clipped = {}, []
        with self.lock:
            self._require(targets, mode)
            raw = {}
            for n, v in targets.items():
                lo, hi = self.range(n, mode)
                c = min(max(v, lo), hi)
                if c != v:
                    clipped.append(n)
                applied[n] = c
                j = self.cfg.joints[n]
                raw[j.id] = rad_to_tick(c, j.zero, j.sign) if mode == "position" else round(j.sign * c / VEL_UNIT)
            self.bus.sync_write(reg_name, raw)
            for n, c in applied.items():
                self.servos[n].target = c
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

    def home(self, speed: float = HOME_SPEED, timeout: float = HOME_TIMEOUT) -> dict[str, float]:
        """전 관절 토크를 켜고 0 rad(config의 zero tick)로 천천히 옮김. 범위 밖 관절도 목표가 범위 안이라 움직일 수 있음.

        이동 중에만 Profile Velocity로 속도를 제한하고 끝나면 원래 값으로 되돌림.
        timeout 안에 도착하지 못한 관절 → 현재 각도 (걸림, 과부하 등).
        """
        with self.lock:
            saved = {}
            for n, j in self.cfg.joints.items():
                s = self.servos[n]
                if s.mode != "position":
                    self.bus.write(j.id, "torque_enable", 0)
                    self.bus.write(j.id, "operating_mode", MODE_CODE["position"])
                    s.mode = "position"
                saved[n] = self.bus.read(j.id, "profile_velocity")
                self.bus.write(j.id, "profile_velocity", max(1, round(speed / VEL_UNIT)))
                # 토크를 켜는 순간 모터가 목표를 현재 위치로 덮어쓰므로, 목표는 켠 뒤에 씀
                self.bus.write(j.id, "torque_enable", 1)
                s.torque = True
                self._send_goal(n, 0.0)
        tol = HOME_TOLERANCE * 2 * math.pi / TICKS_PER_REV
        deadline = time.monotonic() + timeout
        while True:
            self.poll()
            far = {n: r["q"] for n, r in self.reading.items() if abs(r["q"]) > tol}
            if not far or time.monotonic() > deadline:
                break
            time.sleep(POLL_PERIOD)
        with self.lock:
            for n, j in self.cfg.joints.items():
                self.bus.write(j.id, "profile_velocity", saved[n])
        return far

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
    ap.add_argument("--no-home", action="store_true", help="시작할 때 0 rad로 옮기지 않고 토크를 끈 채로 둠")
    ap.add_argument("--no-recover", action="store_true", help="Hardware_Error 자동 Reboot 복구를 끔")
    ap.add_argument("--log", type=Path, metavar="DIR", help="CSV 로깅을 켜고 DIR/<타임스탬프>/ 에 기록 (T-12)")
    args = ap.parse_args()

    cfg = cfgmod.load(args.config)
    with Bus(pick_port(args.port, cfg.port), cfg.baudrate) as bus:
        hand = Hand(bus, cfg, auto_recover=not args.no_recover)
        stop = threading.Event()
        poller = None   # 홈잉 중 Ctrl+C가 나도 finally가 참조할 수 있게 먼저 둠
        # 홈잉(home)부터 try 안: 토크를 켜는 순간 이후 어디서 끊겨도 finally의 토크 off가 실행됨
        try:
            if args.log:
                import runlog
                run_dir = runlog.new_run_dir(args.log)
                hand.logger = runlog.CsvLogger(run_dir)
                print(f"CSV 로깅: {run_dir}")
            if args.no_home:
                print("모든 관절 토크 꺼짐, 위치 모드. 대시보드에서 토크를 켜세요")
            else:
                print(f"전 관절 토크 켜고 0 rad(zero tick)로 이동 중 ({HOME_SPEED} rad/s)...")
                far = hand.home()
                if far:
                    print(f"⚠ {HOME_TIMEOUT:.0f}초 안에 0 rad에 도착하지 못함 (토크는 켜진 채 목표 0 유지): "
                          f"{', '.join(f'{n} {q:+.2f} rad' for n, q in far.items())}")
                else:
                    print("모든 관절 0 rad 도착, 토크 켜짐")

            def poll_loop():
                """고정 데드라인으로 POLL_PERIOD마다 돈다(드리프트 누적 없음). 매 주기 시작 시각을
                LoopStats에 넣어 50 Hz 주기 편차(지터)와 누락 프레임을 집계한다(T-11)."""
                period_ns = round(POLL_PERIOD * 1e9)
                next_ns = time.monotonic_ns()
                tick = 0
                while not stop.is_set():
                    hand.loop_stats.tick(time.monotonic_ns())
                    hand.poll()
                    tick += 1
                    if tick % SLOW_POLL_TICKS == 0:
                        hand.poll_slow()
                        hand.check_recovery()
                    if tick % (SLOW_POLL_TICKS * 60) == 0:
                        hand.log_run_summary()   # 1분마다 run.csv 스냅샷
                    next_ns += period_ns
                    sleep_s = (next_ns - time.monotonic_ns()) / 1e9
                    if sleep_s > 0:
                        stop.wait(sleep_s)   # 과주기면 자지 않고 바로 다음 루프 → 다음 tick이 지연을 집계

            poller = threading.Thread(target=poll_loop, daemon=True)
            poller.start()
            uvicorn.run(create_app(hand, args.presets), host=args.host, port=args.http_port)
        finally:
            stop.set()
            if poller is not None:
                poller.join()   # 포트를 닫기 전에 폴링을 멈춤
            hand.shutdown()
            if hand.logger:
                hand.log_run_summary()
                hand.logger.close()
            print("모든 관절 토크 꺼짐")


if __name__ == "__main__":
    main()
