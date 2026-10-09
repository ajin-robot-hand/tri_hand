"""config.json 읽기와 검증. 실물 배선이 바뀌면 config.json만 고치고 check.py로 확인."""
import json
from dataclasses import dataclass
from pathlib import Path

from dxl import BAUDRATES, TICKS_PER_REV

CONFIG_PATH = Path(__file__).with_name("config.json")


@dataclass(frozen=True)
class JointCfg:
    id: int
    sign: int                   # 모터 tick 증가 방향이 시뮬레이션 관절 +방향이면 +1, 반대면 -1
    zero: int                   # 관절 0 rad(시뮬레이션 초기 자세)일 때의 Present Position tick
    range: tuple[float, float]  # rad, 시뮬레이션 ctrlrange와 같게 유지


@dataclass(frozen=True)
class Config:
    port: str | None            # None이면 U2D2 포트 자동 탐색
    baudrate: int
    joints: dict[str, JointCfg]


def load(path: Path = CONFIG_PATH) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    joints = {n: JointCfg(id=j["id"], sign=j["sign"], zero=j["zero"], range=tuple(j["range"]))
              for n, j in raw["joints"].items()}
    cfg = Config(port=raw.get("port"), baudrate=raw["baudrate"], joints=joints)
    errors = validate(cfg)
    if errors:
        raise ValueError(f"{path} 설정 오류:\n  " + "\n  ".join(errors))
    return cfg


def validate(cfg: Config) -> list[str]:
    errors = []
    if cfg.baudrate not in BAUDRATES.values():
        errors.append(f"baudrate {cfg.baudrate}는 XL430이 지원하지 않음: {sorted(BAUDRATES.values())}")
    ids: dict[int, str] = {}
    for n, j in cfg.joints.items():
        if not 0 <= j.id <= 252:
            errors.append(f"{n}: id {j.id}는 0~252 범위 밖")
        if j.id in ids:
            errors.append(f"{n}: id {j.id}가 {ids[j.id]}와 중복")
        ids.setdefault(j.id, n)
        if j.sign not in (1, -1):
            errors.append(f"{n}: sign은 1 또는 -1 이어야 함 ({j.sign})")
        if not 0 <= j.zero < TICKS_PER_REV:
            errors.append(f"{n}: zero {j.zero}는 0~{TICKS_PER_REV - 1} 범위 밖")
        if len(j.range) != 2 or not j.range[0] < j.range[1]:
            errors.append(f"{n}: range는 [하한, 상한] 이어야 함 ({list(j.range)})")
    return errors
