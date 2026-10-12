"""CSV 로깅 (T-12). SQLite+ERD 대신 append-only CSV 3종으로 계획서 샘플링 요구를 충족.

파일 (run 디렉터리 ``logs/<YYYYmmdd-HHMMSS>/``):
  joint_sample.csv  1 Hz. Position / Load / Temperature (+전압). 계획서 [Page 5] 샘플링 요구.
  error_event.csv   이벤트 발생 시. 통신 오류·하드웨어 오류·Reboot/복구 (패킷 에러 상세 로그).
  run.csv           주기적 스냅샷 + 종료 요약. 지터·패킷 에러율·가용률 (별도 테이블 대신 메타 행).

append-only이고 매 write마다 flush하므로, 24h 구동 중 프로세스가 죽어도 그 시점까지의 측정이
남는다 — 인메모리 카운터(Bus.tx_count 등)가 재시작 시 0으로 리셋되는 한계를 영속 로그로 덮는다.
"""
import csv
from datetime import datetime
from pathlib import Path

JOINT_HEADER = ["ts", "t", "joint", "position_rad", "load_nm", "temperature_c", "voltage_v"]
ERROR_HEADER = ["ts", "t", "kind", "joint", "detail"]
RUN_HEADER = ["ts", "duration_s", "tx_total", "rx_error_total", "packet_error_rate",
              "jitter_ms_p95", "dropped_frac", "availability", "downtime_s",
              "reboot_attempts", "reboot_successes", "reboot_failures"]


def new_run_dir(base: Path) -> Path:
    return Path(base) / datetime.now().strftime("%Y%m%d-%H%M%S")


class CsvLogger:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._joint_w, self._joint_f = self._open("joint_sample.csv", JOINT_HEADER)
        self._error_w, self._error_f = self._open("error_event.csv", ERROR_HEADER)
        self._run_w, self._run_f = self._open("run.csv", RUN_HEADER)

    def _open(self, name: str, header: list[str]):
        f = open(self.dir / name, "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(header)
        f.flush()
        return w, f

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="milliseconds")

    def joint_sample(self, t: float, readings: dict, temps: dict, voltages: dict):
        ts = self._now()
        for n, r in readings.items():
            self._joint_w.writerow([ts, f"{t:.3f}", n, f"{r['q']:.5f}", f"{r['f']:.5f}",
                                    temps.get(n, ""), voltages.get(n, "")])
        self._joint_f.flush()

    def error_event(self, t: float, kind: str, joint: str, detail: str):
        self._error_w.writerow([self._now(), f"{t:.3f}", kind, joint, detail])
        self._error_f.flush()

    def run_summary(self, duration_s: float, packets: dict, loop: dict, availability: dict):
        tx, rx = packets["tx"], packets["rx_errors"]
        self._run_w.writerow([
            self._now(), f"{duration_s:.1f}", tx, rx,
            f"{rx / tx:.6f}" if tx else "0",
            f"{loop['jitter_ms_p95']:.3f}", f"{loop['dropped_frac']:.6f}",
            f"{availability['availability']:.6f}", f"{availability['downtime_s']:.1f}",
            availability["reboots"]["attempts"], availability["reboots"]["successes"],
            availability["reboots"]["failures"]])
        self._run_f.flush()

    def close(self):
        for f in (self._joint_f, self._error_f, self._run_f):
            try:
                f.close()
            except OSError:
                pass
