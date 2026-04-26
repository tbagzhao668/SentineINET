from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import asyncio
import datetime
import json
import hashlib
import logging
import re
import secrets
import socket
import time
import uuid
from threading import Lock
from pathlib import Path
from urllib.parse import urlparse
from app.core.firewall_adapter import FirewallAdapter
from app.core.ai_analyzer import AIAnalyzer

app = FastAPI(title="SentinelAI API")

topology_logger = logging.getLogger("uvicorn.error")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "name": "SentinelAI API",
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

# --- 数据模型 ---

class AIConfig(BaseModel):
    api_key: str
    model: str = "gpt-4-turbo"
    base_url: Optional[str] = None

class BackupServer(BaseModel):
    id: str
    server_ip: str
    protocol: str = "tftp" # "tftp", "ftp", "sftp"
    username: Optional[str] = None
    password: Optional[str] = None
    path: str = "/"

class DeviceConfig(BaseModel):
    id: Optional[str] = None
    brand: str
    host: str
    port: int = 22
    protocol: str = "ssh" # "ssh" 或 "telnet"
    alias: Optional[str] = None
    username: Optional[str] = ""
    password: Optional[str] = ""
    secret: Optional[str] = None
    os_version: Optional[str] = None
    inspection_interval: int = 10 # 每个设备独立的巡检间隔（分钟）
    backup_server_id: Optional[str] = None # 关联的备份服务器 ID
    backup_enabled: bool = False
    backup_interval: int = 1440
    backup_filename_prefix: Optional[str] = None

class SkillEntry(BaseModel):
    id: str
    brand: str
    device_version: Optional[str] = None
    intent: str
    commands: List[str]
    description: Optional[str] = None
    source: str = "ai" # "ai" 或 "user"
    tags: Optional[List[str]] = None
    prerequisites: Optional[str] = None
    validation: Optional[str] = None
    sample_output: Optional[str] = None
    verified: bool = False
    last_verified_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    updated_at: Optional[datetime.datetime] = None

class InspectionSettings(BaseModel):
    auto_inspect: bool
    enabled_devices: List[str]

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    username: str
    force_change: bool = False

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class DeployRequest(BaseModel):
    ips: List[str]

class AgentChatMessage(BaseModel):
    role: str
    content: str

class AgentChatRequest(BaseModel):
    messages: List[AgentChatMessage]
    allow_config: bool = False
    device_ids: Optional[List[str]] = None
    session_id: Optional[str] = None
    auto_execute: bool = True

class AgentRunStepRequest(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    action: str = "next"  # next | retry
    step_index: Optional[int] = None

# --- 内存存储 ---
db = {
    "devices": {}, 
    "ai": None,
    "skills": [],      # 存储 Skill 库
    "inspections": {}, # 存储各设备的巡检结果
    "health_data": {}, # 存储各设备的硬件健康指标: {host: {cpu, mem, temp}}
    "last_run": {},    # 记录每个设备上次巡检的时间点
    "pending_actions": [],
    "policy_history": {}, # 存储已下发的策略历史: {host: [policy1, policy2, ...]}
    "backup_servers": {}, # 存储备份服务器: {id: BackupServer}
    "backup_history": {}, # {device_id: [history_entry, ...]}
    "last_backup": {},    # {device_id: datetime}
    "auth": {"users": {}},
    "auth_sessions": {},
    "agent_sessions": {},
    "settings": {
        "auto_inspect": False,
        "enabled_devices": []
    }
}

_PERSIST_PATH = Path(__file__).resolve().parent / "db.json"
_PERSIST_LOCK = Lock()
_BACKUP_RUNNING = set()
_BACKUP_RUNNING_LOCK = Lock()

def _to_jsonable(obj):
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj

def _serialize_persisted_state():
    devices = {}
    for device_id, dev in db.get("devices", {}).items():
        if hasattr(dev, "dict"):
            devices[device_id] = dev.dict()
        else:
            devices[device_id] = dev

    ai = db.get("ai")
    if hasattr(ai, "dict"):
        ai = ai.dict()

    state = {
        "devices": devices,
        "ai": ai,
        "skills": _to_jsonable(db.get("skills", [])),
        "backup_servers": _to_jsonable(db.get("backup_servers", {})),
        "backup_history": _to_jsonable(db.get("backup_history", {})),
        "last_backup": _to_jsonable(db.get("last_backup", {})),
        "auth": _to_jsonable(db.get("auth", {"users": {}})),
        "agent_sessions": _to_jsonable(db.get("agent_sessions", {})),
        "settings": _to_jsonable(db.get("settings", {"auto_inspect": False, "enabled_devices": []})),
    }
    return state

def _save_persisted_state():
    with _PERSIST_LOCK:
        state = _serialize_persisted_state()
        tmp_path = _PERSIST_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(_PERSIST_PATH)

def _load_persisted_state():
    if not _PERSIST_PATH.exists():
        return
    with _PERSIST_LOCK:
        raw = json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))

    devices_raw = raw.get("devices", {}) or {}
    loaded_devices = {}
    for device_id, dev_data in devices_raw.items():
        try:
            loaded_devices[device_id] = DeviceConfig(**dev_data)
        except Exception:
            continue
    if loaded_devices:
        db["devices"] = loaded_devices

    ai_raw = raw.get("ai", None)
    if isinstance(ai_raw, dict):
        try:
            db["ai"] = AIConfig(**ai_raw)
        except Exception:
            db["ai"] = None

    skills_raw = raw.get("skills", []) or []
    if isinstance(skills_raw, list):
        db["skills"] = skills_raw

    backup_raw = raw.get("backup_servers", {}) or {}
    if isinstance(backup_raw, dict):
        db["backup_servers"] = backup_raw

    backup_history_raw = raw.get("backup_history", {}) or {}
    if isinstance(backup_history_raw, dict):
        db["backup_history"] = backup_history_raw

    last_backup_raw = raw.get("last_backup", {}) or {}
    if isinstance(last_backup_raw, dict):
        parsed = {}
        for device_id, ts in last_backup_raw.items():
            if isinstance(ts, datetime.datetime):
                parsed[str(device_id)] = ts
                continue
            if isinstance(ts, str) and ts.strip():
                try:
                    parsed[str(device_id)] = datetime.datetime.fromisoformat(ts.strip())
                except Exception:
                    continue
        db["last_backup"] = parsed

    settings_raw = raw.get("settings", {}) or {}
    if isinstance(settings_raw, dict):
        db["settings"]["auto_inspect"] = bool(settings_raw.get("auto_inspect", False))
        enabled = settings_raw.get("enabled_devices", []) or []
        db["settings"]["enabled_devices"] = [str(x) for x in enabled if str(x).strip()]

    sessions_raw = raw.get("agent_sessions", {}) or {}
    if isinstance(sessions_raw, dict):
        db["agent_sessions"] = sessions_raw

    auth_raw = raw.get("auth", {}) or {}
    if isinstance(auth_raw, dict):
        users_raw = auth_raw.get("users", {}) or {}
        if isinstance(users_raw, dict):
            db["auth"] = {"users": users_raw}

# --- 认证（登录/改密）---

def _pbkdf2_hash_password(password: str, salt_hex: Optional[str] = None, iterations: int = 150_000):
    salt = bytes.fromhex(salt_hex) if (salt_hex or "").strip() else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return {"salt": salt.hex(), "hash": dk.hex(), "iterations": int(iterations)}

def _verify_password(password: str, user: Dict[str, Any]) -> bool:
    try:
        salt = str(user.get("salt") or "").strip()
        stored = str(user.get("password_hash") or "").strip()
        it = int(user.get("iterations") or 0)
        if not salt or not stored or it <= 0:
            return False
        computed = _pbkdf2_hash_password(password, salt_hex=salt, iterations=it)
        return secrets.compare_digest(computed["hash"], stored)
    except Exception:
        return False

def _ensure_auth_bootstrap():
    auth = db.get("auth")
    if not isinstance(auth, dict):
        db["auth"] = {"users": {}}
        auth = db["auth"]
    users = auth.get("users")
    if not isinstance(users, dict):
        auth["users"] = {}
        users = auth["users"]

    if users:
        return

    record = _pbkdf2_hash_password("admin")
    users["admin"] = {
        "username": "admin",
        "password_hash": record["hash"],
        "salt": record["salt"],
        "iterations": record["iterations"],
        "force_change": True,
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": None,
    }
    _save_persisted_state()

def _issue_token(username: str, ttl_hours: int = 24 * 7) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now() + datetime.timedelta(hours=int(ttl_hours))
    sessions = db.get("auth_sessions")
    if not isinstance(sessions, dict):
        db["auth_sessions"] = {}
        sessions = db["auth_sessions"]
    sessions[token] = {"username": username, "expires_at": expires_at}
    return token

def _get_current_user_from_request(request: Request) -> Dict[str, Any]:
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header.split(" ", 1)[1].strip()
    sessions = db.get("auth_sessions")
    if not isinstance(sessions, dict):
        raise HTTPException(status_code=401, detail="未登录")
    sess = sessions.get(token)
    if not isinstance(sess, dict):
        raise HTTPException(status_code=401, detail="未登录")

    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.datetime.fromisoformat(expires_at)
        except Exception:
            expires_at = None
    if isinstance(expires_at, datetime.datetime) and expires_at < datetime.datetime.now():
        sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="登录已过期")

    username = str(sess.get("username") or "").strip()
    user = (db.get("auth") or {}).get("users", {}).get(username)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="用户不存在")
    return user

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    public_paths = {
        "/",
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/login",
    }
    if request.url.path in public_paths or request.url.path.startswith("/docs"):
        return await call_next(request)
    _get_current_user_from_request(request)
    return await call_next(request)

@app.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    _ensure_auth_bootstrap()
    username = (req.username or "").strip()
    password = req.password or ""
    user = (db.get("auth") or {}).get("users", {}).get(username)
    if not isinstance(user, dict) or (not _verify_password(password, user)):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = _issue_token(username)
    return {
        "token": token,
        "username": username,
        "force_change": bool(user.get("force_change", False)),
    }

@app.get("/auth/me")
async def me(request: Request):
    user = _get_current_user_from_request(request)
    return {"username": user.get("username"), "force_change": bool(user.get("force_change", False))}

@app.post("/auth/change_password")
async def change_password(request: Request, body: ChangePasswordRequest):
    user = _get_current_user_from_request(request)
    username = str(user.get("username") or "").strip()

    if not _verify_password(body.old_password or "", user):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    new_password = (body.new_password or "").strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度至少 6 位")

    record = _pbkdf2_hash_password(new_password)
    users = (db.get("auth") or {}).get("users", {})
    if not isinstance(users, dict) or username not in users:
        raise HTTPException(status_code=400, detail="用户不存在")
    users[username] = {
        **users[username],
        "password_hash": record["hash"],
        "salt": record["salt"],
        "iterations": record["iterations"],
        "force_change": False,
        "updated_at": datetime.datetime.now().isoformat(),
    }
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "密码已更新"}

# --- 辅助函数：Skill 智能缓存逻辑 ---

def _norm_text(value: Optional[str]) -> str:
    return (value or "").strip()

def _find_skill(intent: str, brand: str, device_version: Optional[str] = None):
    target_version = _norm_text(device_version)
    for s in db.get("skills", []):
        if s.get("brand") == brand and s.get("intent") == intent and _norm_text(s.get("device_version")) == target_version:
            return s
    if target_version:
        for s in db.get("skills", []):
            if s.get("brand") == brand and s.get("intent") == intent and not _norm_text(s.get("device_version")):
                return s
    return None

def _upsert_skill(
    intent: str,
    brand: str,
    device_version: Optional[str],
    commands: List[str],
    description: str,
    source: str = "ai",
    tags: Optional[List[str]] = None,
    prerequisites: Optional[str] = None,
    validation: Optional[str] = None,
    sample_output: Optional[str] = None,
    verified: bool = False,
):
    now = datetime.datetime.now()
    existing = _find_skill(intent=intent, brand=brand, device_version=device_version)
    if existing is not None:
        skill_id = existing.get("id") or f"skill_{uuid.uuid4().hex[:10]}_{brand.lower()}"
        created_at = existing.get("created_at") or now
    else:
        skill_id = f"skill_{uuid.uuid4().hex[:10]}_{brand.lower()}"
        created_at = now

    payload = {
        "id": skill_id,
        "brand": brand,
        "device_version": _norm_text(device_version) or None,
        "intent": intent,
        "commands": commands,
        "description": description,
        "source": source,
        "tags": tags,
        "prerequisites": prerequisites,
        "validation": validation,
        "sample_output": sample_output,
        "verified": bool(verified),
        "last_verified_at": (now if verified else existing.get("last_verified_at") if isinstance(existing, dict) else None),
        "created_at": created_at,
        "updated_at": now,
    }
    if existing is not None:
        existing.update(payload)
    else:
        db["skills"].append(payload)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(_save_persisted_state))
    except RuntimeError:
        _save_persisted_state()

def _extract_version_tag(brand: str, output: str) -> Optional[str]:
    import re
    text = (output or "").replace("\r", "\n")
    compact = " ".join([x.strip() for x in text.splitlines() if x.strip()])[:600]
    b = (brand or "").strip().lower()

    patterns = []
    if b in ("huawei", "h3c"):
        patterns = [
            r"(?i)\b(v\d{1,4}r\d{1,4}[a-z0-9]*)\b",
            r"(?i)\b(?:v|version)\s*[:：]?\s*([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
            r"(?i)\bvrp\s*\(r\)\s*software\s*,?\s*version\s*([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
            r"(?i)\bcomware\s*software\s*,?\s*version\s*([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
        ]
    elif b == "cisco":
        patterns = [
            r"(?i)\bversion\s+([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\(\)\-]*)",
        ]
    elif b == "fortinet":
        patterns = [
            r"(?i)\bversion\s*:\s*v?([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
            r"(?i)\bfortios\s+v?([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
        ]
    else:
        patterns = [
            r"(?i)\bversion\s*[:：]?\s*v?([0-9]+(?:\.[0-9]+){1,3}[a-z0-9\-]*)",
        ]

    for p in patterns:
        m = re.search(p, compact)
        if m:
            v = m.group(1).strip()
            return v[:64]

    return compact[:80] if compact else None

