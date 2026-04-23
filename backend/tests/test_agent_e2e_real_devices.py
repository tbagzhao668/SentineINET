import json
import socket
import time
import re

import pytest


def _tcp_ok(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_s):
            return True
    except Exception:
        return False


def _run_cli(main_module, device_id: str, commands):
    dev = main_module.db["devices"][device_id]
    adapter = main_module.FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
    cmds = ["screen-length 0 temporary"] + [str(c) for c in (commands or []) if str(c).strip()]
    return adapter.execute_commands(cmds, is_config=False) or ""


def _pick_interface(output: str, prefer_index: int = 0) -> str:
    text = (output or "").replace("\r", "\n")
    cands = re.findall(r"(?i)\bGigabitEthernet\d+/\d+/\d+\b", text)
    if not cands:
        cands = re.findall(r"(?i)\bGE\d+/\d+/\d+\b", text)
    if not cands:
        return "GigabitEthernet0/0/0"
    uniq = []
    seen = set()
    for x in cands:
        k = x.strip()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(k)
    idx = max(0, min(prefer_index, len(uniq) - 1))
    return uniq[idx]


def _load_device_ids_from_persist(main_module):
    if not main_module.db.get("devices"):
        main_module._load_persisted_state()
    return list((main_module.db.get("devices") or {}).keys())


@pytest.mark.e2e
def test_devices_reachable_over_telnet(main_module):
    main_module._load_persisted_state()
    ids = _load_device_ids_from_persist(main_module)
    assert ids, "db.json 未加载到任何 devices"
    for device_id in ids:
        dev = main_module.db["devices"][device_id]
        assert _tcp_ok(dev.host, dev.port, 2.0), f"设备不可达：{device_id} ({dev.host}:{dev.port})"


@pytest.mark.e2e
def test_show_version_all_devices(main_module):
    main_module._load_persisted_state()
    ids = _load_device_ids_from_persist(main_module)
    for device_id in ids:
        out = _run_cli(main_module, device_id, ["display version"])
        assert out.strip(), f"{device_id} 未返回任何输出"


@pytest.mark.e2e
def test_configure_ip_on_one_device(main_module):
    main_module._load_persisted_state()
    ids = _load_device_ids_from_persist(main_module)
    device_id = "127.0.0.1:2000" if "127.0.0.1:2000" in ids else ids[0]

    brief = _run_cli(main_module, device_id, ["display ip interface brief"])
    iface = _pick_interface(brief, prefer_index=0)
    ip = "192.168.1.1"
    mask = "255.255.255.252"

    _run_cli(
        main_module,
        device_id,
        [
            "system-view",
            f"interface {iface}",
            "undo shutdown",
            f"ip address {ip} {mask}",
            "quit",
            "quit",
        ],
    )

    cfg = _run_cli(main_module, device_id, [f"display current-configuration interface {iface}"])
    assert ip in cfg and mask in cfg, f"{device_id} 接口 {iface} 未看到 IP 配置：{ip}/{mask}"


class _Msg:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(self, message):
        self.message = message


class _Resp:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _ToolCallFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.type = "function"
        self.function = _ToolCallFn(name, arguments)


class FakeCompletions:
    def __init__(self, queue):
        self._queue = queue
        self._call_id = 0

    def create(self, **kwargs):
        if not self._queue:
            return _Resp(_Msg(content=""))
        item = self._queue.pop(0)
        tool_calls = []
        for tc in item.get("tool_calls") or []:
            self._call_id += 1
            args = tc.get("arguments") or {}
            tool_calls.append(_ToolCall(f"call_{self._call_id}", tc["name"], json.dumps(args, ensure_ascii=False)))
        return _Resp(_Msg(content=item.get("content", ""), tool_calls=tool_calls))


class FakeChat:
    def __init__(self, queue):
        self.completions = FakeCompletions(queue)


class FakeClient:
    def __init__(self, queue):
        self.chat = FakeChat(queue)


class FakeAIAnalyzer:
    def __init__(self, queue):
        self.client = FakeClient(queue)


