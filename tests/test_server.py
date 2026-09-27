"""server.py 프리셋/대시보드 API 테스트.

  .venv/bin/python -m pytest tests
"""
import copy
import json
import math
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import mujoco
import pytest
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import server  # noqa: E402

JOINTS = ["A_j0", "A_j1", "A_j2", "B_j1", "B_j2", "C_j1", "C_j2"]


def make_preset(**overrides):
    """관절마다 다른 값을 넣어 관절이 섞여 적용되면 드러나게 함."""
    p = {n: {"target": 0.1 * (i + 1) * (-1) ** i, "kp": 5.0 + i, "kv": 0.1 * (i + 1), "torque_limit": 0.5 + 0.1 * i}
         for i, n in enumerate(JOINTS)}
    for n, fields in overrides.items():
        p[n] = {**p[n], **fields}
    return p


def sim_values():
    s = server._state()
    return {k: s[k] for k in ("targets", "gains", "modes", "torque")}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PRESETS_PATH", tmp_path / "presets.json")
    arrays = (server.model.actuator_gainprm, server.model.actuator_biasprm, server.model.actuator_forcerange,
              server.model.actuator_ctrlrange)
    saved, servos = [a.copy() for a in arrays], copy.deepcopy(server.SERVOS)
    mujoco.mj_resetData(server.model, server.data)
    yield TestClient(server.app)
    for a, v in zip(arrays, saved):
        a[:] = v
    server.SERVOS.clear()
    server.SERVOS.update(servos)
    mujoco.mj_resetData(server.model, server.data)


def test_state_reports_xml_defaults(client):
    s = client.get("/state").json()
    assert set(s["gains"]) == set(JOINTS)
    for g in s["gains"].values():
        assert g == {"kp": 12.0, "kv": 0.5, "torque_limit": 1.4}


def test_save_and_list_do_not_change_simulation(client):
    before = sim_values()
    r = client.put("/presets/grip", json=make_preset())
    assert r.status_code == 200 and r.json() == {"name": "grip", "created": True}
    # 대시보드의 드롭다운 선택은 GET /presets 만 사용
    assert client.get("/presets").json()["grip"] == make_preset()
    assert sim_values() == before


def test_apply_sets_all_motor_parameters(client):
    preset = make_preset()
    client.put("/presets/grip", json=preset)
    s = client.post("/presets/grip/apply").json()
    for n, m in preset.items():
        assert s["targets"][n] == pytest.approx(m["target"])
        assert s["gains"][n] == pytest.approx({k: m[k] for k in ("kp", "kv", "torque_limit")})
        assert server.model.actuator_forcerange[server.JOINTS[n].act].tolist() == pytest.approx(
            [-m["torque_limit"], m["torque_limit"]])


def test_applied_torque_limit_caps_actuator_force(client):
    client.put("/presets/weak", json={n: {"target": 1.0 if n == "A_j0" else 1.5, "kp": 100, "kv": 0,
                                          "torque_limit": 0.2} for n in JOINTS})
    client.post("/presets/weak/apply")
    peak = 0.0
    for _ in range(500):
        mujoco.mj_step(server.model, server.data)
        peak = max(peak, abs(server.data.actuator_force).max())
    assert peak == pytest.approx(0.2)
    assert all(math.isfinite(q) for q in server.data.qpos)


def test_update_existing_preset(client):
    client.put("/presets/grip", json=make_preset())
    r = client.put("/presets/grip", json=make_preset(A_j1={"kp": 42.0}))
    assert r.json() == {"name": "grip", "created": False}
    assert client.get("/presets").json()["grip"]["A_j1"]["kp"] == 42.0