def _detect_device_version(adapter: FirewallAdapter, brand: str) -> Optional[str]:
    candidates_map = {
        "Huawei": ["display version"],
        "H3C": ["display version"],
        "Cisco": ["show version"],
        "Juniper": ["show version"],
        "Arista": ["show version"],
        "Extreme": ["show version"],
        "Dell": ["show version"],
        "HP": ["show version"],
        "Aruba": ["show version"],
        "Brocade": ["show version"],
        "Ruckus": ["show version"],
        "MikroTik": ["/system resource print"],
        "Ubiquiti": ["show version"],
        "PaloAlto": ["show system info"],
        "CheckPoint": ["show version"],
        "Sophos": ["show version"],
        "SonicWall": ["show version"],
        "WatchGuard": ["show version"],
        "Zyxel": ["show version"],
        "Fortinet": ["get system status", "get system performance status"],
        "Ruijie": ["show version", "display version"],
        "Sangfor": ["show version", "display version"],
        "F5": ["show sys version"],
        "A10": ["show version"],
    }
    candidates = candidates_map.get(brand, []) + ["show version", "display version", "get system status"]
    seen = set()
    for cmd in candidates:
        if cmd in seen:
            continue
        seen.add(cmd)
        try:
            out = adapter.execute_commands([cmd])
            tag = _extract_version_tag(brand, out)
            if tag:
                return tag
        except Exception:
            continue
    return None

def _detect_device_version_with_ai(adapter: FirewallAdapter, analyzer: AIAnalyzer, brand: str) -> Optional[str]:
    try:
        commands = analyzer.generate_commands_by_intent("获取设备系统版本信息（只读）", brand, device_version=None)
        output = adapter.execute_commands(commands)
        if _output_indicates_command_error(output):
            feedback = (output or "").strip().replace("\r", "")[:200]
            retry_intent = f"获取设备系统版本信息（只读）\n上一次执行输出提示：{feedback}\n请给可用的替代只读命令。"
            commands = analyzer.generate_commands_by_intent(retry_intent, brand, device_version=None)
            output = adapter.execute_commands(commands)
        if _output_indicates_command_error(output):
            return None
        return _extract_version_tag(brand, output)
    except Exception:
        return None

def _output_indicates_command_error(output: str) -> bool:
    raw = output or ""
    text = raw.lower()
    markers_lower = (
        "% invalid",
        "invalid input",
        "unrecognized command",
        "unknown command",
        "incomplete command",
        "ambiguous command",
        "command not found",
        "bad command",
        "error: unrecognized",
        "too many parameters",
        "too many arguments",
        "wrong parameter",
        "invalid parameter",
        "parameter error",
        "syntax error",
    )
    if any(m in text for m in markers_lower):
        return True

    markers_raw = (
        "参数过多",
        "位置参数",
        "参数错误",
        "语法错误",
        "命令无效",
        "无法识别",
        "不完整命令",
        "错误：",
        "错误:",
    )
    if any(m in raw for m in markers_raw):
        return True

    for line in raw.splitlines():
        if line.strip() == "^":
            return True

    return False

def _looks_like_security_logs(output: str) -> bool:
    import re
    raw = (output or "").strip()
    if not raw:
        return False
    if _output_indicates_command_error(raw):
        return False

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return False

    ip_count = len(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", raw))
    time_hit = bool(re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", raw)) or bool(re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", raw))
    lower = raw.lower()
    keyword_hit = any(k in lower for k in ("deny", "drop", "attack", "intrusion", "threat", "scan", "failed", "login", "security", "ips", "malware"))
    keyword_hit = keyword_hit or any(k in raw for k in ("攻击", "入侵", "威胁", "扫描", "拒绝", "阻断", "告警", "失败", "登录", "安全", "病毒"))

    score = 0
    score += 1 if ip_count >= 1 else 0
    score += 1 if time_hit else 0
    score += 1 if keyword_hit else 0
    return score >= 2

def _looks_like_alarm_logs(output: str) -> bool:
    import re
    raw = (output or "").strip()
    if not raw:
        return False
    if _output_indicates_command_error(raw):
        return False

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return False

    time_hit = bool(re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", raw)) or bool(re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", raw))
    lower = raw.lower()

    keyword_hit = any(k in lower for k in (
        "link", "down", "up", "flap", "interface", "port", "stp", "spanning", "bpdu",
        "ospf", "bgp", "isis", "neighbor", "adjacency",
        "cpu", "memory", "temperature", "fan", "power", "alarm", "critical", "warning", "error",
    ))
    keyword_hit = keyword_hit or any(k in raw for k in (
        "接口", "端口", "链路", "上线", "下线", "抖动", "邻居", "路由", "生成树",
        "告警", "严重", "重要", "警告", "错误", "异常", "温度", "风扇", "电源", "CPU", "内存",
    ))

    if time_hit and keyword_hit:
        return True

    syslog_like = bool(re.search(r"\b%[A-Z0-9_]+-\d+-", raw))
    return syslog_like and keyword_hit

def _looks_like_topology_output(output: str) -> bool:
    raw = (output or "").strip()
    if not raw:
        return False
    if _output_indicates_command_error(raw):
        return False

    lower = raw.lower()
    hits = 0
    hits += 1 if "lldp" in lower else 0
    hits += 1 if any(k in lower for k in ("neighbor", "neighbour", "chassis", "system name", "port id", "local interface", "remote port")) else 0
    hits += 1 if any(k in raw for k in ("邻居", "对端", "本端", "端口", "系统名称", "机箱", "管理地址")) else 0
    return hits >= 2

def _log_command_candidates(brand: str, device_version: Optional[str] = None) -> List[str]:
    b = (brand or "").strip()
    candidates_map = {
        "Huawei": [
            "display logbuffer type security",
            "display logbuffer",
        ],
        "H3C": [
            "display logbuffer",
            "display logbuffer level warning",
        ],
        "Cisco": [
            "show logging",
        ],
        "Juniper": [
            "show log messages",
            "show log messages | last 100",
        ],
        "Arista": [
            "show logging",
            "show logging last 100",
        ],
        "Extreme": [
            "show log",
        ],
        "MikroTik": [
            "/log print",
        ],
        "PaloAlto": [
            "show log system last 100",
            "show log traffic last 100",
        ],
        "CheckPoint": [
            "show logs",
        ],
        "F5": [
            "show sys log",
        ],
        "A10": [
            "show log",
        ],
        "Dell": [
            "show logging",
        ],
        "HP": [
            "show log",
            "show logging",
        ],
        "Aruba": [
            "show logging",
            "show log",
        ],
        "Brocade": [
            "show logging",
            "show log",
        ],
        "Ruckus": [
            "show logging",
            "show log",
        ],
        "Ubiquiti": [
            "show log",
            "cat /var/log/messages",
        ],
        "Sophos": [
            "show log",
        ],
        "SonicWall": [
            "show log",
        ],
        "WatchGuard": [
            "show log",
        ],
        "Zyxel": [
            "show log",
        ],
        "Fortinet": [
            "execute log display",
            "get log event",
        ],
        "Ruijie": [
            "show logging",
            "display logbuffer",
        ],
        "Sangfor": [
            "show logging",
            "display logbuffer",
        ],
    }
    base = candidates_map.get(b, [])
    if base:
        return base
    return ["show logging", "display logbuffer", "execute log display"]

def _alarm_command_candidates(brand: str, device_version: Optional[str] = None) -> List[str]:
    b = (brand or "").strip()
    candidates_map = {
        "Huawei": [
            "display alarm all",
            "display alarm",
            "display logbuffer",
        ],
        "H3C": [
            "display alarm all",
            "display alarm",
            "display logbuffer",
        ],
        "Cisco": [
            "show logging",
        ],
        "Juniper": [
            "show system alarms",
            "show chassis alarms",
            "show log messages | last 100",
        ],
        "Arista": [
            "show logging last 100",
            "show logging",
        ],
        "Extreme": [
            "show log",
        ],
        "MikroTik": [
            "/log print",
            "/system health print",
        ],
        "PaloAlto": [
            "show log system last 100",
            "show system info",
        ],
        "CheckPoint": [
            "show system status",
            "show logs",
        ],
        "F5": [
            "show sys hardware",
            "show sys log",
        ],
        "A10": [
            "show health",
            "show log",
        ],
        "Dell": [
            "show logging",
        ],
        "HP": [
            "show log",
            "show logging",
        ],
        "Aruba": [
            "show logging",
            "show log",
        ],
        "Brocade": [
            "show logging",
            "show log",
        ],
        "Ruckus": [
            "show logging",
            "show log",
        ],
        "Ubiquiti": [
            "show log",
            "cat /var/log/messages",
        ],
        "Sophos": [
            "show log",
        ],
        "SonicWall": [
            "show log",
        ],
        "WatchGuard": [
            "show log",
        ],
        "Zyxel": [
            "show log",
        ],
        "Fortinet": [
            "execute log display",
            "get log event",
        ],
        "Ruijie": [
            "show logging",
            "display logbuffer",
        ],
        "Sangfor": [
            "show logging",
            "display logbuffer",
        ],
    }
    base = candidates_map.get(b, [])
    if base:
        return base
    return ["show logging", "display logbuffer", "display alarm all"]

def _topology_command_candidates(brand: str, device_version: Optional[str] = None) -> List[str]:
    b = (brand or "").strip()
    candidates_map = {
        "Huawei": [
            "display lldp neighbor brief",
            "display lldp neighbor",
            "display lldp neighbor information",
        ],
        "H3C": [
            "display lldp neighbor-information list",
            "display lldp neighbor-information",
        ],
        "Cisco": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "Juniper": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "Arista": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "Extreme": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "Dell": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "HP": [
            "show lldp info remote-device detail",
            "show lldp info remote-device",
        ],
        "Aruba": [
            "show lldp neighbor-info detail",
            "show lldp neighbor-info",
        ],
        "Brocade": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "Ruckus": [
            "show lldp neighbors detail",
            "show lldp neighbors",
        ],
        "MikroTik": [
            "/interface lldp neighbors print",
        ],
        "Ubiquiti": [
            "show lldp neighbors",
            "lldpctl",
        ],
        "Fortinet": [
            "get switch lldp neighbors",
            "diagnose switch-controller lldp neighbors",
        ],
        "Ruijie": [
            "show lldp neighbors detail",
            "show lldp neighbors",
            "display lldp neighbor",
        ],
        "Sangfor": [
            "show lldp neighbors",
        ],
        "PaloAlto": [
            "show lldp neighbors",
        ],
        "CheckPoint": [
            "show lldp neighbors",
        ],
        "Sophos": [
            "show lldp neighbors",
        ],
        "SonicWall": [
            "show lldp neighbors",
        ],
        "WatchGuard": [
            "show lldp neighbors",
        ],
        "Zyxel": [
            "show lldp neighbors",
        ],
        "F5": [
            "show net lldp neighbors",
        ],
        "A10": [
            "show lldp neighbors",
        ],
    }
    base = candidates_map.get(b, [])
    if base:
        return base
    return ["show lldp neighbors detail", "show lldp neighbors"]

async def get_commands_with_skill_cache(analyzer: AIAnalyzer, intent: str, brand: str, device_version: Optional[str] = None) -> List[str]:
    existing = _find_skill(intent=intent, brand=brand, device_version=device_version)
    if existing and isinstance(existing.get("commands"), list) and existing["commands"]:
        return existing["commands"]
    return await asyncio.to_thread(analyzer.generate_commands_by_intent, intent, brand, device_version=device_version)

