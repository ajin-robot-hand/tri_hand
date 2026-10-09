"""tri_hand 카메라 원격 조종: 웹캠 → MediaPipe 손 관절점 21개 → 손가락 굽힘 각도 → server.py 목표 각도.

사람 손가락 → 로봇 손가락 대응
  엄지 → A,  검지 → B,  중지 → C   (약지/새끼는 쓰지 않음)
  사람 첫째 마디(MCP, 엄지는 MCP) 굽힘        → j1
  사람 나머지 마디(PIP+DIP, 엄지는 IP) 굽힘 합 → j2
  A_j0(엄지 요)는 사람 손 동작과의 대응·부호가 확인되지 않아 보내지 않음 (서버의 현재 목표 유지)

굽힘 정도를 0(펼침)~1(최대)로 바꾼 뒤 run_sim.Q_CLOSE(손가락끼리 안 부딪히는 오므림 각도)를 곱함.
손을 놓치면 목표를 보내지 않음 → 로봇은 마지막 목표 자세를 유지.

사용법 (먼저 server.py 실행)
  python teleop.py                 # 기본 웹캠(0번)
  python teleop.py --source 1      # 다른 카메라
  python teleop.py --source a.mp4  # 동영상 파일
  python teleop.py --motors motors.json           # 실물 모터도 함께 구동 (motors.py 참고)
  python teleop.py --motors motors.json --url ""  # 실물만 (시뮬레이션 서버 없이)
  python teleop.py --motors try --url ""          # 보정 없이 실물 시험 (손을 곧게 편 채 시작)
  미리보기 창에서 q: 종료
"""
import argparse
import json
import time
from contextlib import nullcontext
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

import motors
from run_sim import CLOSE_SIGN, Q_CLOSE

MODEL = Path(__file__).parent / "models" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

# MediaPipe 관절점 번호. 앞 3점의 가운데 꺾임 → j1, 나머지 꺾임의 합 → j2
CHAINS = {
    "A": (1, 2, 3, 4),        # 엄지: CMC, MCP, IP, 끝
    "B": (0, 5, 6, 7, 8),     # 검지: 손목, MCP, PIP, DIP, 끝
    "C": (0, 9, 10, 11, 12),  # 중지
}
# 사람 굽힘 각도(rad)를 0~1로 바꾸는 범위 [펼침, 최대 굽힘]. 펼친 손도 추정 잡음으로 0이 아니어서 하한을 둠
# 실측 보정 전 시작값 (본인 손으로 확인 필요)
HUMAN_RANGE = {
    "A": {"j1": (0.15, 0.9), "j2": (0.15, 1.2)},
    "B": {"j1": (0.2, 1.4), "j2": (0.3, 2.6)},
    "C": {"j1": (0.2, 1.4), "j2": (0.3, 2.6)},
}
SMOOTHING = 0.4    # 지수 평활 계수: 새 값 비중. 작을수록 부드럽고 느림
MAX_SPEED = 3.0    # rad/s, 목표 변화 속도 상한. XL430 기본 속도 한계 6.36 rad/s의 절반 이하


def bend(a, b, c) -> float:
    """점 b에서 꺾인 각도(rad). 일직선이면 0"""
    u, v = b - a, c - b
    cos = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
    return float(np.arccos(np.clip(cos, -1.0, 1.0)))


def finger_bends(points: np.ndarray) -> dict[str, dict[str, float]]:
    """21×3 관절점 → 손가락별 {"j1": 첫 꺾임, "j2": 나머지 꺾임 합} (rad)"""
    out = {}
    for finger, chain in CHAINS.items():
        p = points[list(chain)]
        angles = [bend(p[i - 1], p[i], p[i + 1]) for i in range(1, len(p) - 1)]
        out[finger] = {"j1": angles[0], "j2": sum(angles[1:])}
    return out