@pytest.mark.e2e
def test_agent_step_executor_can_configure_vlan_and_trunk(client_e2e, main_module, monkeypatch):
    main_module._load_persisted_state()
    ids = _load_device_ids_from_persist(main_module)
    assert ids, "db.json 未加载到任何 devices"

    device_id = "127.0.0.1:2001" if "127.0.0.1:2001" in ids else ids[0]
    dev = main_module.db["devices"][device_id]
    assert _tcp_ok(dev.host, dev.port, 2.0), f"设备不可达：{device_id} ({dev.host}:{dev.port})"

    iface_brief = _run_cli(main_module, device_id, ["display interface brief"])
    iface = _pick_interface(iface_brief, prefer_index=1)
    vlan_id = 123

    plan = {"intent": "配置 VLAN 与 trunk", "need_tools": True, "need_config": True, "plan": [f"创建 VLAN {vlan_id} 并在 {iface} 放行"], "suggested_device_ids": [device_id], "notes": []}
    queue = [
        {"content": json.dumps(plan, ensure_ascii=False)},
        {
            "tool_calls": [
                {
                    "name": "run_device_commands",
                    "arguments": {
                        "device_id": device_id,
                        "commands": [
                            "screen-length 0 temporary",
                            "system-view",
                            f"vlan {vlan_id}",
                            "quit",
                            f"interface {iface}",
                            "port link-type trunk",
                            f"port trunk allow-pass vlan {vlan_id}",
                            "quit",
                            "quit",
                            f"display vlan {vlan_id}",
                        ],
                    },
                }
            ]
        },
        {"content": "已完成 VLAN 与 trunk 配置，并验证 VLAN 显示正常。"},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))

    if not main_module.db.get("ai") or not getattr(main_module.db["ai"], "api_key", None):
        main_module.db["ai"] = main_module.AIConfig(api_key="test", model="fake", base_url=None)

    r0 = client_e2e.post(
        "/agent/chat",
        json={
            "messages": [{"role": "user", "content": f"在设备上配置 VLAN {vlan_id} 并设置 trunk"}],
            "allow_config": True,
            "device_ids": [device_id],
            "session_id": None,
            "auto_execute": False,
        },
    )
    assert r0.status_code == 200
    data0 = r0.json()
    sid = data0["session_id"]
    run_id = data0["run"]["id"]

    r1 = client_e2e.post("/agent/run/step", json={"session_id": sid, "run_id": run_id, "action": "next"})
    assert r1.status_code == 200
    data1 = r1.json()
    step = data1["run"]["steps"][0]
    assert step["status"] in ("done", "failed")

    verify = _run_cli(main_module, device_id, [f"display vlan {vlan_id}"])
    assert str(vlan_id) in verify, f"{device_id} 未看到 VLAN {vlan_id} 输出"


@pytest.mark.e2e
def test_agent_step_executor_can_configure_interface_ip(client_e2e, main_module, monkeypatch):
    main_module._load_persisted_state()
    ids = _load_device_ids_from_persist(main_module)
    assert ids, "db.json 未加载到任何 devices"

    device_id = "127.0.0.1:2000" if "127.0.0.1:2000" in ids else ids[0]
    dev = main_module.db["devices"][device_id]
    assert _tcp_ok(dev.host, dev.port, 2.0), f"设备不可达：{device_id} ({dev.host}:{dev.port})"

    brief = _run_cli(main_module, device_id, ["display ip interface brief"])
    iface = _pick_interface(brief, prefer_index=0)
    ip = "192.168.1.1"
    mask = "255.255.255.252"

    plan = {
        "intent": "配置接口IP地址",
        "need_tools": True,
        "need_config": True,
        "plan": [f"进入系统视图并在 {iface} 配置 IP 地址 {ip}/30"],
        "suggested_device_ids": [device_id],
        "notes": [],
    }
    queue = [
        {"content": json.dumps(plan, ensure_ascii=False)},
        {
            "tool_calls": [
                {
                    "name": "run_device_commands",
                    "arguments": {
                        "device_id": device_id,
                        "commands": [
                            "screen-length 0 temporary",
                            "system-view",
                            f"interface {iface}",
                            "undo shutdown",
                            f"ip address {ip} {mask}",
                            "quit",
                            "quit",
                            f"display current-configuration interface {iface}",
                        ],
                    },
                }
            ]
        },
        {"content": "已配置接口 IP，并验证当前接口配置包含目标地址。"},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))

    if not main_module.db.get("ai") or not getattr(main_module.db["ai"], "api_key", None):
        main_module.db["ai"] = main_module.AIConfig(api_key="test", model="fake", base_url=None)

    r0 = client_e2e.post(
        "/agent/chat",
        json={
            "messages": [{"role": "user", "content": f"在接口 {iface} 配置 IP 地址 {ip}/30"}],
            "allow_config": True,
            "device_ids": [device_id],
            "session_id": None,
            "auto_execute": False,
        },
    )
    assert r0.status_code == 200
    data0 = r0.json()
    sid = data0["session_id"]
    run_id = data0["run"]["id"]

    r1 = client_e2e.post("/agent/run/step", json={"session_id": sid, "run_id": run_id, "action": "next"})
    assert r1.status_code == 200
    data1 = r1.json()
    step = data1["run"]["steps"][0]
    assert step["status"] in ("done", "failed")

    cfg = _run_cli(main_module, device_id, [f"display current-configuration interface {iface}"])
    assert ip in cfg and mask in cfg, f"{device_id} 接口 {iface} 未看到 IP 配置：{ip}/{mask}"
