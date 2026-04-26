import openai
import json

class AIAnalyzer:
    def __init__(self, api_key, model="gpt-4", base_url=None):
        self.api_key = api_key
        self.model = model
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

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
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"日志内容：\n{log_content}"}
            ],
            response_format={ "type": "json_object" },
            timeout=timeout_s,
        )
        
        return json.loads(response.choices[0].message.content)

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

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"日志内容：\n{log_content}"}
            ],
            response_format={ "type": "json_object" },
            timeout=timeout_s,
        )

        return json.loads(response.choices[0].message.content)

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
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={ "type": "json_object" },
            timeout=timeout_s,
        )
        return json.loads(response.choices[0].message.content)

    def generate_block_commands(self, ips, brand):
        """根据 IP 和品牌生成封堵命令"""
        system_prompt = f"""
        你是一个网络配置助手。请为 {brand} 防火墙生成封堵以下 IP 的命令。
        只需输出命令列表，每行一条。不要包含任何解释性文字或 Markdown 格式。
        """
        
        ip_list = ", ".join(ips)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"需要封堵的 IP: {ip_list}"}
            ]
        )
        
        # 将输出按行分割成列表
        commands = [line.strip() for line in response.choices[0].message.content.split('\n') if line.strip()]
        return commands

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
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"意图：{intent}"}
            ]
        )
        
        content = response.choices[0].message.content.strip()
        # 移除可能的 markdown 块
        content = content.replace("```", "").replace("```bash", "").strip()
        return [line.strip() for line in content.split('\n') if line.strip()]

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

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            timeout=timeout_s,
        )

        return json.loads(response.choices[0].message.content)