@pytest.mark.parametrize("bad", [
    make_preset(A_j0={"target": 1.1}),            # A_j0 범위는 ±1.0472
    make_preset(B_j2={"target": -1.6}),           # 나머지 ±1.5708
    make_preset(A_j1={"kp": 0}),
    make_preset(A_j1={"kp": 100.1}),
    make_preset(C_j1={"kv": -0.1}),
    make_preset(C_j1={"kv": 5.1}),
    make_preset(C_j2={"torque_limit": 0}),
    make_preset(C_j2={"torque_limit": 1.41}),     # XL430 정격 1.4 N·m 초과
    make_preset(C_j2={"torque_limit": "abc"}),
    make_preset(A_j2={"extra": 1}),
    {n: v for n, v in make_preset().items() if n != "C_j2"},   # 관절 누락
    {**make_preset(), "D_j1": make_preset()["A_j1"]},          # 알 수 없는 관절
])
def test_invalid_preset_rejected(client, bad):
    r = client.put("/presets/bad", json=bad)
    assert r.status_code == 422
    assert "bad" not in client.get("/presets").json()


def test_non_finite_rejected(client):
    body = json.dumps(make_preset()).replace('"kp": 5.0', '"kp": NaN', 1)
    r = client.put("/presets/nan", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize("name", [" lead", "a/b", "x" * 41, "a  b"])
def test_invalid_name_rejected(client, name):
    r = client.put(f"/presets/{name}", json=make_preset())
    assert r.status_code in (404, 422)
    assert client.get("/presets").json() == {}


def test_apply_unknown_preset_404_and_no_change(client):
    before = sim_values()
    assert client.post("/presets/nope/apply").status_code == 404
    assert sim_values() == before


@pytest.mark.parametrize("content", [
    "{not json",                                        # 문법이 깨진 JSON
    json.dumps({"grip": {"A_j0": {"target": 0.0}}}),    # JSON은 맞지만 프리셋 형식이 아님
])
def test_corrupt_presets_file_gives_controlled_error(client, content):
    server.PRESETS_PATH.write_text(content, encoding="utf-8")
    before = sim_values()
    assert client.get("/state").status_code == 200   # 텔레메트리는 계속 동작
    for method, path, body in [("GET", "/presets", None), ("PUT", "/presets/grip", make_preset()),
                               ("POST", "/presets/grip/apply", None)]:
        r = client.request(method, path, json=body)
        assert r.status_code == 500
        assert "presets.json" in r.json()["detail"]
    assert server.PRESETS_PATH.read_text(encoding="utf-8") == content   # 덮어쓰지 않음
    assert sim_values() == before


@pytest.mark.parametrize("case", ["invalid_utf8", "permission_denied"])
def test_unreadable_presets_file_gives_controlled_error(client, monkeypatch, case):
    content = b'{"grip": \xff\xfe}' if case == "invalid_utf8" else json.dumps({}).encode()
    server.PRESETS_PATH.write_bytes(content)
    if case == "permission_denied":
        real_read_text = Path.read_text

        def deny(self, *a, **kw):
            if self == server.PRESETS_PATH:
                raise PermissionError(13, "Permission denied", str(self))
            return real_read_text(self, *a, **kw)
        monkeypatch.setattr(Path, "read_text", deny)
    before = sim_values()
    assert client.get("/state").status_code == 200
    for method, path, body in [("GET", "/presets", None), ("PUT", "/presets/grip", make_preset()),
                               ("POST", "/presets/grip/apply", None)]:
        r = client.request(method, path, json=body)
        assert r.status_code == 500
        assert "presets.json" in r.json()["detail"]
    assert server.PRESETS_PATH.read_bytes() == content   # 덮어쓰지 않음
    assert sim_values() == before


def test_inaccessible_parent_dir_is_not_treated_as_empty(client, monkeypatch):
    # Python 3.14의 Path.exists는 상위 폴더 접근 거부(OSError)를 삼키고 False를 돌려줌
    content = json.dumps({"grip": make_preset()}).encode()
    server.PRESETS_PATH.write_bytes(content)
    real_exists, real_read_text = Path.exists, Path.read_text

    def fake_exists(self, *a, **kw):
        return False if self == server.PRESETS_PATH else real_exists(self, *a, **kw)

    def deny(self, *a, **kw):
        if self == server.PRESETS_PATH:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *a, **kw)
    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_text", deny)
    assert client.get("/state").status_code == 200
    r = client.get("/presets")
    assert r.status_code == 500
    assert "presets.json" in r.json()["detail"] and "PermissionError" in r.json()["detail"]
    assert server.PRESETS_PATH.read_bytes() == content   # 덮어쓰지 않음