async def collect_cli_output(adapter: FirewallAdapter, analyzer: AIAnalyzer, intent: str, brand: str, device_version: Optional[str] = None, validation: Optional[str] = None, allow_ai: bool = True):
    existing = _find_skill(intent=intent, brand=brand, device_version=device_version)
    if existing and isinstance(existing.get("commands"), list) and existing["commands"]:
        try:
            output = await asyncio.to_thread(adapter.execute_commands, existing["commands"])
            if (
                not _output_indicates_command_error(output)
                and (validation != "logs" or _looks_like_security_logs(output))
                and (validation != "alarms" or _looks_like_alarm_logs(output))
                and (validation != "topology" or _looks_like_topology_output(output))
            ):
                return output
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    if validation == "logs":
        for cmd in _log_command_candidates(brand, device_version):
            try:
                output = await asyncio.to_thread(adapter.execute_commands, [cmd])
                if not _output_indicates_command_error(output) and _looks_like_security_logs(output):
                    _upsert_skill(intent=intent, brand=brand, device_version=device_version, commands=[cmd], description=f"自动验证通过的 {intent} 指令集", source="ai")
                    return output
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
    if validation == "alarms":
        for cmd in _alarm_command_candidates(brand, device_version):
            try:
                output = await asyncio.to_thread(adapter.execute_commands, [cmd])
                if not _output_indicates_command_error(output) and _looks_like_alarm_logs(output):
                    _upsert_skill(intent=intent, brand=brand, device_version=device_version, commands=[cmd], description=f"自动验证通过的 {intent} 指令集", source="ai")
                    return output
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
    if validation == "topology":
        for cmd in _topology_command_candidates(brand, device_version)[:4]:
            try:
                output = await asyncio.to_thread(adapter.execute_commands, [cmd])
                if not _output_indicates_command_error(output) and _looks_like_topology_output(output):
                    _upsert_skill(intent=intent, brand=brand, device_version=device_version, commands=[cmd], description=f"自动验证通过的 {intent} 指令集", source="ai")
                    return output
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
        if not allow_ai:
            raise RuntimeError("未能获取有效 LLDP 邻居信息输出（已尝试命令候选集）。")

    if not allow_ai:
        raise RuntimeError("未能获取有效输出（allow_ai=false）。")

    commands = await asyncio.to_thread(analyzer.generate_commands_by_intent, intent, brand, device_version=device_version)
    try:
        output = await asyncio.to_thread(adapter.execute_commands, commands)
        attempts = 0
        while True:
            is_error = _output_indicates_command_error(output)
            is_mismatch = (validation == "logs" and not _looks_like_security_logs(output))
            is_mismatch = is_mismatch or (validation == "alarms" and not _looks_like_alarm_logs(output))
            is_mismatch = is_mismatch or (validation == "topology" and not _looks_like_topology_output(output))
            if not is_error and not is_mismatch:
                break
            if attempts >= 1:
                break
            feedback = (output or "").strip().replace("\r", "")[:240]
            if is_error:
                retry_intent = f"{intent}\n上一次执行输出提示：{feedback}\n请给可用的替代只读命令。"
            else:
                if validation == "alarms":
                    retry_intent = f"{intent}\n上一次执行输出看起来不像有效告警/事件日志（可能命令不对或输出字段不足）。输出摘要：{feedback}\n请给能输出可解析告警/事件日志的只读命令。"
                elif validation == "topology":
                    retry_intent = f"{intent}\n上一次执行输出看起来不像有效 LLDP 邻居信息（可能 LLDP 未开启或命令不对）。输出摘要：{feedback}\n请给能输出 LLDP 邻居信息的只读命令。"
                else:
                    retry_intent = f"{intent}\n上一次执行输出看起来不像有效安全日志（可能命令不对或输出字段不足）。输出摘要：{feedback}\n请给能输出可解析安全日志的只读命令。"
            commands = await asyncio.to_thread(analyzer.generate_commands_by_intent, retry_intent, brand, device_version=device_version)
            output = await asyncio.to_thread(adapter.execute_commands, commands)
            attempts += 1

        if (
            not _output_indicates_command_error(output)
            and (validation != "logs" or _looks_like_security_logs(output))
            and (validation != "alarms" or _looks_like_alarm_logs(output))
            and (validation != "topology" or _looks_like_topology_output(output))
        ):
            _upsert_skill(
                intent=intent,
                brand=brand,
                device_version=device_version,
                commands=commands,
                description=f"自动验证通过的 {intent} 指令集",
                source="ai",
                validation=validation,
                sample_output=_truncate_text(output, 360),
                verified=True,
            )
        if validation in ("logs", "alarms", "topology"):
            failed = _output_indicates_command_error(output)
            if validation == "logs":
                failed = failed or (not _looks_like_security_logs(output))
            if validation == "alarms":
                failed = failed or (not _looks_like_alarm_logs(output))
            if validation == "topology":
                failed = failed or (not _looks_like_topology_output(output))
            if failed:
                snippet = (output or "").strip().replace("\r", "")[:280]
                kind = "安全日志" if validation == "logs" else "告警/事件日志" if validation == "alarms" else "LLDP 邻居信息"
                raise RuntimeError(f"未能获取有效{kind}输出（可能命令不匹配或功能未启用）。输出：{snippet}")
        return output
    except Exception:
        raise

def _truncate_text(value: Optional[str], limit: int) -> str:
    return (value or "").replace("\r", "")[: max(0, int(limit or 0))]

def _backup_intent(protocol: str) -> str:
    p = (protocol or "").strip().lower() or "tftp"
    return f"备份运行配置到{p}备份服务器"

def _safe_path_join(base_path: str, name: str) -> str:
    b = (base_path or "").strip() or "/"
    n = (name or "").strip()
    if not n:
        return b
    if b.endswith("/"):
        return b + n.lstrip("/")
    return b + "/" + n.lstrip("/")

def _build_backup_filename(dev: DeviceConfig) -> str:
    prefix = (getattr(dev, "backup_filename_prefix", None) or getattr(dev, "alias", None) or getattr(dev, "id", None) or "device").strip()
    safe = re.sub(r"[^a-zA-Z0-9_.\-]+", "_", prefix)[:40] or "device"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{ts}.cfg"

def _render_template(text: str, values: Dict[str, str]) -> str:
    t = str(text or "")
    if not t:
        return ""
    def repl(m):
        k = m.group(1)
        if k in values:
            return str(values[k] or "")
        return m.group(0)
    return re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, t)

def _looks_like_backup_success(output: str) -> bool:
    text = (output or "").replace("\r", "")
    if _output_indicates_command_error(text):
        return False
    compact = " ".join([x.strip() for x in text.splitlines() if x.strip()])[:1200].lower()
    if len(compact) < 16:
        return False
    tokens = [
        "bytes copied",
        "copy complete",
        "copied",
        "completed",
        "complete",
        "success",
        "successful",
        "transfer",
        "tftp",
        "ftp",
        "sftp",
        "scp",
        "saved",
        "writing",
        "upload",
    ]
    return any(t in compact for t in tokens)

async def run_device_backup(device_id: str, trigger: str = "manual", allow_ai: bool = True) -> Dict[str, Any]:
    dev = db["devices"].get(device_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="设备未找到")
    backup_server_id = getattr(dev, "backup_server_id", None) or ""
    server = db["backup_servers"].get(backup_server_id) if backup_server_id else None
    if not isinstance(server, dict):
        raise HTTPException(status_code=400, detail="该设备未关联备份服务器，请先在资产管理或备份中心配置")

    with _BACKUP_RUNNING_LOCK:
        if device_id in _BACKUP_RUNNING:
            raise HTTPException(status_code=409, detail="该设备正在执行备份任务")
        _BACKUP_RUNNING.add(device_id)

    t0 = time.perf_counter()
    try:
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        ai_conf = db.get("ai")
        analyzer = None
        if ai_conf and getattr(ai_conf, "api_key", "").strip():
            analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)

        version_tag = getattr(dev, "os_version", None) or await asyncio.to_thread(_detect_device_version, adapter, dev.brand)
        if (not version_tag) and analyzer and allow_ai:
            try:
                version_tag = await asyncio.to_thread(_detect_device_version_with_ai, adapter, analyzer, dev.brand)
            except Exception:
                version_tag = None
        if version_tag and version_tag != getattr(dev, "os_version", None):
            dev.os_version = version_tag
            await asyncio.to_thread(_save_persisted_state)

        protocol = (server.get("protocol") or "tftp").strip().lower()
        intent = _backup_intent(protocol)
        existing = _find_skill(intent=intent, brand=dev.brand, device_version=version_tag)

        filename = _build_backup_filename(dev)
        remote_path = _safe_path_join(server.get("path") or "/", filename)
        server_ip = (server.get("server_ip") or "").strip()
        username = (server.get("username") or "").strip()
        password = (server.get("password") or "").strip()
        backup_url = ""
        if protocol in ("ftp", "sftp"):
            if username and password:
                backup_url = f"{protocol}://{username}:{password}@{server_ip}{remote_path if remote_path.startswith('/') else '/' + remote_path}"
            elif username:
                backup_url = f"{protocol}://{username}@{server_ip}{remote_path if remote_path.startswith('/') else '/' + remote_path}"
            else:
                backup_url = f"{protocol}://{server_ip}{remote_path if remote_path.startswith('/') else '/' + remote_path}"

        values = {
            "server_ip": server_ip,
            "protocol": protocol,
            "username": username,
            "password": password,
            "path": (server.get("path") or "/").strip() or "/",
            "remote_path": remote_path,
            "filename": filename,
            "device_id": str(getattr(dev, "id", "") or device_id),
            "backup_url": backup_url,
        }

        used_ai = False
        used_skill_id = existing.get("id") if isinstance(existing, dict) else None
        if existing and isinstance(existing.get("commands"), list) and existing["commands"]:
            templates = [str(x) for x in existing["commands"] if str(x).strip()]
        else:
            if not (analyzer and allow_ai):
                raise HTTPException(status_code=400, detail="缺少可复用的备份 Skill，且未配置 AI（或 allow_ai=false）。")
            used_ai = True
            ai_payload = await asyncio.to_thread(analyzer.generate_backup_command_templates, dev.brand, version_tag, protocol)
            templates = [str(x).strip() for x in (ai_payload.get("commands") or []) if str(x).strip()]
            if not templates:
                raise HTTPException(status_code=500, detail="AI 未返回可用的备份命令模板")
            prerequisites = ai_payload.get("prerequisites") or ""
            tags = ai_payload.get("tags") or ["backup", protocol]
            used_skill_id = None

        commands = [_render_template(t, values) for t in templates]
        output = await asyncio.to_thread(adapter.execute_commands, commands)
        ok = _looks_like_backup_success(output)
        dt_ms = int((time.perf_counter() - t0) * 1000)

        history_entry = {
            "id": f"backup_{uuid.uuid4().hex[:10]}",
            "time": datetime.datetime.now(),
            "trigger": trigger,
            "ok": bool(ok),
            "device_id": device_id,
            "brand": dev.brand,
            "device_version": version_tag,
            "backup_server_id": backup_server_id,
            "protocol": protocol,
            "remote_path": remote_path,
            "used_ai": bool(used_ai),
            "used_skill_id": used_skill_id,
            "output": _truncate_text(output, 1200),
            "dt_ms": dt_ms,
        }
        db.setdefault("backup_history", {})
        db["backup_history"].setdefault(device_id, [])
        db["backup_history"][device_id].append(history_entry)
        db.setdefault("last_backup", {})
        db["last_backup"][device_id] = datetime.datetime.now()

        created_skill_id = None
        if ok and used_ai:
            desc = f"自动验证通过的 {intent} 指令模板（已支持占位符 server_ip/remote_path/backup_url/filename）"
            _upsert_skill(
                intent=intent,
                brand=dev.brand,
                device_version=version_tag,
                commands=templates,
                description=desc,
                source="ai",
                tags=tags,
                prerequisites=prerequisites,
                validation="backup",
                sample_output=_truncate_text(output, 360),
                verified=True,
            )
            saved = _find_skill(intent=intent, brand=dev.brand, device_version=version_tag)
            if isinstance(saved, dict):
                created_skill_id = saved.get("id")

        await asyncio.to_thread(_save_persisted_state)

        if not ok:
            raise HTTPException(status_code=500, detail=f"备份命令已执行但未检测到成功特征。输出：{_truncate_text(output, 280)}")

        return {
            "ok": True,
            "device_id": device_id,
            "backup_server_id": backup_server_id,
            "protocol": protocol,
            "remote_path": remote_path,
            "used_ai": used_ai,
            "used_skill_id": used_skill_id,
            "created_skill_id": created_skill_id,
            "dt_ms": dt_ms,
        }
    finally:
        with _BACKUP_RUNNING_LOCK:
            _BACKUP_RUNNING.discard(device_id)

def _extract_prompt_name(output: str) -> Optional[str]:
    text = (output or "").replace("\r", "")
    name = None
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^[<\[](?P<name>[^>\]\s]{1,64})[>\]]$", line)
        if m:
            name = m.group("name")
    return name

def _base_url_reachable(base_url: Optional[str], timeout_s: float) -> bool:
    url = (base_url or "").strip()
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port
        if not port:
            if (parsed.scheme or "").lower() == "https":
                port = 443
            else:
                port = 80
        conn = socket.create_connection((host, port), timeout=float(timeout_s or 0.0))
        conn.close()
        return True
    except Exception:
        return False

def _parse_huawei_lldp_neighbor_brief(output: str) -> List[Dict[str, str]]:
    text = (output or "").replace("\r", "")
    rows: List[Dict[str, str]] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("display lldp"):
            continue
        if "local intf" in lower and "neighbor" in lower:
            continue
        if (line.startswith("[") and line.endswith("]")) or (line.startswith("<") and line.endswith(">")):
            continue
        m = re.match(r"^(?P<local>\S+)\s+(?P<neighbor>\S+)\s+(?P<remote>\S+)\s+(?P<exp>\d+)\s*$", line)
        if not m:
            continue
        rows.append(
            {
                "local_port": m.group("local"),
                "neighbor_dev": m.group("neighbor"),
                "remote_port": m.group("remote"),
                "expires": m.group("exp"),
            }
        )
    return rows

