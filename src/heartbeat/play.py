"""Heartbeat 재생 진입점: 음원 + MuJoCo를 박자에 맞춰 돌린다.

    python src/heartbeat/play.py              # 음원 + 뷰어 (기본)
    python src/heartbeat/play.py --headless   # 음원·GUI 없이 전구간 수치 검증
    python src/heartbeat/play.py --mute       # 뷰어만 (음원 장치 없을 때)

동기화 원리
  1. 마스터 클럭은 오디오 스트림의 재생 위치(audio.AudioClock.t) 하나뿐이다.
  2. 목표 자세는 전부 `choreo(t)`로 계산한다. 누적되는 상태가 없으니 오차도 누적되지 않는다.
  3. 물리 스텝은 클럭을 따라간다(catch-up). 시뮬이 밀려도 다음 프레임에서 시각이 맞춰진다.
  4. 위치 제어기가 목표를 따라가는 데 걸리는 시간만큼 `LEAD`만큼 미리 보낸다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/ 를 import 경로에

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import mujoco
import numpy as np

from heartbeat.choreo import END, START, choreo
from heartbeat.grid import BAR_PERIOD, bar_beat_to_time, time_to_bar_beat
from heartbeat.schedule import FIRST_BAR, LAST_BAR, get_motion
from heartbeat.validate import validate_all

SCENE = Path(__file__).resolve().parents[1] / "scene.xml"
AUDIO = Path(__file__).resolve().parents[2] / "docs" / "heartbeat" / "Heartbeat.mp3"

# --- 보정 상수 (측정해서 채우는 값) -------------------------------------------
# --headless 스윕으로 측정한 값. 0→0.140 / 0.03→0.062 / 0.05→0.027 / 0.08→0.083 rad
LEAD = 0.050          # s. 위치 제어기(kp=12, kv=0.5) 추종 지연 보정
AUDIO_OFFSET = 0.0    # s. 음원 재생 지연 보정. 손이 늦으면 음수로 (Phase 5)
# 영상↔음원 정렬: mp3_t = video_t + 0.966 s. motions.json의 영상 시각 주석은 이 값을 쓴 것.
VIDEO_OFFSET = 0.966

MAX_CATCHUP_STEPS = 50   # 한 프레임에서 따라잡을 최대 물리 스텝 수 (렉이 나도 폭주 방지)
RESYNC_THRESHOLD = 0.25  # s. 이보다 뒤처지면 스텝으로 메우지 않고 시각을 바로 맞춘다


def apply_ctrl(model, data, t: float) -> None:
    """t 시점의 목표를 액추에이터에 싣는다."""
    for joint, q_des in choreo(t).items():
        data.ctrl[model.actuator(f"{joint}_act").id] = q_des


def _joint_qpos(model, data) -> np.ndarray:
    """액추에이터 순서에 맞춘 현재 관절 각도."""
    return np.array([data.qpos[model.joint(model.actuator(a).trnid[0]).qposadr[0]]
                     for a in range(model.nu)])


def reset_to_start(model, data) -> None:
    """음원이 시작되기 전에 이미 첫 자세로 서 있게 한다.

    qpos=0에서 출발시키면 첫 마디에 제어기가 자세를 따라잡느라 큰 튐이 생긴다.
    연출상으로도 손은 음악이 나오기 전부터 '누운 자세'로 있어야 맞다.
    """
    mujoco.mj_resetData(model, data)
    for joint, q in choreo(START).items():
        data.qpos[model.joint(joint).qposadr[0]] = q
    mujoco.mj_forward(model, data)


def _bar_label(bar: int) -> str:
    if not (FIRST_BAR <= bar <= LAST_BAR):
        return "outro"
    return get_motion(bar)[0]


# ---------------------------------------------------------------- 헤드리스
def run_headless(model, data, lead: float = LEAD) -> None:
    """가상 시간으로 전구간을 빠르게 돌며 발산·자가 충돌·추종 오차를 본다."""
    reset_to_start(model, data)
    floor = model.geom("floor").id
    dt = model.opt.timestep
    names = [model.joint(model.actuator(a).trnid[0]).name for a in range(model.nu)]
    print(f"헤드리스 전구간: {START:.3f} ~ {END:.3f} s  (LEAD={lead*1000:.0f} ms)\n")
    print(" 마디   시각     동작     접촉  최대 추종오차  최대 관절속도")

    stats = {"qerr": 0.0, "qvel": 0.0, "contacts": 0}
    bar_acc = {"qerr": 0.0, "qvel": 0.0, "contacts": 0}
    bar = 0
    for step in range(int((END - START) / dt) + 1):
        t = START + step * dt
        apply_ctrl(model, data, t + lead)
        mujoco.mj_step(model, data)

        # 지금 눈에 보이는 자세가 '지금 시각의 목표'를 얼마나 따라왔는가
        want = choreo(t)
        qerr = float(np.abs(_joint_qpos(model, data)
                            - np.array([want[n] for n in names])).max())
        qvel = float(np.abs(data.qvel[:model.nu]).max())
        self_contacts = sum(1 for c in data.contact[:data.ncon]
                            if floor not in (c.geom1, c.geom2))
        if self_contacts:
            g = [(model.geom(c.geom1).name, model.geom(c.geom2).name)
                 for c in data.contact[:data.ncon] if floor not in (c.geom1, c.geom2)]
            raise RuntimeError(f"자가 충돌 t={t:.3f}s (마디 {time_to_bar_beat(t)[0]}): {g}")

        bar_acc["qerr"] = max(bar_acc["qerr"], qerr)
        bar_acc["qvel"] = max(bar_acc["qvel"], qvel)
        bar_acc["contacts"] = max(bar_acc["contacts"], data.ncon)

        cur_bar = time_to_bar_beat(t)[0]
        if cur_bar != bar:
            if bar:
                print(f"  {bar:3d}  {bar_beat_to_time(bar):6.3f}s  {_bar_label(bar):<7}"
                      f"  {bar_acc['contacts']:3d}   {bar_acc['qerr']:8.4f} rad"
                      f"   {bar_acc['qvel']:6.2f} rad/s")
            for k in stats:
                stats[k] = max(stats[k], bar_acc[k])
            bar_acc = {"qerr": 0.0, "qvel": 0.0, "contacts": 0}
            bar = cur_bar

    assert np.isfinite(data.qpos).all(), "시뮬레이션이 발산했습니다"
    print(f"\n✅ 전구간 완주: 발산 없음 · 자가 충돌 0 · 바닥 외 접촉 0")
    print(f"   최대 추종 오차 {stats['qerr']:.4f} rad   최대 관절 속도 {stats['qvel']:.2f} rad/s"
          f"   (속도 상한 3.0 rad/s)")
    if stats["qerr"] > 0.05:
        print(f"   ⚠ 추종 오차가 0.05 rad을 넘습니다. LEAD({lead*1000:.0f} ms)를 키워 보세요.")


# ------------------------------------------------------------------- 뷰어
def run_viewer(model, data, clock, lead: float = LEAD) -> None:
    """마스터 클럭(음원 재생 위치)을 따라가며 뷰어를 돌린다."""
    import mujoco.viewer

    reset_to_start(model, data)
    with mujoco.viewer.launch_passive(model, data, show_left_ui=False,
                                      show_right_ui=False) as v:
        v.cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
        v.cam.fixedcamid = model.camera("iso").id
        clock.start()
        bar = 0
        while v.is_running():
            t = clock.t
            if t >= END:
                break
            behind = (t - START) - data.time
            if behind > RESYNC_THRESHOLD:
                # 렌더링이 밀려 물리가 한참 뒤처졌다. 스텝으로 메우지 않고 시각을 맞춘다.
                # (위치 제어라 자세는 다음 몇 스텝 안에 목표를 따라잡는다)
                print(f"  ⚠ {behind*1000:.0f} ms 뒤처져 시각을 맞춥니다 (t={t:.2f}s)")
                data.time = t - START
            else:
                # 클럭이 가리키는 시각까지 물리를 따라잡는다
                for _ in range(MAX_CATCHUP_STEPS):
                    if data.time >= t - START:
                        break
                    apply_ctrl(model, data, START + data.time + lead)
                    mujoco.mj_step(model, data)
            v.sync()

            cur_bar = time_to_bar_beat(t)[0]
            if cur_bar != bar and t >= START:
                bar = cur_bar
                print(f"  마디 {bar:3d}  {t:6.2f}s  {_bar_label(bar)}")
            time.sleep(0.002)   # 렌더 루프가 CPU를 다 쓰지 않게
        clock.stop()
    print("\n재생 종료 — 중립 자세로 복귀했습니다.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Heartbeat 비트 연출 재생")
    ap.add_argument("--headless", action="store_true",
                    help="음원·GUI 없이 전구간 수치 검증 (빠름)")
    ap.add_argument("--mute", action="store_true",
                    help="뷰어만 실행. 음원 대신 실시간 클럭을 쓴다")
    ap.add_argument("--audio", type=Path, default=AUDIO, help="음원 파일 경로")
    ap.add_argument("--lead", type=float, default=LEAD, help="추종 지연 보정(s)")
    ap.add_argument("--offset", type=float, default=AUDIO_OFFSET,
                    help="음원 지연 보정(s). 손이 늦게 움직이면 음수로")
    args = ap.parse_args(argv)

    validate_all(verbose=True)
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)

    if args.headless:
        run_headless(model, data, lead=args.lead)
        return 0

    from heartbeat.audio import AudioClock, SilentClock

    if args.mute:
        clock = SilentClock(offset=args.offset, stop_at=END)
    else:
        try:
            clock = AudioClock(args.audio, offset=args.offset, stop_at=END)
        except Exception as e:   # 오디오 장치/디코더 문제로 재생 자체를 포기하지 않는다
            print(f"⚠ 음원을 열 수 없어 무음으로 실행합니다: {e}", file=sys.stderr)
            clock = SilentClock(offset=args.offset, stop_at=END)

    print(f"\n▶ 재생: 마디 {FIRST_BAR}~{LAST_BAR}  "
          f"(음원 {START:.2f}~{END:.2f}s = 영상 {START-VIDEO_OFFSET:.2f}~{END-VIDEO_OFFSET:.2f}s), "
          f"1마디 {BAR_PERIOD:.3f}s\n")
    run_viewer(model, data, clock, lead=args.lead)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
