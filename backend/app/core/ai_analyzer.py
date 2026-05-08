import openai
import json
import re
from typing import Any, Dict, List, Optional, Callable

import httpx

class AIAnalyzer:
    def __init__(self, api_key, model="gpt-4", base_url=None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _should_use_raw_http(self) -> bool:
        bu = (self.base_url or "").strip().lower()
        m = (self.model or "").strip().lower()
        if "api.deepseek.com" in bu:
            return True
        if m.startswith("deepseek-"):
            return True
        return False

    def _raw_chat_completions_create(self, payload: Dict[str, Any], timeout_s: Optional[float]) -> Dict[str, Any]:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        url = base + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=float(timeout_s or 35)) as client:
            r = client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                try:
                    raise RuntimeError(f"Error code: {r.status_code} - {r.json()}")
                except Exception:
                    raise RuntimeError(f"Error code: {r.status_code} - {r.text[:800]}")
            return r.json()

    def _chat_create(self, *, messages: List[Dict[str, Any]], response_format: Optional[Dict[str, Any]] = None, timeout_s: Optional[float] = None) -> Any:
        if self._should_use_raw_http():
            payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
            if response_format is not None:
                payload["response_format"] = response_format
            return self._raw_chat_completions_create(payload=payload, timeout_s=timeout_s)
        kwargs: Dict[str, Any] = {"model": self.model, "messages": messages, "timeout": timeout_s}
        if response_format is not None:
            kwargs["response_format"] = response_format
        return self.client.chat.completions.create(**kwargs)

    def _extract_content(self, resp: Any) -> str:
        try:
            if isinstance(resp, dict):
                return (((resp.get("choices") or [])[0] or {}).get("message") or {}).get("content") or ""
            return resp.choices[0].message.content or ""
        except Exception:
            return ""

    def _strip_dsml(self, text: str) -> str:
        t = text or ""
        if "<｜DSML｜" not in t:
            return t.strip()
        t = re.sub(r"<｜DSML｜[\s\S]*?>", "", t)
        t = re.sub(r"</｜DSML｜[\s\S]*?>", "", t)
        return t.strip()

    def _json_with_retry(
        self,
        *,
        base_messages: List[Dict[str, Any]],
        validator: Callable[[Any], Optional[str]],
        timeout_s: Optional[float],
        max_attempts: int = 4,
    ) -> Dict[str, Any]:
        last_err = ""
        last_raw = ""
        for _ in range(max(1, int(max_attempts))):
            messages = list(base_messages)
            if last_err:
                messages.append(
                    {
                        "role": "system",
                        "content": f"上一次输出不符合要求：{last_err}。请严格输出 JSON 对象，不要包含任何多余文字。",
                    }
                )
                if last_raw.strip():
                    messages.append(
                        {
                            "role": "system",
                            "content": f"上一次输出原文片段（供你纠错）：{last_raw[:600]}",
                        }
                    )
            resp = self._chat_create(messages=messages, response_format={"type": "json_object"}, timeout_s=timeout_s)
            raw = self._strip_dsml(self._extract_content(resp))
            last_raw = raw
            try:
                obj = json.loads(raw or "{}")
            except Exception as e:
                last_err = f"JSON 解析失败：{str(e)[:180]}"
                continue
            err = validator(obj)
            if err:
                last_err = err[:220]
                continue
            return obj
        raise RuntimeError(last_err or "LLM 输出未通过校验")

    def _lines_with_retry(
        self,
        *,
        base_messages: List[Dict[str, Any]],
        validator: Callable[[List[str], str], Optional[str]],
        timeout_s: Optional[float],
        max_attempts: int = 4,
    ) -> List[str]:
        last_err = ""
        last_raw = ""
        for _ in range(max(1, int(max_attempts))):
            messages = list(base_messages)
            if last_err:
                messages.append(
                    {
                        "role": "system",
                        "content": f"上一次输出不符合要求：{last_err}。现在只输出命令本身，每行一条，不要解释。",
                    }
                )
                if last_raw.strip():
                    messages.append({"role": "system", "content": f"上一次输出原文片段（供你纠错）：{last_raw[:600]}"})
            resp = self._chat_create(messages=messages, timeout_s=timeout_s)
            raw = self._strip_dsml(self._extract_content(resp))
            raw = raw.replace("```bash", "").replace("```", "").strip()
            last_raw = raw
            lines = []
            for line in (raw or "").splitlines():
                s = line.strip()
                if not s:
                    continue
                s = re.sub(r"^\s*[\-\*\d]+[.)]\s*", "", s).strip()
                if not s:
                    continue
                if any(ch in s for ch in ("：", "，")) and (" " not in s):
                    continue
                lines.append(s)
            err = validator(lines, raw)
            if err:
                last_err = err[:220]
                continue
            return lines
        raise RuntimeError(last_err or "LLM 输出未通过校验")

    def analyze_logs(self, log_content, brand, timeout_s=None):
        """分析日志并生成风险报告"""
        system_prompt = f"""
        你是一个资深的防火墙安全专家。我会给你一段 {brand} 防火墙的日志。
        请你：
        1. 识别出其中的攻击行为（如暴力破解、扫描、拒绝服务等）。
        2. 提取攻击源 IP 地址。
        3. 给出风险等级（高、中、低）。
        4. 必须以 JSON 格式输出，格式如下：
        {{
            "risks": [
                {{"ip": "1.2.3.4", "type": "暴力破解", "level": "高", "reason": "发现大量 SSH 登录失败记录"}}
            ],
            "summary": "简短的总结报告"
        }}
        """

        def _validate(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return "输出不是 JSON 对象"
            if not isinstance(obj.get("risks"), list):
                return "risks 必须是数组"
            if not isinstance(obj.get("summary"), str):
                return "summary 必须是字符串"
            for r in (obj.get("risks") or [])[:20]:
                if not isinstance(r, dict):
                    return "risks 项必须是对象"
                for k in ("ip", "type", "level", "reason"):
                    v = r.get(k)
                    if not isinstance(v, str) or not v.strip():
                        return f"risks 项缺少或无效字段：{k}"
            return None

        return self._json_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"日志内容：\n{log_content}"}],
            validator=_validate,
            timeout_s=timeout_s,
        )

    def analyze_alarms(self, log_content, brand, device_version=None, timeout_s=None):
        version_text = (device_version or "").strip() or "未知"
        system_prompt = f"""
        你是一个资深的网络运维告警分析专家，擅长分析交换机/路由器/防火墙的系统日志与告警日志。
        目标设备品牌：{brand}
        目标设备版本信息：{version_text}

        我会给你一段设备日志，请你：
        1. 识别告警/事件（如接口 up/down、链路抖动、邻居会话 flap、STP 变化、CPU/内存/温度过高、风扇/电源异常、ACL/IPS/DoS 类事件等）。
        2. 提取关键对象（如接口/槽位/模块/邻居IP/进程名等），必要时从日志中推断。
        3. 给出告警等级（高/中/低）。
        4. 输出处理建议（只读建议，不要输出下发命令）。
        5. 必须以 JSON 格式输出，格式如下：
        {{
            "alarms": [
                {{"time": "2026-01-01 12:00:00", "type": "接口Down", "level": "高", "target": "GE0/0/1", "reason": "接口链路Down", "suggestion": "检查物理链路/对端端口/光模块"}}
            ],
            "summary": "简短总结"
        }}
        """

        def _validate(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return "输出不是 JSON 对象"
            if not isinstance(obj.get("alarms"), list):
                return "alarms 必须是数组"
            if not isinstance(obj.get("summary"), str):
                return "summary 必须是字符串"
            for a in (obj.get("alarms") or [])[:30]:
                if not isinstance(a, dict):
                    return "alarms 项必须是对象"
                for k in ("time", "type", "level", "target", "reason", "suggestion"):
                    v = a.get(k)
                    if not isinstance(v, str) or not v.strip():
                        return f"alarms 项缺少或无效字段：{k}"
            return None

        return self._json_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"日志内容：\n{log_content}"}],
            validator=_validate,
            timeout_s=timeout_s,
        )

    def analyze_topology(self, lldp_payload, seed_brand_hint=None, timeout_s=None):
        system_prompt = f"""
        你是一个资深网络工程师与网络拓扑建模专家。
        我会给你一组来自不同网络设备的 LLDP 邻居信息输出（可能包含不同厂商、不同格式、以及少量无效/报错输出）。
        请你从中提取拓扑关系，输出一个可视化友好的拓扑 JSON。

        要求：
        1. 识别每台设备自身标识（优先用 payload 里的 device_id/alias/host），并尽量提取邻居设备标识（system name / chassis id / mgmt ip 等）。
        2. 生成链路（links），每条链路至少包含 source/target；尽量补全 local_port/remote_port；标注 protocol="lldp"。
        3. 去重：同一对设备的同一对端口只保留一条链路；如果两侧都上报，合并为一条。
        4. 允许出现“未知邻居”：如果邻居不在资产库，也要作为一个节点输出。
        5. 输出格式必须为 JSON，格式如下：
        {{
          "nodes": [{{"id": "node-id", "label": "显示名称", "brand": "品牌可选", "host": "可选", "device_id": "可选"}}],
          "links": [{{"source": "node-id", "target": "node-id", "local_port": "可选", "remote_port": "可选", "protocol": "lldp"}}],
          "summary": "简短总结（节点数、链路数、异常提示）"
        }}
        """

        user_content = json.dumps({"seed_brand_hint": seed_brand_hint, "devices": lldp_payload}, ensure_ascii=False)
        def _validate(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return "输出不是 JSON 对象"
            if not isinstance(obj.get("nodes"), list):
                return "nodes 必须是数组"
            if not isinstance(obj.get("links"), list):
                return "links 必须是数组"
            if not isinstance(obj.get("summary"), str):
                return "summary 必须是字符串"
            for n in (obj.get("nodes") or [])[:80]:
                if not isinstance(n, dict):
                    return "nodes 项必须是对象"
                if not isinstance(n.get("id"), str) or not n.get("id").strip():
                    return "nodes.id 必须是字符串"
                if not isinstance(n.get("label"), str) or not n.get("label").strip():
                    return "nodes.label 必须是字符串"
            for l in (obj.get("links") or [])[:120]:
                if not isinstance(l, dict):
                    return "links 项必须是对象"
                if not isinstance(l.get("source"), str) or not l.get("source").strip():
                    return "links.source 必须是字符串"
                if not isinstance(l.get("target"), str) or not l.get("target").strip():
                    return "links.target 必须是字符串"
            return None

        return self._json_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            validator=_validate,
            timeout_s=timeout_s,
        )

    def generate_block_commands(self, ips, brand):
        """根据 IP 和品牌生成封堵命令"""
        system_prompt = f"""
        你是一个网络配置助手。请为 {brand} 防火墙生成封堵以下 IP 的命令。
        只需输出命令列表，每行一条。不要包含任何解释性文字或 Markdown 格式。
        """

        def _validate(lines: List[str], raw: str) -> Optional[str]:
            if not lines:
                return "没有输出任何命令"
            if "```" in (raw or ""):
                return "包含 Markdown 代码块"
            bad = ("解释", "说明", "如下", "命令", "建议", "json", "{", "}")
            if any(x in (raw or "") for x in bad):
                return "包含解释性文字"
            return None

        ip_list = ", ".join([str(x).strip() for x in (ips or []) if str(x).strip()])
        return self._lines_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"需要封堵的 IP: {ip_list}"}],
            validator=_validate,
            timeout_s=None,
        )

    def generate_commands_by_intent(self, intent, brand, device_version=None):
        """根据用户的意图（如：获取 CPU、内存、日志等）和设备品牌生成对应的 CLI 命令"""
        version_text = (device_version or "").strip() or "未知"
        system_prompt = f"""
        你是一个精通各类防火墙 CLI 操作的专家。
        目标设备品牌：{brand}
        目标设备版本信息：{version_text}
        
        请根据用户的“意图”给出最准确的 CLI 命令。
        规则：
        1. 只输出命令本身，不要包含任何 Markdown 代码块标签、解释、前导符（如 # 或 >）。
        2. 如果需要多个命令才能完成意图，请每行输出一个命令。
        3. 确保命令是只读的（巡检类）或配置类的，取决于意图。
        4. 如果不同版本命令存在差异，请优先生成适配该版本的命令。
        """

        def _validate(lines: List[str], raw: str) -> Optional[str]:
            if not lines:
                return "没有输出任何命令"
            if "```" in (raw or ""):
                return "包含 Markdown 代码块"
            if any(x in (raw or "") for x in ("解释", "说明", "原因", "如下", "建议", "这里是", "输出")):
                return "包含解释性文字"
            return None

        return self._lines_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"意图：{intent}"}],
            validator=_validate,
            timeout_s=None,
        )

    def generate_backup_command_templates(self, brand, device_version=None, protocol="tftp", timeout_s=None):
        version_text = (device_version or "").strip() or "未知"
        p = (protocol or "").strip().lower() or "tftp"
        system_prompt = f"""
        你是一个精通各类网络设备/防火墙 CLI 的专家。
        目标设备品牌：{brand}
        目标设备版本信息：{version_text}
        目标传输协议：{p}

        任务：生成“备份当前运行配置到备份服务器”的命令模板（可用于定期自动备份）。

        强制要求：
        1) 输出必须为 JSON（json_object），只能包含 keys: commands, prerequisites, tags
        2) commands 必须是字符串数组（1-6 条），每条是单行 CLI 命令，不要包含解释文字
        3) 命令必须尽量做到非交互式（不要依赖输入确认/密码提示/文件名提示）
        4) 不要写死真实 IP/用户名/密码/路径，必须使用占位符：
           - {{server_ip}} 备份服务器IP
           - {{remote_path}} 备份文件远端路径（包含文件名）
           - {{filename}} 备份文件名
           - {{backup_url}} 完整 URL（适用于 ftp/sftp，可能包含账号密码）
        5) 若需要先保存当前配置，请包含必要的保存命令（同样要求非交互式或默认确认）
        6) tags 必须包含 \"backup\" 和协议名（例如 \"tftp\"）
        """

        user_prompt = "请给出可执行的命令模板。"

        def _validate(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return "输出不是 JSON 对象"
            if set(obj.keys()) - {"commands", "prerequisites", "tags"}:
                return "只能包含 keys: commands, prerequisites, tags"
            cmds = obj.get("commands")
            if not isinstance(cmds, list) or not (1 <= len(cmds) <= 6):
                return "commands 必须是 1-6 条的数组"
            for c in cmds:
                if not isinstance(c, str) or not c.strip():
                    return "commands 每条必须是非空字符串"
                if "\n" in c:
                    return "commands 每条必须是单行命令"
            pre = obj.get("prerequisites")
            if pre is not None and not isinstance(pre, list):
                return "prerequisites 必须是数组"
            if isinstance(pre, list):
                for x in pre:
                    if not isinstance(x, str):
                        return "prerequisites 只能包含字符串"
            tags = obj.get("tags")
            if tags is not None and not isinstance(tags, list):
                return "tags 必须是数组"
            if isinstance(tags, list):
                low = [str(x).strip().lower() for x in tags if str(x).strip()]
                if "backup" not in low:
                    return "tags 必须包含 backup"
                if p not in low:
                    return f"tags 必须包含协议名：{p}"
            return None

        return self._json_with_retry(
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            validator=_validate,
            timeout_s=timeout_s,
        )