def _fallback_topology_from_payload(payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    node_map: Dict[str, Dict[str, Any]] = {}
    links: List[Dict[str, Any]] = []
    link_seen = set()
    device_name_map: Dict[str, str] = {}
    name_to_device_id: Dict[str, str] = {}

    for p in payload:
        node_id = p.get("device_id") or p.get("host") or "unknown"
        prompt_name = _extract_prompt_name(p.get("lldp_output") or "")
        if prompt_name:
            device_name_map[node_id] = prompt_name
            name_to_device_id.setdefault(prompt_name, node_id)
        host_port = f"{p.get('host')}:{p.get('port')}" if p.get("host") and p.get("port") else (p.get("host") or "")
        label = prompt_name or p.get("alias") or host_port or node_id
        node = {
            "id": node_id,
            "label": label,
            "brand": p.get("brand"),
            "host": p.get("host"),
            "device_id": p.get("device_id"),
            "collected_at": p.get("collected_at"),
        }
        node_map[node_id] = node

    for p in payload:
        if p.get("error") or not (p.get("lldp_output") or "").strip():
            continue
        source_id = p.get("device_id") or p.get("host") or "unknown"
        brand = (p.get("brand") or "").strip()
        out = p.get("lldp_output") or ""

        entries: List[Dict[str, str]] = []
        if brand == "Huawei":
            entries = _parse_huawei_lldp_neighbor_brief(out)

        for e in entries:
            neigh_label = (e.get("neighbor_dev") or "unknown").strip() or "unknown"
            target_id = name_to_device_id.get(neigh_label) or f"unknown:{neigh_label}"
            if target_id not in node_map:
                node_map[target_id] = {"id": target_id, "label": neigh_label}
            local_port = e.get("local_port") or ""
            remote_port = e.get("remote_port") or ""
            expires_s = None
            try:
                expires_s = int(e.get("expires")) if e.get("expires") is not None else None
            except Exception:
                expires_s = None
            a, b = (source_id, target_id) if source_id <= target_id else (target_id, source_id)
            a_port, b_port = (local_port, remote_port) if source_id == a else (remote_port, local_port)
            link_key = (a, b, a_port, b_port, "lldp")
            if link_key in link_seen:
                continue
            link_seen.add(link_key)
            links.append(
                {
                    "source": a,
                    "target": b,
                    "local_port": a_port or None,
                    "remote_port": b_port or None,
                    "protocol": "lldp",
                    "expires_s": expires_s,
                }
            )

    nodes = list(node_map.values())
    ok_cnt = sum(1 for p in payload if (p.get("lldp_output") or "").strip() and not p.get("error"))
    err_cnt = sum(1 for p in payload if p.get("error"))
    parsed_links = len(links)
    summary = f"已采集设备：{len(payload)}，成功：{ok_cnt}，失败：{err_cnt}；基于 LLDP 输出解析到链路：{parsed_links}（未调用/未依赖大模型）。"
    return {"nodes": nodes, "links": links, "summary": summary}

async def detect_device_version_with_debug(adapter: FirewallAdapter, analyzer: AIAnalyzer, brand: str):
    attempts: List[Dict[str, Any]] = []

    candidates_map = {
        "Huawei": ["display version"],
        "H3C": ["display version"],
        "Cisco": ["show version"],
        "Juniper": ["show version"],
        "Arista": ["show version"],
        "Extreme": ["show version"],
        "Dell": ["show version"],
        "HP": ["show version"],
        "Aruba": ["show version"],
        "Brocade": ["show version"],
        "Ruckus": ["show version"],
        "MikroTik": ["/system resource print"],
        "Ubiquiti": ["show version"],
        "PaloAlto": ["show system info"],
        "CheckPoint": ["show version"],
        "Sophos": ["show version"],
        "SonicWall": ["show version"],
        "WatchGuard": ["show version"],
        "Zyxel": ["show version"],
        "Fortinet": ["get system status", "get system performance status"],
        "Ruijie": ["show version", "display version"],
        "Sangfor": ["show version", "display version"],
        "F5": ["show sys version"],
        "A10": ["show version"],
    }
    candidates = candidates_map.get(brand, []) + ["show version", "display version", "get system status"]
    seen = set()
    for cmd in candidates:
        cmd = str(cmd).strip()
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        try:
            out = await asyncio.to_thread(adapter.execute_commands, [cmd])
            tag = _extract_version_tag(brand, out)
            ok = bool(tag) and (not _output_indicates_command_error(out))
            attempts.append(
                {
                    "source": "candidate",
                    "commands": [cmd],
                    "ok": ok,
                    "version_tag": tag,
                    "output_snippet": _truncate_text(out, 1200),
                }
            )
            if ok:
                return tag, {"used_commands": [cmd], "attempts": attempts}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            attempts.append(
                {
                    "source": "candidate",
                    "commands": [cmd],
                    "ok": False,
                    "error": str(e)[:240],
                }
            )

    try:
        ai_cmds = await asyncio.to_thread(analyzer.generate_commands_by_intent, "获取设备系统版本信息（只读）", brand, device_version=None)
        ai_cmds = [str(x) for x in (ai_cmds or []) if str(x).strip()]
        if ai_cmds:
            out = await asyncio.to_thread(adapter.execute_commands, ai_cmds)
            tag = _extract_version_tag(brand, out)
            ok = bool(tag) and (not _output_indicates_command_error(out))
            attempts.append(
                {
                    "source": "ai",
                    "commands": ai_cmds,
                    "ok": ok,
                    "version_tag": tag,
                    "output_snippet": _truncate_text(out, 1200),
                }
            )
            if ok:
                return tag, {"used_commands": ai_cmds, "attempts": attempts}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        attempts.append({"source": "ai", "ok": False, "error": str(e)[:240]})

    return None, {"attempts": attempts}

async def collect_topology_cli_output_with_debug(adapter: FirewallAdapter, analyzer: AIAnalyzer, brand: str, device_version: Optional[str] = None):
    intent = "查看 LLDP 邻居信息"
    attempts: List[Dict[str, Any]] = []

    existing = _find_skill(intent=intent, brand=brand, device_version=device_version)
    if existing and isinstance(existing.get("commands"), list) and existing["commands"]:
        cmds = [str(x) for x in existing["commands"] if str(x).strip()]
        if cmds:
            try:
                output = await asyncio.to_thread(adapter.execute_commands, cmds)
                ok = (not _output_indicates_command_error(output)) and _looks_like_topology_output(output)
                attempts.append(
                    {
                        "source": "skill",
                        "commands": cmds,
                        "ok": ok,
                        "output_snippet": _truncate_text(output, 1200),
                    }
                )
                if ok:
                    return output, {"used_commands": cmds, "attempts": attempts}
            except asyncio.CancelledError:
                raise
            except Exception as e:
                attempts.append(
                    {
                        "source": "skill",
                        "commands": cmds,
                        "ok": False,
                        "error": str(e)[:240],
                    }
                )

    for cmd in _topology_command_candidates(brand, device_version)[:4]:
        cmd = str(cmd).strip()
        if not cmd:
            continue
        try:
            output = await asyncio.to_thread(adapter.execute_commands, [cmd])
            ok = (not _output_indicates_command_error(output)) and _looks_like_topology_output(output)
            attempts.append(
                {
                    "source": "candidate",
                    "commands": [cmd],
                    "ok": ok,
                    "output_snippet": _truncate_text(output, 1200),
                }
            )
            if ok:
                _upsert_skill(
                    intent=intent,
                    brand=brand,
                    device_version=device_version,
                    commands=[cmd],
                    description=f"自动验证通过的 {intent} 指令集",
                    source="ai",
                    validation="topology",
                    sample_output=_truncate_text(output, 360),
                    verified=True,
                )
                return output, {"used_commands": [cmd], "attempts": attempts}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            attempts.append(
                {
                    "source": "candidate",
                    "commands": [cmd],
                    "ok": False,
                    "error": str(e)[:240],
                }
            )

    raise RuntimeError(json.dumps({"message": "未能获取有效 LLDP 邻居信息输出（已尝试命令候选集）。", "attempts": attempts}, ensure_ascii=False))
    commands = await asyncio.to_thread(analyzer.generate_commands_by_intent, intent, brand, device_version=device_version)
    commands = [str(x) for x in (commands or []) if str(x).strip()]
    if commands:
        try:
            output = await asyncio.to_thread(adapter.execute_commands, commands)
            ok = (not _output_indicates_command_error(output)) and _looks_like_topology_output(output)
            attempts.append(
                {
                    "source": "ai",
                    "commands": commands,
                    "ok": ok,
                    "output_snippet": _truncate_text(output, 1200),
                }
            )
            if ok:
                _upsert_skill(
                    intent=intent,
                    brand=brand,
                    device_version=device_version,
                    commands=commands,
                    description=f"自动验证通过的 {intent} 指令集",
                    source="ai",
                    validation="topology",
                    sample_output=_truncate_text(output, 360),
                    verified=True,
                )
                return output, {"used_commands": commands, "attempts": attempts}

            feedback = (output or "").strip().replace("\r", "")[:240]
            retry_intent = f"{intent}\n上一次执行输出看起来不像有效 LLDP 邻居信息（可能 LLDP 未开启或命令不对）。输出摘要：{feedback}\n请给能输出 LLDP 邻居信息的只读命令。"
            retry_commands = await asyncio.to_thread(analyzer.generate_commands_by_intent, retry_intent, brand, device_version=device_version)
            retry_commands = [str(x) for x in (retry_commands or []) if str(x).strip()]
            if retry_commands:
                retry_output = await asyncio.to_thread(adapter.execute_commands, retry_commands)
                retry_ok = (not _output_indicates_command_error(retry_output)) and _looks_like_topology_output(retry_output)
                attempts.append(
                    {
                        "source": "ai_retry",
                        "commands": retry_commands,
                        "ok": retry_ok,
                        "output_snippet": _truncate_text(retry_output, 1200),
                    }
                )
                if retry_ok:
                    _upsert_skill(
                        intent=intent,
                        brand=brand,
                        device_version=device_version,
                        commands=retry_commands,
                        description=f"自动验证通过的 {intent} 指令集",
                        source="ai",
                        validation="topology",
                        sample_output=_truncate_text(retry_output, 360),
                        verified=True,
                    )
                    return retry_output, {"used_commands": retry_commands, "attempts": attempts}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            attempts.append(
                {
                    "source": "ai",
                    "commands": commands,
                    "ok": False,
                    "error": str(e)[:240],
                }
            )

    raise RuntimeError(json.dumps({"message": "未能获取有效 LLDP 邻居信息输出（已尝试技能/候选/AI）。", "attempts": attempts}, ensure_ascii=False))

import subprocess
import platform

async def ping_host(host: str) -> bool:
    """跨平台连通性测试 (Windows, macOS, Linux)"""
    host = host.strip()
    is_windows = platform.system().lower() == "windows"
    param = "-n" if is_windows else "-c"
    command = ["ping", param, "1", host]
    
    try:
        def _run_ping():
            return subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                shell=is_windows
            )

        result = await asyncio.to_thread(_run_ping)
        
        if result.returncode != 0:
            # 自动识别编码进行日志输出
            encoding = 'gbk' if is_windows else 'utf-8'
            err_msg = result.stderr.decode(encoding, errors='ignore')
            print(f"Ping failed for {host} ({platform.system()}). Return code: {result.returncode}")
            if err_msg: print(f"Error: {err_msg}")
            
        return result.returncode == 0
    except Exception as e:
        print(f"Ping exception on {platform.system()} for {host}: {str(e)}")
        return False

# --- 巡检核心逻辑 ---

async def run_device_inspection(device_id: str):
    if not db["ai"] or device_id not in db["devices"]:
        return
    
    dev = db["devices"][device_id]
    ai_conf = db["ai"]
    
    try:
        # 0. 先进行 Ping 测试
        is_alive = await ping_host(dev.host)
        if not is_alive:
            db["inspections"][device_id] = {"status": "offline", "error": "Ping timeout", "time": datetime.datetime.now()}
            return

        db["inspections"][device_id] = {"status": "analyzing", "time": datetime.datetime.now()}
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)
        version_tag = dev.os_version or await asyncio.to_thread(_detect_device_version, adapter, dev.brand) or await asyncio.to_thread(_detect_device_version_with_ai, adapter, analyzer, dev.brand)
        if version_tag and version_tag != dev.os_version:
            dev.os_version = version_tag
            await asyncio.to_thread(_save_persisted_state)

        health_output = await collect_cli_output(adapter, analyzer, "查看设备的 CPU 使用率、内存使用率、运行温度", dev.brand, version_tag)
        health = adapter.parse_health_output(health_output)
        db["health_data"][device_id] = health
        
        raw_logs = await collect_cli_output(adapter, analyzer, "查看最近的被攻击日志或安全日志", dev.brand, version_tag, validation="logs")
        
        # 如果能走到这里，说明连接成功
        db["inspections"][device_id]["status"] = "online"
        
        report = await asyncio.to_thread(analyzer.analyze_logs, raw_logs, dev.brand)
        
        new_risks = [r for r in report.get("risks", []) if r.get("level") == "高"]
        if new_risks:
            db["pending_actions"].append({
                "id": f"risk_{int(datetime.datetime.now().timestamp())}",
                "device_id": device_id,
                "host": dev.host,
                "port": dev.port,
                "alias": dev.alias,
                "risks": new_risks,
                "summary": report.get("summary"),
                "time": datetime.datetime.now(),
                "status": "pending"
            })
            db["inspections"][device_id]["status"] = "threat_detected"
        else:
            db["inspections"][device_id]["status"] = "online" # 保持在线状态
            
        db["last_run"][device_id] = datetime.datetime.now()
            
    except Exception as e:
        # 精细化捕获错误原因
        err_msg = str(e).lower()
        status = "offline"
        if "authentication" in err_msg or "password" in err_msg:
            status = "unauthorized"
        
        db["inspections"][device_id] = {
            "status": status, 
            "error": str(e),
            "time": datetime.datetime.now()
        }

async def connectivity_monitor():
    """全时在线监测任务：每 30 秒执行一次 Ping 探测，更新设备基础在线状态"""
    while True:
        # print(f"[{datetime.datetime.now()}] 启动全网连通性扫描...")
        for device_id, dev in db["devices"].items():
            try:
                is_alive = await ping_host(dev.host)
                # 仅在不处于“正在分析”状态时更新状态，避免覆盖 AI 巡检的中间状态
                current_status = db["inspections"].get(device_id, {}).get("status")
                if current_status != "analyzing":
                    db["inspections"][device_id] = {
                        "status": "online" if is_alive else "offline",
                        "time": datetime.datetime.now(),
                        "error": None if is_alive else "Ping timeout"
                    }
            except Exception as e:
                print(f"Monitor error for {device_id}: {e}")
        await asyncio.sleep(30)