def test_limits_lower_bounds_match_server_validation(client):
    """대시보드는 /limits 로 입력을 검사하므로, 하한 포함/제외가 서버 검증과 같아야 함."""
    lim = client.get("/limits").json()
    for f in ("kp", "kv", "torque_limit"):
        r = client.put("/presets/edge", json=make_preset(A_j1={f: lim[f][0]}))
        assert r.status_code == (422 if f in lim["exclusive_min"] else 200), f


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "tri_hand" in r.text


def step(seconds):
    for _ in range(round(seconds / server.model.opt.timestep)):
        mujoco.mj_step(server.model, server.data)


def to_velocity(client, name):
    client.post(f"/joints/{name}/torque", json={"enabled": False})
    client.post(f"/joints/{name}/mode", json={"mode": "velocity"})
    return client.post(f"/joints/{name}/torque", json={"enabled": True})


def test_state_reports_modes_and_torque(client):
    s = client.get("/state").json()
    assert s["modes"] == {n: "position" for n in JOINTS}
    assert s["torque"] == {n: True for n in JOINTS}
    j = client.get("/joints").json()
    assert all(j[n]["velocity_range"] == [-server.VEL_LIMIT, server.VEL_LIMIT] for n in JOINTS)


def test_mode_change_rejected_while_torque_on(client):
    r = client.post("/joints/A_j2/mode", json={"mode": "velocity"})
    assert r.status_code == 409
    assert client.get("/state").json()["modes"]["A_j2"] == "position"


def test_unknown_joint_or_mode_rejected(client):
    assert client.post("/joints/D_j1/torque", json={"enabled": False}).status_code == 404
    assert client.post("/joints/D_j1/mode", json={"mode": "velocity"}).status_code == 404
    client.post("/joints/A_j2/torque", json={"enabled": False})
    assert client.post("/joints/A_j2/mode", json={"mode": "current"}).status_code == 422


def test_torque_off_gives_zero_actuator_force(client):
    client.post("/joints", json={"A_j1": -1.0})
    step(0.1)
    assert abs(server.data.actuator_force[server.JOINTS["A_j1"].act]) > 0.1
    s = client.post("/joints/A_j1/torque", json={"enabled": False}).json()
    assert s["torque"]["A_j1"] is False
    for _ in range(200):
        mujoco.mj_step(server.model, server.data)
        assert server.data.actuator_force[server.JOINTS["A_j1"].act] == 0.0
    # 설정은 토크를 꺼도 남아 있어야 다시 켰을 때 같은 게인으로 돌아옴
    assert s["gains"]["A_j1"] == {"kp": 12.0, "kv": 0.5, "torque_limit": 1.4}


def test_velocity_mode_reaches_target_velocity(client):
    s = to_velocity(client, "A_j2").json()
    assert s["modes"]["A_j2"] == "velocity" and s["torque"]["A_j2"] is True
    r = client.post("/velocities", json={"A_j2": 0.5})
    assert r.json() == {"applied": {"A_j2": 0.5}, "clipped": []}
    step(0.5)
    v = []
    for _ in range(250):
        mujoco.mj_step(server.model, server.data)
        v.append(server.data.qvel[server.JOINTS["A_j2"].dof])
    assert min(v) == pytest.approx(0.5, abs=0.025) and max(v) == pytest.approx(0.5, abs=0.025)
    assert client.get("/state").json()["targets"]["A_j2"] == 0.5


def test_velocity_above_angle_range_is_not_capped(client):
    # 속도 모드 목표가 위치 모드 ctrlrange(±1.5708)로 잘리면 3 rad/s에 못 미침
    to_velocity(client, "A_j2")
    client.post("/velocities", json={"A_j2": 3.0})
    step(0.2)
    assert server.data.qvel[server.JOINTS["A_j2"].dof] > 2.5


