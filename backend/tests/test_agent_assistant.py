import json


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


class FakeFirewallAdapter:
    def __init__(self, *args, **kwargs):
        self._brand = args[0] if args else ""

    def execute_commands(self, commands):
        return "\n".join([f"OK:{c}" for c in (commands or [])])


def _seed_devices(main_module):
    d0 = main_module.DeviceConfig(id="127.0.0.1:2000", brand="Huawei", host="127.0.0.1", port=2000, protocol="telnet", alias="R1")
    d1 = main_module.DeviceConfig(id="127.0.0.1:2001", brand="Huawei", host="127.0.0.1", port=2001, protocol="telnet", alias="SW1")
    main_module.db["devices"] = {d0.id: d0, d1.id: d1}
    main_module.db["ai"] = main_module.AIConfig(api_key="test", model="fake", base_url=None)


def test_agent_chat_auto_execute_false_returns_run_and_plan(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "检查 LLDP", "need_tools": True, "need_config": False, "plan": ["列出资产设备", "执行 display lldp neighbor brief"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "检查 LLDP"}], "allow_config": False, "device_ids": None, "session_id": None, "auto_execute": False})
    assert r.status_code == 200
    data = r.json()
    assert data.get("session_id")
    assert isinstance(data.get("plan"), dict)
    assert isinstance(data.get("run"), dict)
    assert data["run"]["status"] in ("planned", "running", "done", "failed")
    assert len(data["run"]["steps"]) == 2
    assert data["run"]["steps"][0]["status"] == "pending"


def test_agent_chat_need_config_blocks_when_allow_config_false(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "配置 IP", "need_tools": True, "need_config": True, "plan": ["进入接口视图", "配置 IP 地址"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "给设备配置IP"}], "allow_config": False, "device_ids": ["127.0.0.1:2000"], "session_id": None, "auto_execute": False})
    assert r.status_code == 200
    data = r.json()
    assert "涉及配置变更" in (data.get("message") or "")
    assert data.get("run", {}).get("status") == "planned"


def test_agent_chat_nonconverged_does_not_500(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "列设备并执行版本", "need_tools": True, "need_config": False, "plan": ["列出设备", "执行 display version"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
        {"tool_calls": [{"name": "list_devices", "arguments": {}}]},
        {"tool_calls": [{"name": "list_devices", "arguments": {}}]},
        {"tool_calls": [{"name": "list_devices", "arguments": {}}]},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "列出资产设备并执行 display version"}], "allow_config": False, "device_ids": None, "session_id": None, "auto_execute": True})
    assert r.status_code == 200
    data = r.json()
    assert "未能收敛" in (data.get("message") or "")
    assert data.get("run", {}).get("status") == "failed"


def test_agent_run_step_updates_step_status(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "检查版本", "need_tools": True, "need_config": False, "plan": ["在设备上执行 display version"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
    ]
    step_queue = [
        {"tool_calls": [{"name": "run_device_commands", "arguments": {"device_id": "127.0.0.1:2000", "commands": ["display version"]}}]},
        {"content": "已执行 display version，输出正常。建议继续下一步。"},
    ]
    combined = queue + step_queue
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(combined))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r0 = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "检查版本"}], "allow_config": False, "device_ids": ["127.0.0.1:2000"], "session_id": None, "auto_execute": False})
    assert r0.status_code == 200
    data0 = r0.json()
    sid = data0["session_id"]
    run_id = data0["run"]["id"]

    r1 = client.post("/agent/run/step", json={"session_id": sid, "run_id": run_id, "action": "next"})
    assert r1.status_code == 200
    data1 = r1.json()
    run = data1["run"]
    assert run["steps"][0]["status"] in ("done", "failed")
    assert run["steps"][0]["started_at"]


def test_agent_run_step_blocks_dangerous_commands(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "危险操作", "need_tools": True, "need_config": True, "plan": ["执行 reboot"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
    ]
    step_queue = [
        {"tool_calls": [{"name": "run_device_commands", "arguments": {"device_id": "127.0.0.1:2000", "commands": ["reboot"]}}]},
        {"content": "已拒绝执行高风险命令。"},
    ]
    combined = queue + step_queue
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(combined))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r0 = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "重启设备"}], "allow_config": True, "device_ids": ["127.0.0.1:2000"], "session_id": None, "auto_execute": False})
    assert r0.status_code == 200
    data0 = r0.json()
    sid = data0["session_id"]
    run_id = data0["run"]["id"]

    r1 = client.post("/agent/run/step", json={"session_id": sid, "run_id": run_id, "action": "next"})
    assert r1.status_code == 200
    data1 = r1.json()
    step = data1["run"]["steps"][0]
    assert step["status"] in ("done", "failed")
    if step.get("tool_log"):
        assert any((t.get("ok") is False and ("高风险" in (t.get("error") or ""))) for t in step["tool_log"])


def test_agent_chat_device_scope_rejects_other_device(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    queue = [
        {"content": json.dumps({"intent": "只允许一台", "need_tools": True, "need_config": False, "plan": ["执行 show"], "suggested_device_ids": ["127.0.0.1:2000"], "notes": []}, ensure_ascii=False)},
        {"tool_calls": [{"name": "run_device_commands", "arguments": {"device_id": "127.0.0.1:2001", "commands": ["display version"]}}]},
        {"content": "设备不在允许列表，已停止。"},
    ]
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(queue))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "只操作 2000 设备"}], "allow_config": False, "device_ids": ["127.0.0.1:2000"], "session_id": None, "auto_execute": True})
    assert r.status_code == 200
    data = r.json()
    assert any((x.get("tool") == "run_device_commands" and x.get("ok") is False) for x in (data.get("tool_log") or []))


def test_agent_run_step_rejects_mismatched_ip_in_commands(client, main_module, reset_db, monkeypatch):
    _seed_devices(main_module)
    plan_queue = [
        {"content": json.dumps({"intent": "配置 VLANIF IP", "need_tools": True, "need_config": True, "plan": ["在 VLANIF 10 配置 IP 地址 192.168.1.2/30"], "suggested_device_ids": ["127.0.0.1:2001"], "notes": []}, ensure_ascii=False)},
    ]
    step_queue = [
        {"tool_calls": [{"name": "run_device_commands", "arguments": {"device_id": "127.0.0.1:2001", "commands": ["system-view", "interface Vlanif 10", "ip address 10.0.10.2 255.255.255.252", "quit", "quit"]}}]},
        {"content": "完成。"},
    ]
    combined = plan_queue + step_queue
    monkeypatch.setattr(main_module, "AIAnalyzer", lambda *args, **kwargs: FakeAIAnalyzer(combined))
    monkeypatch.setattr(main_module, "FirewallAdapter", FakeFirewallAdapter)

    r0 = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "配置 VLANIF 10 IP 192.168.1.2/30"}], "allow_config": True, "device_ids": ["127.0.0.1:2001"], "session_id": None, "auto_execute": False})
    assert r0.status_code == 200
    data0 = r0.json()
    sid = data0["session_id"]
    run_id = data0["run"]["id"]

    r1 = client.post("/agent/run/step", json={"session_id": sid, "run_id": run_id, "action": "next"})
    assert r1.status_code == 200
    data1 = r1.json()
    step = data1["run"]["steps"][0]
    assert step["status"] == "failed"
    assert "未按期望下发" in (step.get("summary") or "") or "未出现在命令中" in (step.get("summary") or "")