async def inspection_scheduler():
    """AI 巡检调度任务：根据各设备设置的间隔执行深度安全分析"""
    while True:
        if db["settings"]["auto_inspect"]:
            now = datetime.datetime.now()
            enabled_entries = db["settings"].get("enabled_devices", []) or []
            enabled_set = {str(x).strip() for x in enabled_entries if str(x).strip()}
            device_ids = list(db["devices"].keys()) if not enabled_set else [
                device_id
                for device_id, dev in db["devices"].items()
                if (device_id in enabled_set) or (dev.host in enabled_set)
            ]
            for device_id in device_ids:
                dev = db["devices"].get(device_id)
                if not dev:
                    continue
                
                last_time = db["last_run"].get(device_id)
                # 检查是否达到该设备的巡检间隔
                if last_time is None or (now - last_time).total_seconds() >= dev.inspection_interval * 60:
                    asyncio.create_task(run_device_inspection(device_id))
        await asyncio.sleep(60)

async def backup_scheduler():
    while True:
        now = datetime.datetime.now()
        for device_id, dev in db["devices"].items():
            try:
                if not getattr(dev, "backup_enabled", False):
                    continue
                interval_min = int(getattr(dev, "backup_interval", 0) or 0)
                if interval_min <= 0:
                    continue
                server_id = (getattr(dev, "backup_server_id", None) or "").strip()
                if not server_id:
                    continue
                server = db["backup_servers"].get(server_id)
                protocol = (server.get("protocol") if isinstance(server, dict) else None) or ""
                intent = _backup_intent(protocol or "tftp")
                existing = _find_skill(intent=intent, brand=getattr(dev, "brand", "") or "", device_version=getattr(dev, "os_version", None))
                ai_conf = db.get("ai")
                has_ai = bool(ai_conf and getattr(ai_conf, "api_key", "").strip())
                if (not existing) and (not has_ai):
                    continue
                last_time = db.get("last_backup", {}).get(device_id)
                due = (last_time is None) or ((now - last_time).total_seconds() >= interval_min * 60)
                if due:
                    async def _runner(did: str):
                        try:
                            await run_device_backup(did, trigger="schedule", allow_ai=True)
                        except Exception:
                            return
                    asyncio.create_task(_runner(device_id))
            except Exception:
                continue
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    _load_persisted_state()
    _ensure_auth_bootstrap()
    asyncio.create_task(inspection_scheduler())
    asyncio.create_task(connectivity_monitor())
    asyncio.create_task(backup_scheduler())

# --- API 路由 ---

@app.post("/config/settings")
async def update_settings(settings: InspectionSettings):
    db["settings"]["auto_inspect"] = settings.auto_inspect
    db["settings"]["enabled_devices"] = settings.enabled_devices
    await asyncio.to_thread(_save_persisted_state)
    return db["settings"]

@app.get("/config/backup")
async def list_backup_servers():
    return list(db["backup_servers"].values())

@app.post("/config/backup")
async def add_backup_server(server: BackupServer):
    db["backup_servers"][server.id] = server.dict()
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "备份服务器已保存"}

@app.delete("/config/backup/{server_id}")
async def remove_backup_server(server_id: str):
    if server_id in db["backup_servers"]:
        del db["backup_servers"][server_id]
        await asyncio.to_thread(_save_persisted_state)
        return {"message": "备份服务器已移除"}
    raise HTTPException(status_code=404, detail="服务器未找到")

@app.get("/backup/status")
async def get_backup_status():
    items = []
    for device_id, dev in db["devices"].items():
        server_id = (getattr(dev, "backup_server_id", None) or "").strip()
        server = db["backup_servers"].get(server_id) if server_id else None
        protocol = (server.get("protocol") if isinstance(server, dict) else None) or ""
        last_time = db.get("last_backup", {}).get(device_id)
        interval_min = int(getattr(dev, "backup_interval", 0) or 0)
        next_run = None
        if isinstance(last_time, datetime.datetime) and interval_min > 0:
            next_run = last_time + datetime.timedelta(minutes=interval_min)
        items.append(
            {
                "device_id": device_id,
                "alias": getattr(dev, "alias", None),
                "brand": getattr(dev, "brand", None),
                "device_version": getattr(dev, "os_version", None),
                "backup_enabled": bool(getattr(dev, "backup_enabled", False)),
                "backup_interval": interval_min,
                "backup_server_id": server_id,
                "backup_protocol": protocol,
                "last_backup": last_time,
                "next_backup": next_run,
            }
        )
    return items

@app.get("/backup/history/{device_id}")
async def get_backup_history(device_id: str):
    items = db.get("backup_history", {}).get(device_id, []) or []
    return items[-50:]

@app.post("/backup/run/{device_id}")
async def run_backup_now(device_id: str):
    return await run_device_backup(device_id, trigger="manual", allow_ai=True)

@app.get("/config/ai/models")
async def get_ai_models():
    """动态获取 LLM 模型列表"""
    if not db["ai"] or not db["ai"].api_key:
        return []
    
    import httpx
    ai = db["ai"]
    url = f"{ai.base_url or 'https://api.openai.com/v1'}/models"
    headers = {"Authorization": f"Bearer {ai.api_key}"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 提取模型 ID 列表并排序
                models = [m["id"] for m in data.get("data", [])]
                return sorted(models)
            return []
    except Exception as e:
        return []

@app.get("/config/settings")
async def get_settings():
    return db["settings"]

# --- 资产管理接口 ---

@app.get("/devices")
async def list_devices():
    return list(db["devices"].values())

@app.get("/devices/status")
async def get_all_devices_status():
    """获取所有设备的最新健康状态及看板统计信息"""
    enabled_entries = db["settings"].get("enabled_devices", []) or []
    enabled_set = {str(x).strip() for x in enabled_entries if str(x).strip()}
    stats = {}
    for device_id, dev in db["devices"].items():
        inspection = db["inspections"].get(device_id, {"status": "unknown"})
        last_backup = db.get("last_backup", {}).get(device_id)
        backup_interval = int(getattr(dev, "backup_interval", 0) or 0)
        next_backup = None
        if isinstance(last_backup, datetime.datetime) and backup_interval > 0:
            next_backup = last_backup + datetime.timedelta(minutes=backup_interval)
        stats[device_id] = {
            "id": device_id,
            "host": dev.host,
            "port": dev.port,
            "alias": dev.alias,
            "brand": dev.brand,
            "status": inspection.get("status"),
            "error": inspection.get("error"),
            "health": db["health_data"].get(device_id, {"cpu_usage": 0, "mem_usage": 0, "temperature": 0}),
            "last_run": db["last_run"].get(device_id),
            "policy_count": len(db["policy_history"].get(device_id, [])),
            "inspection_interval": dev.inspection_interval,
            "backup_enabled": bool(getattr(dev, "backup_enabled", False)),
            "backup_interval": backup_interval,
            "backup_server_id": getattr(dev, "backup_server_id", None),
            "last_backup": last_backup,
            "next_backup": next_backup,
            "is_enabled": (not enabled_set) or (device_id in enabled_set) or (dev.host in enabled_set)
        }
    return stats

@app.post("/devices")
async def add_device(device: DeviceConfig):
    device.host = device.host.strip()
    device.username = (device.username or "").strip()
    device.password = (device.password or "").strip()
    device_id = (device.id or f"{device.host}:{device.port}").strip()
    device.id = device_id
    if device_id in db["devices"]:
        db["devices"][device_id] = device
        await asyncio.to_thread(_save_persisted_state)
        return {"message": f"设备 {device_id} 已更新", "device": device}
    
    db["devices"][device_id] = device
    
    # 添加后立即进行一次 Ping 探测，避免 unknown 状态
    print(f"Adding device {device_id}, triggering initial ping...")
    is_alive = await ping_host(device.host)
    db["inspections"][device_id] = {
        "status": "online" if is_alive else "offline",
        "time": datetime.datetime.now()
    }
    
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "设备添加成功并已完成首次连通性探测", "device": device}

@app.delete("/devices/{device_id}")
async def remove_device(device_id: str):
    if device_id in db["devices"]:
        del db["devices"][device_id]
        db["inspections"].pop(device_id, None)
        db["health_data"].pop(device_id, None)
        db["last_run"].pop(device_id, None)
        db["policy_history"].pop(device_id, None)
        if device_id in db["settings"].get("enabled_devices", []):
            db["settings"]["enabled_devices"] = [d for d in db["settings"]["enabled_devices"] if d != device_id]
        await asyncio.to_thread(_save_persisted_state)
        return {"message": "设备已移除"}
    raise HTTPException(status_code=404, detail="设备未找到")

@app.post("/devices/{device_id}/alias")
async def update_device_alias(device_id: str, alias: str):
    if device_id not in db["devices"]:
        raise HTTPException(status_code=404, detail="设备未找到")
    db["devices"][device_id].alias = alias
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "别名更新成功"}

@app.get("/inspections/pending")
async def get_pending_actions():
    return [a for a in db["pending_actions"] if a["status"] == "pending"]

@app.post("/inspections/confirm/{action_id}")
async def confirm_action(action_id: str, approve: bool):
    action = next((a for a in db["pending_actions"] if a["id"] == action_id), None)
    if not action: raise HTTPException(status_code=404, detail="任务不存在")
    if not approve:
        action["status"] = "rejected"
        return {"message": "已忽略"}
    
    device_id = action.get("device_id") or action.get("host")
    if not device_id or device_id not in db["devices"]:
        raise HTTPException(status_code=404, detail="设备未找到")
    dev = db["devices"][device_id]
    ai_conf = db["ai"]
    
    # 查找关联的备份服务器
    backup_server_id = dev.backup_server_id
    backup_server = db["backup_servers"].get(backup_server_id) if backup_server_id else None
    
    if not backup_server:
        raise HTTPException(status_code=400, detail="该设备未关联备份服务器，请先在资产管理或备份中心配置")

    try:
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)
        version_tag = dev.os_version or await asyncio.to_thread(_detect_device_version, adapter, dev.brand) or await asyncio.to_thread(_detect_device_version_with_ai, adapter, analyzer, dev.brand)
        if version_tag and version_tag != dev.os_version:
            dev.os_version = version_tag
            await asyncio.to_thread(_save_persisted_state)
        
        # 1. 尝试备份 (AI 获取指令)
        backup_intent = f"备份当前运行配置到 {backup_server['protocol']} 服务器 {backup_server['server_ip']}，路径 {backup_server['path']}"
        if backup_server['username']:
            backup_intent += f"，用户名 {backup_server['username']}"
        
        backup_output = await collect_cli_output(adapter, analyzer, backup_intent, dev.brand, version_tag)
        
        if any(err in backup_output.lower() for err in ["error", "failed", "timeout", "unreachable", "refused"]):
            raise HTTPException(status_code=500, detail=f"备份失败，备份服务器可能不可用。输出：{backup_output[:100]}")

        # 2. 备份成功，生成恢复技能
        recovery_intent = f"从 {backup_server['protocol']} 服务器 {backup_server['server_ip']} 恢复配置，路径 {backup_server['path']}"
        await get_commands_with_skill_cache(analyzer, recovery_intent, dev.brand, version_tag)

        # 3. 执行封堵指令
        commands = await asyncio.to_thread(analyzer.generate_block_commands, [r["ip"] for r in action["risks"]], dev.brand)
        await asyncio.to_thread(adapter.execute_commands, commands, True)
        
        # 记录历史
        history_entry = {
            "id": action["id"],
            "time": datetime.datetime.now(),
            "commands": commands,
            "risks": action["risks"],
            "summary": action["summary"],
            "backup_info": backup_server
        }
        if device_id not in db["policy_history"]:
            db["policy_history"][device_id] = []
        db["policy_history"][device_id].append(history_entry)
        
        action["status"] = "completed"
        return {"message": "备份成功并策略已下发"}
    except HTTPException as he: raise he
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices/{device_id}/policies")
async def get_device_policy_history(device_id: str):
    return db["policy_history"].get(device_id, [])

@app.get("/logs/analyze/{device_id}")
async def analyze_device_logs(device_id: str):
    if not db["ai"] or device_id not in db["devices"]: raise HTTPException(status_code=400, detail="配置不完整")
    dev = db["devices"][device_id]
    ai_conf = db["ai"]
    try:
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)
        version_tag = dev.os_version or await asyncio.to_thread(_detect_device_version, adapter, dev.brand) or await asyncio.to_thread(_detect_device_version_with_ai, adapter, analyzer, dev.brand)
        if version_tag and version_tag != dev.os_version:
            dev.os_version = version_tag
            await asyncio.to_thread(_save_persisted_state)

        health_output = await collect_cli_output(adapter, analyzer, "查看设备的 CPU 使用率、内存使用率、运行温度", dev.brand, version_tag)
        health = adapter.parse_health_output(health_output)
        db["health_data"][device_id] = health
        
        raw_logs = await collect_cli_output(adapter, analyzer, "查看最近的被攻击日志或安全日志", dev.brand, version_tag, validation="logs")
        
        return await asyncio.to_thread(analyzer.analyze_logs, raw_logs, dev.brand)
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs/alarms/{device_id}")
async def analyze_device_alarms(device_id: str):
    if not db["ai"] or device_id not in db["devices"]:
        raise HTTPException(status_code=400, detail="配置不完整")
    dev = db["devices"][device_id]
    ai_conf = db["ai"]
    try:
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)
        version_tag = dev.os_version or await asyncio.to_thread(_detect_device_version, adapter, dev.brand) or await asyncio.to_thread(_detect_device_version_with_ai, adapter, analyzer, dev.brand)
        if version_tag and version_tag != dev.os_version:
            dev.os_version = version_tag
            await asyncio.to_thread(_save_persisted_state)

        raw_logs = await collect_cli_output(adapter, analyzer, "查看最近的系统告警、硬件告警、链路告警或事件日志", dev.brand, version_tag, validation="alarms")
        return await asyncio.to_thread(analyzer.analyze_alarms, raw_logs, dev.brand, device_version=version_tag)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/topology/generate")
