"""Heartbeat 시간표 단위 테스트. 음원·GUI·실물 없이 전부 돈다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from heartbeat import choreo as choreo_mod                      # noqa: E402
from heartbeat import schedule as sched                         # noqa: E402
from heartbeat import validate as val                           # noqa: E402
from heartbeat.choreo import choreo, pose_norm, to_rad          # noqa: E402
from heartbeat.grid import (BAR_PERIOD, BARS, BEAT_PERIOD,      # noqa: E402
                            END, FIRST_DOWNBEAT, bar_beat_to_time,
                            snap_to_grid, time_to_bar_beat)
from motors import safe_range                                   # noqa: E402
from run_sim import CLOSE_SIGN, Q_CLOSE                         # noqa: E402

JOINTS = set(sched.JOINTS)


# ------------------------------------------------------------------ 격자
def test_phase1_bar_one_starts_at_first_downbeat():
    assert bar_beat_to_time(1, 0.0) == pytest.approx(FIRST_DOWNBEAT)


def test_phase1_bars_are_evenly_spaced_without_drift():
    assert bar_beat_to_time(2) == pytest.approx(FIRST_DOWNBEAT + BAR_PERIOD)
    assert bar_beat_to_time(BARS + 1) == pytest.approx(END, abs=1e-9)


def test_phase1_eighth_note_offset_is_half_a_beat():
    assert bar_beat_to_time(3, 0.5) - bar_beat_to_time(3, 0.0) == pytest.approx(BEAT_PERIOD / 2)


@pytest.mark.parametrize("bar", [1, 10, 19, 45])
def test_phase1_time_to_bar_beat_round_trips(bar):
    b, beat = time_to_bar_beat(bar_beat_to_time(bar))
    assert b == bar
    assert beat == pytest.approx(0.0, abs=1e-9)


def test_phase1_snap_lands_on_a_grid_point():
    t = bar_beat_to_time(3, 0.3)
    assert snap_to_grid(t, 1) == pytest.approx(bar_beat_to_time(3, 0.0))
    assert snap_to_grid(t, 2) == pytest.approx(bar_beat_to_time(3, 0.5))


# ------------------------------------------------------------- 동작/보간
def test_phase2_choreo_returns_all_seven_joints():
    assert set(choreo(bar_beat_to_time(1)).keys()) == JOINTS


def test_phase2_normalised_value_converts_with_close_sign():
    # B는 오므림이 +, A는 -
    assert to_rad("B_j2", 0.5) == pytest.approx(CLOSE_SIGN["B"] * Q_CLOSE["j2"] * 0.5)
    assert to_rad("A_j2", 0.5) == pytest.approx(CLOSE_SIGN["A"] * Q_CLOSE["j2"] * 0.5)
    assert to_rad("A_j0", 0.5) == pytest.approx(0.5)   # 요는 이미 rad


def test_phase2_keyframe_values_are_hit_exactly_on_the_beat():
    # clasp(마디 11~14) beat 0 = 0.66, beat 1 = 0.44
    assert pose_norm(bar_beat_to_time(11, 0.0))["B_j2"] == pytest.approx(0.66, abs=1e-6)
    assert pose_norm(bar_beat_to_time(11, 1.0))["B_j2"] == pytest.approx(0.44, abs=1e-6)


def test_phase2_pose_is_continuous_across_a_section_boundary():
    """구간이 바뀌는 순간 자세가 튀지 않는다 (전역 타임라인으로 보간하므로)."""
    t = bar_beat_to_time(15, 0.0)          # clasp → pound 경계
    before, after = pose_norm(t - 1e-4), pose_norm(t + 1e-4)
    assert max(abs(before[j] - after[j]) for j in JOINTS) < 1e-3


def test_phase2_outside_the_timeline_the_pose_is_held():
    assert pose_norm(-5.0) == pose_norm(choreo_mod.START)
    assert pose_norm(choreo_mod.END + 5.0) == pose_norm(choreo_mod.END)
    # 끝나면 중립
    assert all(v == pytest.approx(0.0) for v in choreo(choreo_mod.END + 1.0).values())


@pytest.mark.parametrize("bar", range(1, 20))
def test_phase2_every_beat_stays_inside_the_safe_range(bar):
    for beat in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        for name, q in choreo(bar_beat_to_time(bar, beat)).items():
            lo, hi = safe_range(name)
            assert lo - 1e-9 <= q <= hi + 1e-9, f"마디 {bar}.{beat} {name}={q:+.3f}"


# --------------------------------------------------------------- 시간표
def test_phase3_schedule_covers_every_analysed_bar_exactly_once():
    rows = sched.build_schedule()
    assert [r["bar"] for r in rows] == list(range(sched.FIRST_BAR, sched.LAST_BAR + 1))


def test_phase3_sections_match_the_video_reading():
    assert sched.get_motion(1)[0] == "still"     # 영상 0.0~6.5s 바닥에 누움
    assert sched.get_motion(5)[0] == "veil"      # 영상 6.5~13.7s 얼굴 덮는 손
    assert sched.get_motion(9)[0] == "rise"      # 영상 13.7~17.2s 일어남
    assert sched.get_motion(14)[0] == "clasp"    # 영상 17.2~24.3s 맞잡은 손
    assert sched.get_motion(15)[0] == "pound"    # 영상 24.3~29.7s 빌드
    assert sched.get_motion(19)[0] == "claw"     # 영상 29.7~33.2s 가로 스윕


def test_phase3_two_bar_motions_restart_only_every_other_bar():
    """veil은 8박(2마디)짜리라 마디 5, 7에서만 새로 시작한다."""
    assert sched.get_motion(5) == ("veil", 5)
    assert sched.get_motion(6) == ("veil", 5)
    assert sched.get_motion(7) == ("veil", 7)
    assert sched.get_motion(8) == ("veil", 7)


def test_phase3_bar_outside_the_analysed_range_is_rejected():
    with pytest.raises(ValueError):
        sched.get_motion(sched.LAST_BAR + 1)


def test_phase3_timeline_is_strictly_increasing():
    times = [kf["t"] for kf in sched.build_timeline()]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_phase3_timeline_ends_neutral():
    assert all(v == pytest.approx(0.0) for v in sched.build_timeline()[-1]["q"].values())


# --------------------------------------------------------------- 검증기
def test_phase3_validate_all_passes():
    val.validate_all()


def test_phase3_validator_catches_a_too_fast_keyframe():
    """상한을 넘는 타임라인을 일부러 만들어 검증기가 잡는지 본다."""
    fast = [
        {"t": 0.0, "q": {j: 0.0 for j in sched.JOINTS}, "ease": "inout", "tag": "a"},
        {"t": 0.1, "q": {**{j: 0.0 for j in sched.JOINTS}, "B_j2": 1.0},
         "ease": "inout", "tag": "b"},            # 1.2 rad / 0.1 s = 12 rad/s
    ]
    assert val.check_speed_limit(fast)


def test_phase3_validator_accounts_for_the_ease_curve_peak():
    """평균은 상한 아래지만 ease='out'의 출발 기울기는 3배라 넘는 경우."""
    kfs = [
        {"t": 0.0, "q": {j: 0.0 for j in sched.JOINTS}, "ease": "out", "tag": "a"},
        {"t": 0.4, "q": {**{j: 0.0 for j in sched.JOINTS}, "B_j2": 0.5},
         "ease": "out", "tag": "b"},              # 평균 1.5 rad/s, 순간 4.5 rad/s
    ]
    assert val.peak_speed(kfs[0], kfs[1], "B_j2") == pytest.approx(4.5)
    assert val.check_speed_limit(kfs)
    kfs[1]["ease"] = "inout"                      # 같은 진폭이라도 smoothstep이면 통과
    assert not val.check_speed_limit(kfs)


def test_phase3_validator_catches_an_off_grid_keyframe(monkeypatch):
    monkeypatch.setitem(val.MOTIONS, "bogus",
                        {"beats": 4, "keyframes": [{"beat": 0.3, "q": {}}]})
    assert val.check_grid_alignment()


def test_phase3_validator_catches_an_out_of_range_pose():
    bad = [{"t": 0.0, "q": {**{j: 0.0 for j in sched.JOINTS}, "B_j2": 2.0},
            "ease": "inout", "tag": "x"}]
    assert val.check_safe_range(bad)


def test_phase3_timeline_fits_inside_the_audio():
    assert not val.check_duration(sched.build_timeline())
    assert sched.end_time() <= END
