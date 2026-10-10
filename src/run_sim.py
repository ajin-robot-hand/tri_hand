"""tri_hand MuJoCo 데모: 세 손가락 및 엄지 대립(Yaw) 관절의 주기적 위치 제어.

사용법
  python run_sim.py              # 뷰어 실행 (macOS는 mjpython run_sim.py)
  python run_sim.py --headless   # 뷰어 없이 수치만 확인 (WSL2/서버 등)
"""
import argparse
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import mujoco
import numpy as np

SCENE = Path(__file__).with_name("scene.xml")

# 모든 굴곡 관절 축이 +X라서 A(위쪽)는 음수, B/C(아래쪽)는 양수 방향이 '오므림'.
CLOSE_SIGN = {"A": -1.0, "B": +1.0, "C": +1.0}
Q_CLOSE = {"j1": 0.3, "j2": 1.2}   # rad, 오므렸을 때 목표 각도 (크기). 이 값까지는 손가락끼리 안 부딪힘
PERIOD = 4.0                       # s, 한 번 오므렸다 펴는 주기
YAW_AMPLITUDE = 0.25               # rad, 엄지 대립(Yaw/A_j0) 회전 진폭 (~14.3도)
# 실물 모터(motors.py) 및 제어 파라미터
YAW_GAIN = 5.0                     # 사람 엄지 좌우 → A_j0 반영 배율. 엄지를 끝까지 벌리면 YAW_GAIN × YAW_AMPLITUDE
YAW_LIMIT = 1.0472                 # rad (60도), A_j0가 갈 수 있는 끝. hand.xml A_j0 range와 같음


def command(t: float) -> dict[str, float]:
    """t 시점의 관절별 목표 각도. 0(펼침) ↔ 1(오므림)을 코사인으로 부드럽게."""
    s = 0.5 * (1.0 - np.cos(2.0 * np.pi * t / PERIOD))
    ctrls = {f"{f}_{j}": CLOSE_SIGN[f] * Q_CLOSE[j] * s
             for f in "ABC" for j in ("j1", "j2")}
    # 7번째 액추에이터: 엄지 요(Yaw / 대립) 회전 관절
    # 파지 시퀀스에 맞춰 대립 각도(Opposition)로 부드럽게 회전
    ctrls["A_j0"] = YAW_AMPLITUDE * np.sin(2.0 * np.pi * t / PERIOD)
    return ctrls


def apply_ctrl(model, data):
    for joint_name, q_des in command(data.time).items():
        data.ctrl[model.actuator(f"{joint_name}_act").id] = q_des


def run_headless(model, data, seconds=8.0):
    try:
        ball = model.body("ball").id
    except KeyError:
        ball = None
    steps = int(seconds / model.opt.timestep)
    for i in range(steps):
        apply_ctrl(model, data)
        mujoco.mj_step(model, data)
        if i % int(1.0 / model.opt.timestep) == 0:
            ball_str = f"ball(mm)={np.round(data.xpos[ball]*1000, 1)}  " if ball is not None else ""
            q_yaw = data.qpos[model.joint("A_j0").qposadr[0]]
            print(f"t={data.time:4.1f}s  {ball_str}A_j0={q_yaw:+.2f}rad  "
                  f"contacts={data.ncon}  max|qvel|={np.abs(data.qvel[:7]).max():.2f}")
    assert np.isfinite(data.qpos).all(), "시뮬레이션이 발산했습니다"
    print("\n✅ 헤드리스 시뮬레이션 검증 완료 (수치 안정성 및 발산 없음)")


def run_viewer(model, data):
    import mujoco.viewer
    with mujoco.viewer.launch_passive(model, data) as v:
        v.cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
        v.cam.fixedcamid = model.camera("iso").id
        while v.is_running():
            t0 = time.time()
            apply_ctrl(model, data)
            mujoco.mj_step(model, data)
            v.sync()
            time.sleep(max(0.0, model.opt.timestep - (time.time() - t0)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    (run_headless if args.headless else run_viewer)(model, data)