async def generate_topology(
    scope: str = "enabled",
    debug: bool = False,
    use_ai: bool = False,
    version_timeout_s: int = 10,
    device_timeout_s: int = 18,
    llm_timeout_s: int = 25,
    concurrency: int = 4,
):
    request_id = uuid.uuid4().hex[:10]
    t0 = time.perf_counter()
    generated_at = datetime.datetime.now().isoformat()
    topology_logger.info("topology.generate start request_id=%s scope=%s debug=%s use_ai=%s", request_id, scope, debug, use_ai)
    analyzer = None
    if use_ai:
        if not db["ai"] or not getattr(db["ai"], "api_key", None):
            raise HTTPException(status_code=400, detail="AI 配置不完整（use_ai=true 时需要 api_key）")
        ai_conf = db["ai"]
        analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, ai_conf.base_url)

    scope_value = (scope or "enabled").strip().lower()
    if scope_value == "all":
        device_ids = list(db.get("devices", {}).keys())
    else:
        enabled_ids = db.get("settings", {}).get("enabled_devices", []) or []
        enabled_set = set(enabled_ids)
        if not enabled_set:
            device_ids = list(db.get("devices", {}).keys())
        else:
            device_ids = [
                device_id
                for device_id, dev in db.get("devices", {}).items()
                if (device_id in enabled_set) or (getattr(dev, "host", None) in enabled_set)
            ]

    if not device_ids:
        topology_logger.info("topology.generate empty request_id=%s", request_id)
        return {"nodes": [], "links": [], "summary": "未选择任何设备（请先接入资产或启用设备）"}

    version_timeout_s = max(1, min(120, int(version_timeout_s or 10)))
    device_timeout_s = max(1, min(300, int(device_timeout_s or 18)))
    llm_timeout_s = max(1, min(120, int(llm_timeout_s or 25)))
    concurrency = max(1, min(12, int(concurrency or 4)))
    sem = asyncio.Semaphore(concurrency)

    topology_logger.info(
        "topology.generate selected request_id=%s devices=%s concurrency=%s timeouts(version=%ss device=%ss llm=%ss)",
        request_id,
        len(device_ids),
        concurrency,
        version_timeout_s,
        device_timeout_s,
        llm_timeout_s,
    )

    async def _collect_one(device_id: str):
        dev = db["devices"][device_id]
        dev_ctx = f"{getattr(dev,'alias',None) or ''} {getattr(dev,'host',None)}:{getattr(dev,'port',None)} {getattr(dev,'protocol',None)} {getattr(dev,'brand',None)}".strip()
        device_t0 = time.perf_counter()
        topology_logger.info("topology.device start request_id=%s device_id=%s ctx=%s", request_id, device_id, dev_ctx)
        device_entry = {
            "device_id": device_id,
            "alias": dev.alias,
            "host": dev.host,
            "port": dev.port,
            "protocol": dev.protocol,
            "brand": dev.brand,
            "os_version": dev.os_version,
            "lldp_output": "",
            "error": None,
            "collected_at": datetime.datetime.now().isoformat(),
        }
        try:
            async with sem:
                topology_logger.info("topology.device acquired request_id=%s device_id=%s", request_id, device_id)
                adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
                version_tag = dev.os_version or None
                version_debug = None
                if not version_tag:
                    v_t0 = time.perf_counter()
                    topology_logger.info("topology.version start request_id=%s device_id=%s", request_id, device_id)
                    v, vdbg = await asyncio.wait_for(
                        detect_device_version_with_debug(adapter, analyzer, dev.brand),
                        timeout=version_timeout_s,
                    )
                    version_tag = v or None
                    version_debug = vdbg
                    topology_logger.info(
                        "topology.version done request_id=%s device_id=%s ok=%s tag=%s dt=%.2fs",
                        request_id,
                        device_id,
                        bool(version_tag),
                        version_tag,
                        time.perf_counter() - v_t0,
                    )
                    if debug and isinstance(version_debug, dict):
                        try:
                            attempts = version_debug.get("attempts") or []
                            used = version_debug.get("used_commands")
                            topology_logger.info(
                                "topology.version detail request_id=%s device_id=%s used=%s attempts=%s",
                                request_id,
                                device_id,
                                used,
                                len(attempts),
                            )
                        except Exception:
                            pass
                    if version_tag and version_tag != dev.os_version:
                        dev.os_version = version_tag
                        await asyncio.to_thread(_save_persisted_state)
                    device_entry["os_version"] = version_tag
                    if debug:
                        device_entry["version_debug"] = version_debug
                if debug:
                    l_t0 = time.perf_counter()
                    topology_logger.info("topology.lldp start request_id=%s device_id=%s tag=%s", request_id, device_id, version_tag)
                    raw, dbg = await asyncio.wait_for(
                        collect_topology_cli_output_with_debug(adapter, analyzer, dev.brand, version_tag),
                        timeout=device_timeout_s,
                    )
                    device_entry["lldp_output"] = _truncate_text(raw, 6000)
                    device_entry["debug"] = dbg
                    topology_logger.info(
                        "topology.lldp done request_id=%s device_id=%s ok=%s raw_len=%s dt=%.2fs",
                        request_id,
                        device_id,
                        bool((raw or "").strip()),
                        len(raw or ""),
                        time.perf_counter() - l_t0,
                    )
                    if isinstance(dbg, dict):
                        try:
                            topology_logger.info(
                                "topology.lldp detail request_id=%s device_id=%s used=%s attempts=%s",
                                request_id,
                                device_id,
                                dbg.get("used_commands"),
                                len(dbg.get("attempts") or []),
                            )
                            if debug:
                                for i, a in enumerate((dbg.get("attempts") or [])[:8]):
                                    topology_logger.info(
                                        "topology.lldp attempt request_id=%s device_id=%s idx=%s source=%s ok=%s cmds=%s err=%s",
                                        request_id,
                                        device_id,
                                        i,
                                        a.get("source"),
                                        a.get("ok"),
                                        a.get("commands"),
                                        a.get("error"),
                                    )
                        except Exception:
                            pass
                else:
                    l_t0 = time.perf_counter()
                    topology_logger.info("topology.lldp start request_id=%s device_id=%s tag=%s", request_id, device_id, version_tag)
                    raw, _ = await asyncio.wait_for(
                        collect_topology_cli_output_with_debug(adapter, analyzer, dev.brand, version_tag),
                        timeout=device_timeout_s,
                    )
                    device_entry["lldp_output"] = _truncate_text(raw, 6000)
                    topology_logger.info(
                        "topology.lldp done request_id=%s device_id=%s ok=%s raw_len=%s dt=%.2fs",
                        request_id,
                        device_id,
                        bool((raw or "").strip()),
                        len(raw or ""),
                        time.perf_counter() - l_t0,
                    )
        except asyncio.TimeoutError:
            device_entry["error"] = f"采集超时（>{device_timeout_s}s）"
            topology_logger.warning("topology.device timeout request_id=%s device_id=%s", request_id, device_id)
        except Exception as e:
            msg = str(e)[:360]
            device_entry["error"] = msg
            topology_logger.exception("topology.device error request_id=%s device_id=%s err=%s", request_id, device_id, msg)
            if debug:
                try:
                    parsed = json.loads(str(e))
                    if isinstance(parsed, dict) and parsed.get("attempts") is not None:
                        device_entry["debug"] = {"attempts": parsed.get("attempts")}
                except Exception:
                    pass
        topology_logger.info(
            "topology.device end request_id=%s device_id=%s ok=%s dt=%.2fs",
            request_id,
            device_id,
            (not device_entry.get("error")) and bool((device_entry.get("lldp_output") or "").strip()),
            time.perf_counter() - device_t0,
        )
        return device_entry

    collect_t0 = time.perf_counter()
    collected = await asyncio.gather(*[_collect_one(device_id) for device_id in device_ids])
    topology_logger.info("topology.collect done request_id=%s dt=%.2fs", request_id, time.perf_counter() - collect_t0)
    payload = [
        {
            "device_id": p.get("device_id"),
            "alias": p.get("alias"),
            "host": p.get("host"),
            "port": p.get("port"),
            "protocol": p.get("protocol"),
            "brand": p.get("brand"),
            "os_version": p.get("os_version"),
            "lldp_output": p.get("lldp_output"),
            "error": p.get("error"),
            "collected_at": p.get("collected_at"),
        }
        for p in collected
    ]

    base_result = _fallback_topology_from_payload(payload)
    if isinstance(base_result, dict):
        base_result["generated_at"] = generated_at
        base_result["request_id"] = request_id
    if debug:
        base_result["debug"] = {
            "devices": collected,
            "timeouts": {
                "version_timeout_s": version_timeout_s,
                "device_timeout_s": device_timeout_s,
                "llm_timeout_s": llm_timeout_s,
            },
            "concurrency": concurrency,
            "use_ai": use_ai,
        }
    if not use_ai:
        topology_logger.info("topology.generate end request_id=%s dt=%.2fs", request_id, time.perf_counter() - t0)
        return base_result

    brand_hint = ",".join(sorted({p.get("brand") for p in payload if p.get("brand")}))
    try:
        ai_conf = db.get("ai")
        base_url = getattr(ai_conf, "base_url", None) if ai_conf is not None else None
        preflight_timeout = min(1.0, float(llm_timeout_s or 1.0))
        if not _base_url_reachable(base_url, preflight_timeout):
            result = base_result
            if debug and isinstance(result, dict) and isinstance(result.get("debug"), dict):
                result["debug"]["ai_skipped"] = True
                result["debug"]["ai_base_url"] = base_url
            topology_logger.warning("topology.ai skipped request_id=%s base_url=%s", request_id, base_url)
            return result
        ai_t0 = time.perf_counter()
        topology_logger.info("topology.ai start request_id=%s brand_hint=%s", request_id, brand_hint)
        result = await asyncio.to_thread(analyzer.analyze_topology, payload, seed_brand_hint=brand_hint, timeout_s=llm_timeout_s)
        topology_logger.info(
            "topology.ai done request_id=%s nodes=%s links=%s dt=%.2fs",
            request_id,
            len((result or {}).get("nodes") or []),
            len((result or {}).get("links") or []),
            time.perf_counter() - ai_t0,
        )
        if debug and isinstance(result, dict):
            result["debug"] = {"devices": collected}
        topology_logger.info("topology.generate end request_id=%s dt=%.2fs", request_id, time.perf_counter() - t0)
        return result
    except Exception as e:
        result = base_result
        if debug and isinstance(result, dict) and isinstance(result.get("debug"), dict):
            result["debug"]["ai_error"] = str(e)[:240]
        topology_logger.warning("topology.ai fallback request_id=%s err=%s dt=%.2fs", request_id, str(e)[:240], time.perf_counter() - t0)
        return result

# --- AI Agent Chat 接口 ---

def _sanitize_devices_for_agent(device_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    allowed = set([str(x) for x in (device_ids or []) if str(x).strip()])
    items = []
    for device_id, dev in (db.get("devices", {}) or {}).items():
        if allowed and str(device_id) not in allowed:
            continue
        items.append(
            {
                "id": str(device_id),
                "alias": getattr(dev, "alias", None),
                "brand": getattr(dev, "brand", None),
                "host": getattr(dev, "host", None),
                "port": getattr(dev, "port", None),
                "protocol": getattr(dev, "protocol", None),
                "os_version": getattr(dev, "os_version", None),
            }
        )
    return items

def _looks_readonly_command(cmd: str) -> bool:
    c = (cmd or "").strip().lower()
    if not c:
        return True
    readonly_prefixes = (
        "show ",
        "display ",
        "get ",
        "diagnose ",
        "ping ",
        "traceroute ",
        "tracert ",
        "/system ",
    )
    if c.startswith(readonly_prefixes):
        return True
    readonly_exact = {
        "show",
        "display",
        "ping",
        "traceroute",
        "tracert",
        "display current-configuration",
        "display current",
        "display interface brief",
        "display ip interface brief",
    }
    if c in readonly_exact:
        return True
    return False

def _looks_dangerous_command(cmd: str) -> bool:
    c = (cmd or "").strip().lower()
    if not c:
        return False
    patterns = [
        r"\bformat\b",
        r"\bdelete\b",
        r"\berase\b",
        r"\breboot\b",
        r"\breload\b",
        r"\bshutdown\b",
        r"\bfactory\b",
        r"\bfactory\s+reset\b",
        r"\bwrite\s+erase\b",
        r"\breset\s+saved-configuration\b",
        r"\bclear\s+configuration\b",
        r"\berase\s+startup-config\b",
        r"\bdelete\s+/force\b",
    ]
    return any(re.search(p, c) for p in patterns)

def _agent_now_iso() -> str:
    return datetime.datetime.now().isoformat()

def _agent_trim_list(items: List[Any], keep: int) -> List[Any]:
    if keep <= 0:
        return []
    return items[-keep:] if len(items) > keep else items

def _agent_get_or_create_session(session_id: Optional[str], device_ids: Optional[List[str]], allow_config: bool) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    if not sid:
        sid = uuid.uuid4().hex[:12]
    sessions = db.setdefault("agent_sessions", {})
    s = sessions.get(sid)
    if not isinstance(s, dict):
        s = {
            "id": sid,
            "created_at": _agent_now_iso(),
            "updated_at": _agent_now_iso(),
            "device_ids": [str(x) for x in (device_ids or []) if str(x).strip()],
            "allow_config": bool(allow_config),
            "messages": [],
            "events": [],
            "memory": {"devices": {}, "notes": []},
        }
        sessions[sid] = s
    s["updated_at"] = _agent_now_iso()
    if device_ids is not None:
        s["device_ids"] = [str(x) for x in (device_ids or []) if str(x).strip()]
    s["allow_config"] = bool(allow_config)
    return s

def _agent_add_event(session: Dict[str, Any], event_type: str, detail: Dict[str, Any]):
    ev = {"ts": _agent_now_iso(), "type": event_type, **(detail or {})}
    session.setdefault("events", []).append(ev)
    session["events"] = _agent_trim_list(session.get("events") or [], 200)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(_save_persisted_state))
    except RuntimeError:
        _save_persisted_state()