def test_velocities_validated_and_clipped(client):
    to_velocity(client, "A_j2")
    assert client.post("/velocities", json={"D_j1": 0.1}).status_code == 400
    r = client.post("/velocities", content='{"A_j2": NaN}', headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    r = client.post("/velocities", json={"A_j2": 10.0})
    assert r.json() == {"applied": {"A_j2": server.VEL_LIMIT}, "clipped": ["A_j2"]}


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/joints", {"A_j1": 0.3, "A_j2": 0.3}),
    ("POST", "/grasp", {"amount": 0.5}),
    ("POST", "/presets/grip/apply", None),
])
def test_angle_request_to_velocity_joint_rejected_without_change(client, method, path, body):
    client.put("/presets/grip", json=make_preset())
    to_velocity(client, "A_j2")
    before = sim_values()
    r = client.request(method, path, json=body)
    assert r.status_code == 409 and "A_j2" in r.json()["detail"]
    assert sim_values() == before


def test_velocity_request_to_position_joint_rejected_without_change(client):
    before = sim_values()
    r = client.post("/velocities", json={"A_j1": 0.5})
    assert r.status_code == 409 and "A_j1" in r.json()["detail"]
    assert sim_values() == before


def test_angle_request_to_torque_off_joint_rejected(client):
    client.post("/joints/B_j1/torque", json={"enabled": False})
    before = sim_values()
    r = client.post("/joints", json={"B_j1": 0.3})
    assert r.status_code == 409 and "B_j1" in r.json()["detail"]
    assert sim_values() == before


def test_torque_on_holds_current_state(client):
    client.post("/joints", json={"A_j1": -0.8})
    step(0.5)
    client.post("/joints/A_j1/torque", json={"enabled": False})
    step(0.3)   # 토크 없이 중력으로 움직임
    q = float(server.data.qpos[server.JOINTS["A_j1"].qpos])
    s = client.post("/joints/A_j1/torque", json={"enabled": True}).json()
    assert s["targets"]["A_j1"] == pytest.approx(q) and q != pytest.approx(-0.8, abs=1e-3)

    client.post("/joints", json={"A_j2": 0.8})
    step(0.2)
    s = to_velocity(client, "A_j2").json()
    assert s["targets"]["A_j2"] == 0.0


def test_reset_keeps_mode_and_torque(client):
    to_velocity(client, "A_j2")
    client.post("/joints/B_j1/torque", json={"enabled": False})
    s = client.post("/reset").json()
    assert s["modes"]["A_j2"] == "velocity" and s["torque"]["A_j2"] is True
    assert s["torque"]["B_j1"] is False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(port, presets):
    proc = subprocess.Popen([sys.executable, "server.py", "--headless", "--port", str(port), "--presets", str(presets)],
                            cwd=SRC, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            _get(port, "/state")
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("서버가 시작되지 않음")


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
        return json.loads(r.read())


def _send(port, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


def test_presets_survive_restart_and_headless_sim_runs(tmp_path):
    port, presets = _free_port(), tmp_path / "presets.json"
    proc = _start(port, presets)
    try:
        _send(port, "PUT", "/presets/grip", make_preset())
    finally:
        proc.terminate()
        proc.wait(5)

    proc = _start(port, presets)
    try:
        assert _get(port, "/presets") == {"grip": make_preset()}
        assert _get(port, "/state")["gains"]["A_j1"]["kp"] == 12.0   # 재시작 시 자동 적용 안 됨
        _send(port, "POST", "/presets/grip/apply")
        t0 = _get(port, "/state")["time"]
        time.sleep(1.0)
        s = _get(port, "/state")
        assert s["time"] > t0 + 0.5   # 헤드리스 시뮬레이션 루프가 실시간으로 진행
        assert all(math.isfinite(q) for q in s["joints"].values())
        for n, m in make_preset().items():
            assert s["joints"][n] == pytest.approx(m["target"], abs=0.05)
    finally:
        proc.terminate()
        proc.wait(5)
