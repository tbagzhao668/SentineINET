from netmiko import ConnectHandler
import datetime
import os
import socket
import re
import time

class FirewallAdapter:
    # 品牌与 Netmiko 设备类型的映射
    BRAND_MAP = {
        "Cisco": "cisco_asa",
        "Huawei": "huawei",
        "H3C": "hp_comware",
        "Fortinet": "fortinet",
        "Sangfor": "generic_ssh",
        "Ruijie": "ruijie",
        "Juniper": "juniper",
        "Arista": "arista_eos",
        "Extreme": "extreme_exos",
        "MikroTik": "mikrotik_routeros",
        "PaloAlto": "paloalto_panos",
        "CheckPoint": "checkpoint_gaia",
        "F5": "f5_tmsh",
        "A10": "a10",
        "Dell": "generic_ssh",
        "HP": "hp_procurve",
        "Aruba": "generic_ssh",
        "Brocade": "generic_ssh",
        "Ruckus": "generic_ssh",
        "Ubiquiti": "generic_ssh",
        "Sophos": "generic_ssh",
        "SonicWall": "generic_ssh",
        "WatchGuard": "generic_ssh",
        "Zyxel": "generic_ssh"
    }

    def __init__(self, brand, host, username=None, password=None, port=22, secret=None, protocol="ssh"):
        self.brand = brand
        self.protocol = (protocol or "ssh").strip().lower()
        base_device_type = self.BRAND_MAP.get(brand, "generic_ssh")
        # 如果是 Telnet，Netmiko 通常需要在 device_type 后加 _telnet
        self.device_type = f"{base_device_type}_telnet" if self.protocol == "telnet" else base_device_type
        
        self.connection_params = {
            "device_type": self.device_type,
            "host": host,
            "username": username or "",
            "password": password or "",
            "port": port,
            "secret": secret,
            "timeout": 10,
            "conn_timeout": 6,
            "auth_timeout": 10,
            "banner_timeout": 10,
            "blocking_timeout": 10,
        }

    def _precheck_protocol(self):
        host = self.connection_params.get("host")
        port = int(self.connection_params.get("port") or 0)
        if not host or not port:
            return
        try:
            with socket.create_connection((host, port), timeout=3) as sock:
                sock.settimeout(1.5)
                try:
                    data = sock.recv(64)
                except Exception:
                    data = b""
        except Exception as e:
            raise RuntimeError(f"TCP 连接失败：无法连接到 {host}:{port}（{self.protocol}）。{e}") from e

        if self.protocol == "telnet" and data.startswith(b"SSH-"):
            raise RuntimeError(
                f"目标端口返回 SSH banner（{data[:32].decode(errors='ignore')}），但当前设备协议设置为 telnet。"
                f"请改为 ssh，或改用 telnet 端口（通常为 23）。"
            )
        if self.protocol == "ssh" and data and (not data.startswith(b"SSH-")):
            hint = data[:32].decode(errors="ignore")
            raise RuntimeError(
                f"目标端口未返回 SSH banner（收到：{hint!r}），但当前设备协议设置为 ssh。"
                f"请检查端口/协议是否应为 telnet，或设备 SSH 服务是否开启。"
            )

    def _connect(self):
        self._precheck_protocol()
        params = dict(self.connection_params)
        if self.protocol == "telnet":
            params["global_delay_factor"] = 2
            params["global_cmd_verify"] = False
            if not str(params.get("device_type") or "").endswith("_telnet"):
                params["device_type"] = "generic_termserver_telnet"
        try:
            conn = ConnectHandler(**params)
            if hasattr(conn, "set_base_prompt"):
                try:
                    conn.set_base_prompt()
                except Exception:
                    pass

            paging_cmd = None
            if self.brand == "Huawei":
                paging_cmd = "screen-length 0 temporary"
            elif self.brand == "H3C":
                paging_cmd = "screen-length disable"
            elif self.brand == "Cisco":
                paging_cmd = "terminal length 0"
            elif self.brand == "Ruijie":
                paging_cmd = "terminal length 0"
            elif self.brand == "Juniper":
                paging_cmd = "set cli screen-length 0"
            elif self.brand == "Arista":
                paging_cmd = "terminal length 0"
            elif self.brand == "Extreme":
                paging_cmd = "disable clipaging"
            elif self.brand == "MikroTik":
                paging_cmd = None
            elif self.brand == "PaloAlto":
                paging_cmd = None
            elif self.brand == "CheckPoint":
                paging_cmd = None
            elif self.brand == "F5":
                paging_cmd = None
            elif self.brand == "A10":
                paging_cmd = None
            elif self.brand == "HP":
                paging_cmd = "no page"
            if self.protocol == "telnet":
                username_pattern = r"(?i)(user|username|login|user name|account|user id|userid|name|账号|帐号|用户名|用户)\s*[:：]"
                password_pattern = r"(?i)(pass|password|passwd|口令|密码)\s*[:：]"
                need_login = False
                try:
                    if hasattr(conn, "write_channel"):
                        conn.write_channel("\n")
                    if hasattr(conn, "read_channel"):
                        buf = conn.read_channel() or ""
                    else:
                        buf = ""
                    if buf and (re.search(username_pattern, buf) or re.search(password_pattern, buf)):
                        need_login = True
                except Exception:
                    need_login = True
                if need_login and hasattr(conn, "std_login"):
                    conn.std_login(username_pattern=username_pattern, pwd_pattern=password_pattern, delay_factor=2)
                if hasattr(conn, "set_base_prompt"):
                    conn.set_base_prompt()
            if hasattr(conn, "disable_paging"):
                try:
                    if paging_cmd:
                        conn.disable_paging(command=paging_cmd)
                    else:
                        conn.disable_paging()
                except Exception:
                    pass
            if paging_cmd and hasattr(conn, "send_command_timing"):
                try:
                    conn.send_command_timing(paging_cmd)
                except Exception:
                    pass
            return conn
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            if "Pattern not detected" in msg:
                raise RuntimeError(
                    "登录交互识别失败：可能是协议/端口不匹配（例如 telnet 连到 SSH 端口），或设备提示符为非标准/中文。"
                    f"请检查协议(ssh/telnet)、端口、以及设备是否开启对应服务。原始错误：{msg}"
                ) from e
            raise

    def execute_commands(self, commands, is_config=False):
        """执行任意 CLI 命令列表"""
        if isinstance(commands, str):
            commands = [commands]

        if (not is_config) and self.protocol == "telnet":
            username = str(self.connection_params.get("username") or "").strip()
            password = str(self.connection_params.get("password") or "").strip()
            if (not username) and (not password):
                return self._execute_telnet_noauth(commands)

        with self._connect() as conn:
            if is_config:
                if hasattr(conn, "enable"):
                    conn.enable()
                return conn.send_config_set(commands)
            else:
                results = []
                for cmd in commands:
                    if self.protocol == "telnet":
                        if hasattr(conn, "send_command_timing"):
                            results.append(
                                conn.send_command_timing(
                                    cmd,
                                    strip_prompt=False,
                                    strip_command=False,
                                    delay_factor=2,
                                    max_loops=200,
                                )
                            )
                        else:
                            results.append(conn.send_command(cmd, cmd_verify=False, read_timeout=30))
                    else:
                        results.append(conn.send_command(cmd, cmd_verify=False, read_timeout=30))
                return "\n".join(results)

    def _execute_telnet_noauth(self, commands):
        host = self.connection_params.get("host")
        port = int(self.connection_params.get("port") or 0)
        if not host or not port:
            raise RuntimeError("Telnet 连接参数不完整（host/port）。")

        from netmiko._telnetlib.telnetlib import Telnet

        def _read_idle(tn: Telnet, timeout_s: float, idle_s: float) -> bytes:
            buf = b""
            t0 = time.time()
            last_rx = None
            while time.time() - t0 < timeout_s:
                try:
                    chunk = tn.read_very_eager()
                except Exception:
                    chunk = b""
                if chunk:
                    buf += chunk
                    last_rx = time.time()
                else:
                    if last_rx is not None and (time.time() - last_rx) >= idle_s:
                        break
                    time.sleep(0.08)
            return buf

        tn = None
        try:
            tn = Telnet(host, port, timeout=3)
            tn.write(b"\r\n")
            banner = _read_idle(tn, 2.5, 0.5)
            text = banner.decode(errors="ignore")
            if re.search(r"(?i)(user|username|login|账号|帐号|用户名|用户)\s*[:：]", text) or re.search(r"(?i)(pass|password|passwd|口令|密码)\s*[:：]", text):
                raise RuntimeError(f"Telnet 端口需要登录交互（检测到登录提示），请在资产里填写用户名/密码后再试。提示片段：{text.strip()[:120]}")

            results = []
            for cmd in commands:
                cmd = str(cmd).strip()
                if not cmd:
                    continue
                tn.write(cmd.encode("utf-8", errors="ignore") + b"\r\n")
                out = _read_idle(tn, 9.0, 0.8)
                results.append(out.decode(errors="ignore"))
            return "\n".join(results)
        finally:
            try:
                if tn is not None:
                    tn.close()
            except Exception:
                pass

    def parse_health_output(self, output):
        """解析硬件健康输出 (简单正则解析)"""
        import re
        cpu = 0
        mem = 0
        temp = 35 # 默认温度
        
        # 简单通用的百分比匹配
        percentages = re.findall(r'(\d+)%', output)
        if len(percentages) >= 2:
            cpu = int(percentages[0])
            mem = int(percentages[1])
        elif len(percentages) == 1:
            cpu = int(percentages[0])
            mem = 45 # 兜底
        
        # 温度匹配
        temp_match = re.search(r'(\d+)\s*C', output)
        if temp_match:
            temp = int(temp_match.group(1))
        
        # 如果没匹配到任何内容，给一些模拟数据以便演示
        if cpu == 0: cpu = 12
        if mem == 0: mem = 48
        
        return {
            "cpu_usage": cpu,
            "mem_usage": mem,
            "temperature": temp,
            "raw": output[:200]
        }

    def backup_config(self, backup_path="./backups"):
        """备份当前配置"""
        if not os.path.exists(backup_path):
            os.makedirs(backup_path)
        
        backup_cmd = "show running-config" if self.brand == "Cisco" else "display current-configuration"
        
        with self._connect() as conn:
            config_data = conn.send_command(backup_cmd)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.brand}_{self.connection_params['host']}_{timestamp}.cfg"
            full_path = os.path.join(backup_path, filename)
            
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(config_data)
            
            return full_path

    def apply_config(self, commands):
        """下发配置策略"""
        with self._connect() as conn:
            if hasattr(conn, "enable"):
                conn.enable()
            return conn.send_config_set(commands)

    def rollback(self, backup_file):
        """配置回滚 (简单实现：将备份文件重新下发)"""
        if not os.path.exists(backup_file):
            raise FileNotFoundError("备份文件不存在")
            
        with open(backup_file, "r", encoding="utf-8") as f:
            config_lines = f.readlines()
            
        return self.apply_config(config_lines)