def retarget(points: np.ndarray) -> dict[str, float]:
    """관절점 → 로봇 목표 각도(rad). 굽힘 정도 0~1 × 오므림 방향 × Q_CLOSE"""
    targets = {}
    for finger, bends in finger_bends(points).items():
        for j, angle in bends.items():
            lo, hi = HUMAN_RANGE[finger][j]
            amount = float(np.clip((angle - lo) / (hi - lo), 0.0, 1.0))
            targets[f"{finger}_{j}"] = CLOSE_SIGN[finger] * Q_CLOSE[j] * amount
    return targets


class Smoother:
    """지수 평활 후 한 번에 움직이는 양을 MAX_SPEED×dt로 제한"""

    def __init__(self):
        self.value: dict[str, float] | None = None

    def __call__(self, raw: dict[str, float], dt: float) -> dict[str, float]:
        if self.value is None:
            self.value = dict(raw)
            return dict(raw)
        step = MAX_SPEED * dt
        for n, q in raw.items():
            prev = self.value[n]
            want = prev + SMOOTHING * (q - prev)
            self.value[n] = prev + float(np.clip(want - prev, -step, step))
        return dict(self.value)


def send(url: str, targets: dict[str, float]) -> str | None:
    """POST /joints. 실패하면 이유 문자열, 성공하면 None"""
    req = urllib.request.Request(f"{url}/joints", data=json.dumps(targets).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=0.2).read()
    except urllib.error.HTTPError as e:
        return f"{e.code} {e.read().decode(errors='replace')[:80]}"
    except (urllib.error.URLError, TimeoutError) as e:
        return f"server unreachable: {e}"
    return None


def ensure_model():
    if not MODEL.exists():
        print(f"손 인식 모델 내려받는 중: {MODEL}")
        MODEL.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL)


def draw(frame, landmarks, lines: list[str]):
    """cv2.putText는 한글을 못 그리므로 lines는 영문만"""
    h, w = frame.shape[:2]
    for lm in landmarks or []:
        cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 3, (0, 255, 0), -1)
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (10, 25 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)


def run(source, url: str, preview: bool, motors_config: Path | None):
    ensure_model()
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"카메라/파일을 열 수 없음: {source}")
    options = HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                    running_mode=RunningMode.VIDEO, num_hands=1)
    smoother = Smoother()
    t0 = last = time.monotonic()
    hand = motors.load(motors_config, MAX_SPEED) if motors_config else nullcontext()
    with HandLandmarker.create_from_options(options) as tracker, hand:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = time.monotonic()
            dt, last = now - last, now
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = tracker.detect_for_video(image, int((now - t0) * 1000))
            if result.hand_world_landmarks:
                # world 관절점: 손 중심 기준 m 단위 3D라 카메라 거리와 무관
                points = np.array([[p.x, p.y, p.z] for p in result.hand_world_landmarks[0]])
                targets = smoother(retarget(points), dt)
                if motors_config:
                    hand.send(targets)
                error = send(url, targets) if url else None
                lines = [f"{n} {q:+.2f}" for n, q in targets.items()] + ([error] if error else [])
                landmarks = result.hand_landmarks[0]
            else:
                lines, landmarks = ["no hand: holding last pose"], None
            if preview:
                draw(frame, landmarks, lines)
                cv2.imshow("tri_hand teleop (q: quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                print(" ".join(lines))
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0", help="카메라 번호 또는 동영상 파일 경로")
    ap.add_argument("--url", default="http://127.0.0.1:8000", help='server.py 주소. ""이면 시뮬레이션에 보내지 않음')
    ap.add_argument("--motors", type=Path, help='motors.json 경로, 또는 "try"(보정 없이 시험). 주면 실물 모터도 구동')
    ap.add_argument("--no-preview", action="store_true", help="창 없이 터미널에 목표 각도 출력")
    args = ap.parse_args()
    run(int(args.source) if args.source.isdigit() else args.source, args.url, not args.no_preview, args.motors)