def _agent_add_message(session: Dict[str, Any], role: str, content: str):
    msg = {"ts": _agent_now_iso(), "role": role, "content": (content or "")[:8000]}
    session.setdefault("messages", []).append(msg)
    session["messages"] = _agent_trim_list(session.get("messages") or [], 80)

def _agent_create_run_from_plan(session: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    run_id = uuid.uuid4().hex[:10]
    steps = []
    for i, s in enumerate(plan.get("plan") or []):
        steps.append(
            {
                "index": i,
                "text": str(s),
                "status": "pending",
                "started_at": None,
                "ended_at": None,
                "summary": "",
                "tool_log": [],
            }
        )
    run = {
        "id": run_id,
        "created_at": _agent_now_iso(),
        "updated_at": _agent_now_iso(),
        "intent": plan.get("intent"),
        "need_tools": bool(plan.get("need_tools")),
        "need_config": bool(plan.get("need_config")),
        "status": "planned",
        "steps": steps,
    }
    session.setdefault("runs", {})[run_id] = run
    session["active_run_id"] = run_id
    session["updated_at"] = _agent_now_iso()
    _agent_add_event(session, "run_created", {"run_id": run_id, "steps": len(steps)})
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(_save_persisted_state))
    except RuntimeError:
        _save_persisted_state()
    return run

