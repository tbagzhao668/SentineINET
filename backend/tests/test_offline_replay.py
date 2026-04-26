import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import (
    _backup_intent,
    _fallback_topology_from_payload,
    _looks_dangerous_command,
    _looks_readonly_command,
    _parse_huawei_lldp_neighbor_brief,
    _render_template,
)


def test_parse_huawei_lldp_neighbor_brief():
    out = "\n".join(
        [
            "<R1>",
            "display lldp neighbor brief",
            "Local Intf  Neighbor Dev  Port ID  Exp",
            "GE0/0/1     R2            GE0/0/2   120",
            "<R1>",
            "",
        ]
    )
    rows = _parse_huawei_lldp_neighbor_brief(out)
    assert len(rows) == 1
    assert rows[0]["local_port"] == "GE0/0/1"
    assert rows[0]["neighbor_dev"] == "R2"
    assert rows[0]["remote_port"] == "GE0/0/2"
    assert rows[0]["expires"] == "120"


def test_fallback_topology_links_and_expires():
    out_r1 = "\n".join(
        [
            "<R1>",
            "display lldp neighbor brief",
            "Local Intf  Neighbor Dev  Port ID  Exp",
            "GE0/0/1     R2            GE0/0/2   120",
            "<R1>",
            "",
        ]
    )
    out_r2 = "\n".join(
        [
            "<R2>",
            "display lldp neighbor brief",
            "Local Intf  Neighbor Dev  Port ID  Exp",
            "GE0/0/2     R1            GE0/0/1   120",
            "<R2>",
            "",
        ]
    )
    payload = [
        {"device_id": "dev1", "host": "10.0.0.1", "port": 22, "brand": "Huawei", "lldp_output": out_r1, "error": None, "collected_at": "2026-01-01T00:00:00"},
        {"device_id": "dev2", "host": "10.0.0.2", "port": 22, "brand": "Huawei", "lldp_output": out_r2, "error": None, "collected_at": "2026-01-01T00:00:01"},
    ]
    topo = _fallback_topology_from_payload(payload)
    node_ids = {n["id"] for n in topo["nodes"]}
    assert "dev1" in node_ids
    assert "dev2" in node_ids
    assert len(topo["links"]) >= 1
    l0 = topo["links"][0]
    assert l0.get("protocol") == "lldp"
    assert isinstance(l0.get("expires_s"), int) or (l0.get("expires_s") is None)


def test_agent_command_gates():
    assert _looks_readonly_command("display version") is True
    assert _looks_readonly_command("system-view") is False
    assert _looks_dangerous_command("reboot") is True
    assert _looks_dangerous_command("display lldp neighbor brief") is False


def test_backup_template_render():
    cmd = "tftp {server_ip} put vrpcfg.zip {remote_path}"
    rendered = _render_template(cmd, {"server_ip": "10.0.0.9", "remote_path": "/cfg/dev1.cfg"})
    assert rendered == "tftp 10.0.0.9 put vrpcfg.zip /cfg/dev1.cfg"
    assert _backup_intent("tftp").startswith("备份运行配置到")