def _agent_prefix_to_mask(prefix: int) -> Optional[str]:
    try:
        p = int(prefix)
    except Exception:
        return None
    if p < 0 or p > 32:
        return None
    mask = (0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF if p != 0 else 0
    return ".".join(str((mask >> (8 * i)) & 0xFF) for i in [3, 2, 1, 0])

def _agent_extract_ip_requirements(text: str) -> List[Dict[str, Optional[str]]]:
    t = (text or "").strip()
    if not t:
        return []
    found = []
    for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?\b", t):
        ip = m.group(1)
        prefix = m.group(2)
        try:
            octets = [int(x) for x in ip.split(".")]
        except Exception:
            continue
        if len(octets) != 4 or any(x < 0 or x > 255 for x in octets):
            continue
        mask = _agent_prefix_to_mask(int(prefix)) if prefix is not None else None
        found.append({"ip": ip, "mask": mask})
    uniq = []
    seen = set()
    for x in found:
        k = (x.get("ip") or "", x.get("mask") or "")
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq

def _agent_extract_iface_requirement(text: str) -> Optional[str]:
    t = (text or "")
    m = re.search(r"\b(GigabitEthernet\d+/\d+/\d+|GE\d+/\d+/\d+)\b", t, flags=re.IGNORECASE)
    return m.group(1) if m else None

def _agent_extract_vlan_ids(text: str) -> List[int]:
    t = (text or "")
    ids = []
    for m in re.finditer(r"(?i)\bvlan(?:if)?\s*(\d{1,4})\b", t):
        try:
            v = int(m.group(1))
        except Exception:
            continue
        if 1 <= v <= 4094:
            ids.append(v)
    seen = set()
    out = []
    for v in ids:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out

def _agent_validate_step_commands(step_text: str, commands: List[str]) -> Optional[str]:
    st = (step_text or "")
    cmd_text = "\n".join([str(x) for x in (commands or [])]).strip()
    if not st or not cmd_text:
        return None
    cmd_low = cmd_text.lower()
    st_low = st.lower()

    ips = _agent_extract_ip_requirements(st)
    if "ping" in st_low:
        for x in ips:
            ip = x.get("ip")
            if ip and ip.lower() not in cmd_low:
                return f"步骤要求的目标 IP 未出现在命令中：{ip}"
        return None

    for x in ips:
        ip = x.get("ip")
        mask = x.get("mask")
        if ip and ip.lower() not in cmd_low:
            return f"步骤要求的 IP 未出现在命令中：{ip}"
        if ip and mask:
            if f"ip address {ip} {mask}".lower() not in cmd_low:
                return f"步骤要求的 IP/掩码未按期望下发：ip address {ip} {mask}"

    iface = _agent_extract_iface_requirement(st)
    if iface and iface.lower() not in cmd_low:
        return f"步骤要求的接口未出现在命令中：{iface}"

    vlan_ids = _agent_extract_vlan_ids(st)
    for v in vlan_ids:
        if f"vlan {v}".lower() not in cmd_low and f"vlanif {v}".lower() not in cmd_low:
            return f"步骤要求的 VLAN/VLANIF 未出现在命令中：{v}"

    return None

def _agent_get_session_or_404(session_id: str) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id 不能为空")
    s = (db.get("agent_sessions", {}) or {}).get(sid)
    if not isinstance(s, dict):
        raise HTTPException(status_code=404, detail="session_id 不存在")
    return s

def _agent_get_run_or_404(session: Dict[str, Any], run_id: Optional[str]) -> Dict[str, Any]:
    rid = (run_id or session.get("active_run_id") or "").strip()
    runs = session.get("runs") or {}
    run = runs.get(rid)
    if not isinstance(run, dict):
        raise HTTPException(status_code=404, detail="run_id 不存在")
    return run

@app.post("/agent/run/step")
async def agent_run_step(req: AgentRunStepRequest):
    session = _agent_get_session_or_404(req.session_id)
    run = _agent_get_run_or_404(session, req.run_id)

    steps = run.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=400, detail="当前 run 没有可执行的步骤")

    idx = req.step_index
    if idx is None:
        idx = next((s.get("index") for s in steps if s.get("status") in ("pending", "failed")), None)
    if idx is None:
        run["status"] = "done"
        run["updated_at"] = _agent_now_iso()
        _agent_add_event(session, "run_done", {"run_id": run.get("id")})
        return {"session_id": session.get("id"), "run": run, "events": session.get("events") or []}

    if idx < 0 or idx >= len(steps):
        raise HTTPException(status_code=400, detail="step_index 越界")
    step = steps[idx]

    if req.action == "retry":
        step["status"] = "pending"
        step["summary"] = ""
        step["tool_log"] = []
        step["started_at"] = None
        step["ended_at"] = None

    if step.get("status") not in ("pending", "failed"):
        return {"session_id": session.get("id"), "run": run, "events": session.get("events") or []}

    step_t0 = time.perf_counter()
    step["status"] = "running"
    step["started_at"] = _agent_now_iso()
    run["status"] = "running"
    run["updated_at"] = _agent_now_iso()
    _agent_add_event(session, "step_start", {"run_id": run.get("id"), "step_index": idx, "text": step.get("text")})

    step_text = str(step.get("text") or "")
    ai_conf = db["ai"]
    analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, getattr(ai_conf, "base_url", None))

    device_ids = session.get("device_ids") or []
    allowed_devices = _sanitize_devices_for_agent(device_ids)
    allowed_ids = [d["id"] for d in allowed_devices]

    tools = [
        {
            "type": "function",
            "function": {"name": "list_devices", "description": "列出资产库设备", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        },
        {
            "type": "function",
            "function": {
                "name": "run_device_commands",
                "description": "在指定资产设备上执行命令并返回输出。allow_config=false 时只允许只读命令。",
                "parameters": {
                    "type": "object",
                    "properties": {"device_id": {"type": "string"}, "commands": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                    "required": ["device_id", "commands"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def _tool_list_devices():
        return {"devices": allowed_devices}

    async def _tool_run_device_commands(device_id: str, commands: List[str]):
        if str(device_id) not in set(allowed_ids):
            raise ValueError("DENY_DEVICE: device_id 不在允许列表中")
        if not bool(session.get("allow_config")):
            for c in commands:
                if not _looks_readonly_command(c):
                    raise ValueError("DENY_READONLY: 当前会话未开启配置下发（allow_config=false），仅允许只读命令")
        else:
            for c in commands:
                if _looks_dangerous_command(c):
                    raise ValueError("DENY_DANGEROUS: 检测到高风险命令，已拒绝执行")
            err = _agent_validate_step_commands(step_text, commands)
            if err:
                raise ValueError(f"PARAM_MISMATCH: {err}")

        dev = db["devices"].get(device_id)
        if dev is None:
            raise ValueError("NOT_FOUND: 设备不存在")
        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        out = await asyncio.to_thread(adapter.execute_commands, commands)
        return {"device_id": device_id, "commands": commands, "output": _truncate_text(out or "", 6000)}

    system_prompt = (
        "你是网络领域的执行代理。现在只执行一个步骤，不要输出多余内容。\n"
        "你可以调用工具获取设备信息/执行命令。\n"
        "输出要求：最终用中文给出本步骤的执行摘要（summary），并说明是否需要下一步。"
    )
    messages_for_model: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": json.dumps({"allowed_device_ids": allowed_ids, "allow_config": bool(session.get("allow_config"))}, ensure_ascii=False)},
        {"role": "user", "content": f"步骤：{step_text}"},
    ]

    tool_calls_log = []
    last_tool_ok: Optional[bool] = None
    last_tool_error: Optional[str] = None
    try:
        for _ in range(3):
            resp = analyzer.client.chat.completions.create(
                model=ai_conf.model,
                messages=messages_for_model,
                tools=tools,
                tool_choice="auto",
                timeout=35,
            )
            msg = resp.choices[0].message
            if getattr(msg, "tool_calls", None):
                assistant_payload: Dict[str, Any] = {"role": "assistant", "content": msg.content or "", "tool_calls": []}
                for tc in msg.tool_calls:
                    assistant_payload["tool_calls"].append({"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}})
                messages_for_model.append(assistant_payload)

                for tc in msg.tool_calls:
                    name = tc.function.name
                    args_raw = tc.function.arguments or "{}"
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    except Exception:
                        args = {}

                    t0 = time.perf_counter()
                    ok = True
                    result = None
                    err = None
                    try:
                        if name == "list_devices":
                            result = _tool_list_devices()
                        elif name == "run_device_commands":
                            result = await _tool_run_device_commands(device_id=args.get("device_id"), commands=args.get("commands") or [])
                        else:
                            raise ValueError("未知工具")
                    except Exception as e:
                        ok = False
                        err = str(e)[:300]
                        result = {"ok": False, "error": err}

                    tool_calls_log.append({"tool": name, "ok": ok, "dt_ms": int((time.perf_counter() - t0) * 1000), "error": err})
                    last_tool_ok = bool(ok)
                    last_tool_error = err
                    messages_for_model.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
                continue

            summary = msg.content or ""
            step_dt_ms = int((time.perf_counter() - step_t0) * 1000)
            if last_tool_ok is False:
                step["status"] = "failed"
                summary = f"步骤执行失败：{(last_tool_error or '未知错误')}"
                _agent_add_event(session, "step_failed", {"run_id": run.get("id"), "step_index": idx, "dt_ms": step_dt_ms, "error": (last_tool_error or "")[:240]})
            else:
                step["status"] = "done"
            step["ended_at"] = _agent_now_iso()
            step["summary"] = summary[:1200]
            step["tool_log"] = tool_calls_log
            run["updated_at"] = _agent_now_iso()
            if step["status"] == "done":
                _agent_add_event(session, "step_done", {"run_id": run.get("id"), "step_index": idx, "dt_ms": step_dt_ms})
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(asyncio.to_thread(_save_persisted_state))
            except RuntimeError:
                _save_persisted_state()
            return {"session_id": session.get("id"), "run": run, "events": session.get("events") or []}

        raise RuntimeError("步骤执行未能收敛")
    except Exception as e:
        step_dt_ms = int((time.perf_counter() - step_t0) * 1000) if "step_t0" in locals() else None
        step["status"] = "failed"
        step["ended_at"] = _agent_now_iso()
        step["summary"] = f"步骤执行失败：{str(e)[:240]}"
        step["tool_log"] = tool_calls_log
        run["updated_at"] = _agent_now_iso()
        payload = {"run_id": run.get("id"), "step_index": idx, "error": str(e)[:240]}
        if isinstance(step_dt_ms, int):
            payload["dt_ms"] = step_dt_ms
        _agent_add_event(session, "step_failed", payload)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(_save_persisted_state))
        except RuntimeError:
            _save_persisted_state()
        return {"session_id": session.get("id"), "run": run, "events": session.get("events") or []}

@app.post("/agent/chat")
async def agent_chat(req: AgentChatRequest):
    if not db.get("ai") or not getattr(db["ai"], "api_key", None):
        raise HTTPException(status_code=400, detail="AI 配置不完整，请先在 AI 配置页填写 api_key/model/base_url")

    ai_conf = db["ai"]
    analyzer = AIAnalyzer(ai_conf.api_key, ai_conf.model, getattr(ai_conf, "base_url", None))

    session = _agent_get_or_create_session(req.session_id, req.device_ids, bool(req.allow_config))
    session_id = session.get("id")

    allowed_devices = _sanitize_devices_for_agent(req.device_ids)
    allowed_ids = [d["id"] for d in allowed_devices]

    latest_user_text = ""
    for m in reversed(req.messages or []):
        if (m.role or "").strip().lower() == "user":
            latest_user_text = m.content or ""
            break
    if latest_user_text.strip():
        _agent_add_message(session, "user", latest_user_text)
        _agent_add_event(session, "user", {"text": latest_user_text[:400]})

    system_prompt = (
        "你是一个只服务于网络领域的 AI 助手（网络工程师/自动化运维助手）。\n"
        "你的职责：根据用户的自然语言需求，给出网络配置建议、排障步骤、变更方案、以及可执行的设备命令。\n"
        "强约束：\n"
        "1) 仅回答网络/设备/拓扑/协议/安全策略/运维自动化相关内容；其他领域请求必须拒绝。\n"
        "2) 你只能对“资产库设备”提出操作建议；如果需要执行命令，必须调用工具，并且 device_id 必须来自允许列表。\n"
        "3) 默认以最安全方式处理：如果 allow_config=false，则只能执行只读命令（show/display/get/ping/traceroute 等）。\n"
        "4) 当某个意图对应的一组命令在某台设备上成功执行且输出有效时，调用 save_skill 将该意图-命令沉淀为技能，以便后续自动复用。\n"
        "5) 严禁擅自改写用户给定的参数（设备ID/接口名/VLAN号/IP地址/掩码/前缀长度）；必须原样使用。\n"
        "输出要求：中文，结构清晰；需要执行时先给计划，再执行；执行结果要摘要，必要时附关键输出片段。\n"
    )

    base_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    base_messages.append(
        {
            "role": "system",
            "content": json.dumps(
                {
                    "session_id": session_id,
                    "allow_config": bool(req.allow_config),
                    "allowed_device_ids": allowed_ids,
                    "devices": allowed_devices,
                    "memory": session.get("memory") or {},
                },
                ensure_ascii=False,
            ),
        }
    )

    user_messages = []
    for m in (session.get("messages") or []):
        role = (m.get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        user_messages.append({"role": role, "content": m.get("content") or ""})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_devices",
                "description": "列出资产库中的设备（仅包含非敏感字段）。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_skills",
                "description": "列出当前已沉淀的 Skill，可按品牌和意图关键字过滤，便于复用已有命令模板。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "brand": {"type": "string"},
                        "intent_contains": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_device_commands",
                "description": "在指定资产设备上执行命令并返回输出。allow_config=false 时只允许只读命令。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string"},
                        "commands": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["device_id", "commands"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_skill",
                "description": "保存/更新一条 Skill（意图->命令），用于后续自动复用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "brand": {"type": "string"},
                        "device_version": {"type": "string"},
                        "intent": {"type": "string"},
                        "commands": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "description": {"type": "string"},
                        "source": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "prerequisites": {"type": "string"},
                        "validation": {"type": "string"},
                        "sample_output": {"type": "string"},
                        "verified": {"type": "boolean"},
                    },
                    "required": ["brand", "intent", "commands"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    tool_log: List[Dict[str, Any]] = []
    created_skill_ids: List[str] = []

    def _tool_list_devices():
        return {"devices": allowed_devices}

    def _tool_list_skills(brand: Optional[str] = None, intent_contains: Optional[str] = None):
        items = db.get("skills", []) or []
        b = (brand or "").strip()
        kw = (intent_contains or "").strip().lower()
        if b:
            items = [s for s in items if (s.get("brand") or "").strip().lower() == b.lower()]
        if kw:
            items = [s for s in items if kw in ((s.get("intent") or "").lower())]
        return {"skills": items[:50]}

    async def _tool_run_device_commands(device_id: str, commands: List[str]):
        if str(device_id) not in set(allowed_ids):
            raise ValueError("DENY_DEVICE: device_id 不在允许列表中")
        if not req.allow_config:
            for c in commands:
                if not _looks_readonly_command(c):
                    raise ValueError("DENY_READONLY: 当前会话未开启配置下发（allow_config=false），仅允许只读命令")
        else:
            for c in commands:
                if _looks_dangerous_command(c):
                    raise ValueError("DENY_DANGEROUS: 检测到高风险命令，已拒绝执行")

        dev = db["devices"].get(device_id)
        if dev is None:
            raise ValueError("NOT_FOUND: 设备不存在")

        adapter = FirewallAdapter(dev.brand, dev.host, dev.username, dev.password, dev.port, dev.secret, dev.protocol)
        cmds_safe = [str(x) for x in (commands or [])][:20]
        _agent_add_event(session, "tool_start", {"tool": "run_device_commands", "device_id": device_id, "commands": cmds_safe})
        t0 = time.perf_counter()
        try:
            output = await asyncio.to_thread(adapter.execute_commands, commands)
            _agent_add_event(
                session,
                "tool_end",
                {"tool": "run_device_commands", "device_id": device_id, "ok": True, "dt_ms": int((time.perf_counter() - t0) * 1000)},
            )
        except Exception as e:
            _agent_add_event(
                session,
                "tool_end",
                {
                    "tool": "run_device_commands",
                    "device_id": device_id,
                    "ok": False,
                    "dt_ms": int((time.perf_counter() - t0) * 1000),
                    "error": str(e)[:240],
                },
            )
            raise
        return {
            "device_id": device_id,
            "brand": dev.brand,
            "device_version": getattr(dev, "os_version", None),
            "commands": commands,
            "output": _truncate_text(output or "", 8000),
        }

    def _tool_save_skill(
        brand: str,
        intent: str,
        commands: List[str],
        device_version: Optional[str] = None,
        description: str = "",
        source: str = "ai",
        tags: Optional[List[str]] = None,
        prerequisites: Optional[str] = None,
        validation: Optional[str] = None,
        sample_output: Optional[str] = None,
        verified: bool = False,
    ):
        _upsert_skill(
            intent=intent,
            brand=brand,
            device_version=device_version,
            commands=commands,
            description=description or "",
            source=source or "ai",
            tags=tags,
            prerequisites=prerequisites,
            validation=validation,
            sample_output=_truncate_text(sample_output, 360) if sample_output else None,
            verified=bool(verified),
        )
        existing = _find_skill(intent=intent, brand=brand, device_version=device_version)
        skill_id = existing.get("id") if isinstance(existing, dict) else None
        if skill_id:
            created_skill_ids.append(str(skill_id))
        _agent_add_event(session, "skill_saved", {"skill_id": skill_id, "brand": brand, "intent": intent})
        return {"ok": True, "skill_id": skill_id}

    messages_for_model: List[Dict[str, Any]] = base_messages + user_messages

    plan = None
    try:
        plan_resp = analyzer.client.chat.completions.create(
            model=ai_conf.model,
            messages=messages_for_model
            + [
                {
                    "role": "system",
                    "content": "先输出一个可执行的计划（plan），不要执行工具。必须输出 JSON："
                    '{"intent":"...","need_tools":true,"need_config":false,"plan":["步骤1","步骤2"],"suggested_device_ids":["..."],"notes":["..."]}',
                }
            ],
            response_format={"type": "json_object"},
            timeout=25,
        )
        plan_raw = plan_resp.choices[0].message.content or "{}"
        plan = json.loads(plan_raw) if isinstance(plan_raw, str) else plan_raw
    except Exception as e:
        tool_log.append({"tool": "plan", "ok": False, "dt_ms": 0, "args": {}, "error": str(e)[:240]})
        plan = None

    run = None
    if isinstance(plan, dict):
        _agent_add_event(session, "plan", {"intent": plan.get("intent"), "need_tools": bool(plan.get("need_tools")), "need_config": bool(plan.get("need_config")), "plan": _agent_trim_list([str(x) for x in (plan.get("plan") or [])], 20)})
        run = _agent_create_run_from_plan(session, plan)
        if bool(plan.get("need_config")) and not bool(req.allow_config):
            msg = "该需求涉及配置变更。当前会话未开启“允许配置下发”，我先给出计划与建议；如需执行，请在前端打开“允许配置下发”后再发送“继续执行”。"
            _agent_add_message(session, "assistant", msg)
            _agent_add_event(session, "assistant", {"text": msg[:400]})
            return {"session_id": session_id, "run": run, "plan": plan, "events": session.get("events") or [], "message": msg, "tool_log": tool_log, "skills_saved": created_skill_ids}

        if not bool(req.auto_execute):
            msg = "计划已生成。你可以点击“执行下一步”按步骤运行；需要我自动一步到位也可以打开“自动执行”。"
            _agent_add_message(session, "assistant", msg)
            _agent_add_event(session, "assistant", {"text": msg[:400]})
            return {"session_id": session_id, "run": run, "plan": plan, "events": session.get("events") or [], "message": msg, "tool_log": tool_log, "skills_saved": created_skill_ids}

    for _ in range(3):
        try:
            resp = analyzer.client.chat.completions.create(
                model=ai_conf.model,
                messages=messages_for_model,
                tools=tools,
                tool_choice="auto",
                timeout=35,
            )
        except Exception as e:
            tool_log.append(
                {
                    "tool": "llm",
                    "ok": False,
                    "dt_ms": 0,
                    "args": {"tools_enabled": True},
                    "error": str(e)[:300],
                }
            )
            resp = analyzer.client.chat.completions.create(
                model=ai_conf.model,
                messages=messages_for_model,
                timeout=35,
            )
        msg = resp.choices[0].message
        if getattr(msg, "tool_calls", None):
            assistant_payload: Dict[str, Any] = {"role": "assistant", "content": msg.content or "", "tool_calls": []}
            for tc in msg.tool_calls:
                assistant_payload["tool_calls"].append(
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                )
            messages_for_model.append(assistant_payload)

            for tc in msg.tool_calls:
                name = tc.function.name
                args_raw = tc.function.arguments or "{}"
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                except Exception:
                    args = {}

                t0 = time.perf_counter()
                ok = True
                result: Any = None
                err: Optional[str] = None
                try:
                    if name == "list_devices":
                        result = _tool_list_devices()
                    elif name == "list_skills":
                        result = _tool_list_skills(
                            brand=args.get("brand"),
                            intent_contains=args.get("intent_contains"),
                        )
                    elif name == "run_device_commands":
                        result = await _tool_run_device_commands(device_id=args.get("device_id"), commands=args.get("commands") or [])
                    elif name == "save_skill":
                        result = _tool_save_skill(
                            brand=args.get("brand"),
                            device_version=args.get("device_version"),
                            intent=args.get("intent"),
                            commands=args.get("commands") or [],
                            description=args.get("description") or "",
                            source=args.get("source") or "ai",
                            tags=args.get("tags"),
                            prerequisites=args.get("prerequisites"),
                            validation=args.get("validation"),
                            sample_output=args.get("sample_output"),
                            verified=bool(args.get("verified") or False),
                        )
                    else:
                        raise ValueError("未知工具")
                except Exception as e:
                    ok = False
                    err = str(e)[:300]
                    result = {"ok": False, "error": err}

                tool_log.append(
                    {
                        "tool": name,
                        "ok": ok,
                        "dt_ms": int((time.perf_counter() - t0) * 1000),
                        "args": args,
                        "error": err,
                    }
                )

                messages_for_model.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        final_text = msg.content or ""
        if isinstance(run, dict) and isinstance(run.get("steps"), list):
            for s in run["steps"]:
                if s.get("status") == "pending":
                    s["status"] = "done"
                    s["started_at"] = s.get("started_at") or _agent_now_iso()
                    s["ended_at"] = _agent_now_iso()
                    s["summary"] = "自动执行模式：步骤合并执行完成"
            run["status"] = "done"
            run["updated_at"] = _agent_now_iso()
        _agent_add_message(session, "assistant", final_text)
        _agent_add_event(session, "assistant", {"text": final_text[:400]})
        return {"session_id": session_id, "run": run, "plan": plan, "events": session.get("events") or [], "message": final_text, "tool_log": tool_log, "skills_saved": created_skill_ids}

    msg = "AI 工具调用循环未能收敛，我已停止继续自动调用工具。建议：缩小设备范围（选择单台设备）、把需求拆成更小的步骤，或关闭自动执行改为逐步执行。"
    if isinstance(run, dict):
        run["status"] = "failed"
        run["updated_at"] = _agent_now_iso()
        steps = run.get("steps")
        if isinstance(steps, list):
            for s in steps:
                if s.get("status") == "pending":
                    s["status"] = "skipped"
                    s["summary"] = "由于工具调用未收敛，本步骤未自动执行"
                    s["ended_at"] = _agent_now_iso()
    _agent_add_message(session, "assistant", msg)
    _agent_add_event(session, "llm_not_converged", {"run_id": run.get("id") if isinstance(run, dict) else None})
    return {"session_id": session_id, "run": run, "plan": plan, "events": session.get("events") or [], "message": msg, "tool_log": tool_log, "skills_saved": created_skill_ids}

# --- Skill Hub 接口 ---

@app.get("/skills")
async def list_skills():
    return db["skills"]

@app.post("/skills")
async def add_custom_skill(skill: SkillEntry):
    db["skills"].append(skill.dict())
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "技能已存入库"}

@app.delete("/skills/{skill_id}")
async def remove_skill(skill_id: str):
    db["skills"] = [s for s in db["skills"] if s["id"] != skill_id]
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "技能已移除"}

@app.post("/config/ai")
async def set_ai_config(config: AIConfig):
    db["ai"] = config
    await asyncio.to_thread(_save_persisted_state)
    return {"message": "配置已保存"}

@app.get("/config/ai")
async def get_ai_config():
    return db["ai"]

def _trigger_backend_reload():
    Path(__file__).touch()

@app.post("/admin/restart")
async def restart_backend(request: Request, background_tasks: BackgroundTasks):
    client_host = request.client.host if request.client else ""
    origin = (request.headers.get("origin") or "").lower()
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅允许本机调用")
    if not origin.startswith(("http://localhost:5175", "http://127.0.0.1:5175", "http://localhost", "http://127.0.0.1")):
        raise HTTPException(status_code=403, detail="来源不允许")
    background_tasks.add_task(_trigger_backend_reload)
    return {"message": "已触发后端重载（需以 --reload 方式启动 uvicorn 才会自动重载）"}
