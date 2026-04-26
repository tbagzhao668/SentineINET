import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Shield, Server, Cpu, Activity, AlertTriangle, CheckCircle, RotateCcw, Plus, Trash2, Globe, Settings, Bell, Clock, Play, Pause, X, Edit3, Zap, Code } from 'lucide-react';
import axios from 'axios';

const API_BASE = import.meta?.env?.VITE_API_BASE || "http://127.0.0.1:8000";

const App = () => {
  const APP_NAME = "SentinelNet";
  const APP_TAGLINE = "网络运维与安全平台";
  const [activeTab, setActiveTab] = useState('dashboard');
  
  // 数据状态
  const [devices, setDevices] = useState([]);
  const [selectedDeviceHost, setSelectedDeviceHost] = useState("");
  const [globalAi, setGlobalAi] = useState({ api_key: "", model: "gpt-4-turbo", base_url: "" });
  const [aiModels, setAiModels] = useState([]);
  const [backupServers, setBackupServers] = useState([]);
  const [settings, setSettings] = useState({ auto_inspect: false, enabled_devices: [] });
  const [deviceStatuses, setDeviceStatuses] = useState({});
  const [skills, setSkills] = useState([]);
  
  // 运行状态
  const [risks, setRisks] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [loading, setLoading] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [summary, setSummary] = useState("");
  const [alarmSummary, setAlarmSummary] = useState("");
  const [analysisMode, setAnalysisMode] = useState("security");
  const [topologyScope, setTopologyScope] = useState("enabled");
  const [topologyLoading, setTopologyLoading] = useState(false);
  const [topology, setTopology] = useState({ nodes: [], links: [], summary: "", generated_at: "" });
  const [topologyError, setTopologyError] = useState("");
  const topologySvgRef = useRef(null);
  const topologyLayoutSizeRef = useRef({ w: 0, h: 0 });
  const [topologyViewBox, setTopologyViewBox] = useState({ x: 0, y: 0, w: 980, h: 560 });
  const topologyViewBoxRef = useRef({ x: 0, y: 0, w: 980, h: 560 });
  const [hoveredTopologyNodeId, setHoveredTopologyNodeId] = useState("");
  const [topologyManualPositions, setTopologyManualPositions] = useState(() => {
    try {
      const raw = localStorage.getItem("topology.manual_positions.v1");
      const parsed = raw ? JSON.parse(raw) : null;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  });
  const topologyDragRef = useRef({ mode: "", nodeId: "", startClientX: 0, startClientY: 0, startVb: null, startNode: null, startPoint: null });
  const [topologyDragMode, setTopologyDragMode] = useState("");
  const [topologyDraggingNodeId, setTopologyDraggingNodeId] = useState("");
  const [agentAllowConfig, setAgentAllowConfig] = useState(false);
  const [agentUseAllDevices, setAgentUseAllDevices] = useState(true);
  const [agentSelectedDeviceIds, setAgentSelectedDeviceIds] = useState([]);
  const [agentSessionId, setAgentSessionId] = useState("");
  const [agentAutoExecute, setAgentAutoExecute] = useState(true);
  const [agentRun, setAgentRun] = useState(null);
  const [agentMessages, setAgentMessages] = useState([
    { role: "assistant", content: "我是网络 AI 助手。你可以用自然语言描述需求（排障、生成配置、网络部署建议等）。我会在需要时调用资产库设备执行只读命令，并自动沉淀可复用的 Skill。" }
  ]);
  const [agentInput, setAgentInput] = useState("");
  const [agentSending, setAgentSending] = useState(false);
  const agentChatEndRef = useRef(null);
  const [aiSaving, setAiSaving] = useState(false);
  const [pendingActions, setPendingActions] = useState([]);
  const [historyModal, setHistoryModal] = useState({ show: false, host: "", data: [] });
  const [devicePage, setDevicePage] = useState(1);
  const [devicePageSize, setDevicePageSize] = useState(8);
  const [backupPage, setBackupPage] = useState(1);
  const [backupPageSize, setBackupPageSize] = useState(8);
  const [skillPage, setSkillPage] = useState(1);
  const [skillPageSize, setSkillPageSize] = useState(8);

  // 表单暂存状态
  const [newDevice, setNewDevice] = useState({ brand: "Cisco", host: "", port: 22, protocol: "ssh", alias: "", username: "", password: "", inspection_interval: 10, backup_server_id: "", backup_enabled: false, backup_interval: 1440, backup_filename_prefix: "" });
  const [newSkill, setNewSkill] = useState({ brand: "Cisco", device_version: "", intent: "", commands: "", description: "" });
  const [newBackupServer, setNewBackupServer] = useState({ id: "", server_ip: "", protocol: "tftp", username: "", password: "", path: "/" });

  const brands = [
    "Huawei",
    "H3C",
    "Cisco",
    "Juniper",
    "Arista",
    "Extreme",
    "Dell",
    "HP",
    "Aruba",
    "Brocade",
    "Ruckus",
    "MikroTik",
    "Ubiquiti",
    "PaloAlto",
    "CheckPoint",
    "Sophos",
    "SonicWall",
    "WatchGuard",
    "Zyxel",
    "Fortinet",
    "Sangfor",
    "Ruijie",
    "F5",
    "A10"
  ];

  function getDeviceId(device) {
    return device?.id || `${device?.host}:${device?.port}`;
  }

  const deviceTotalPages = Math.max(1, Math.ceil((devices?.length || 0) / (devicePageSize || 1)));
  const safeDevicePage = Math.min(Math.max(1, devicePage), deviceTotalPages);
  const deviceStart = (safeDevicePage - 1) * devicePageSize;
  const pagedDevices = (devices || []).slice(deviceStart, deviceStart + devicePageSize);

  const backupTotalPages = Math.max(1, Math.ceil((backupServers?.length || 0) / (backupPageSize || 1)));
  const safeBackupPage = Math.min(Math.max(1, backupPage), backupTotalPages);
  const backupStart = (safeBackupPage - 1) * backupPageSize;
  const pagedBackupServers = (backupServers || []).slice(backupStart, backupStart + backupPageSize);

  const skillTotalPages = Math.max(1, Math.ceil((skills?.length || 0) / (skillPageSize || 1)));
  const safeSkillPage = Math.min(Math.max(1, skillPage), skillTotalPages);
  const skillStart = (safeSkillPage - 1) * skillPageSize;
  const pagedSkills = (skills || []).slice(skillStart, skillStart + skillPageSize);

  useEffect(() => {
    setDevicePage(p => Math.min(Math.max(1, p), deviceTotalPages));
  }, [deviceTotalPages]);

  useEffect(() => {
    setBackupPage(p => Math.min(Math.max(1, p), backupTotalPages));
  }, [backupTotalPages]);

  useEffect(() => {
    setSkillPage(p => Math.min(Math.max(1, p), skillTotalPages));
  }, [skillTotalPages]);

  const HealthGauge = ({ label, value, color }) => (
    <div className="flex flex-col gap-1.5 flex-1">
      <div className="flex justify-between items-center text-[8px] font-black uppercase tracking-widest text-slate-500">
        <span>{label}</span>
        <span className={color}>{value}%</span>
      </div>
      <div className="h-1 w-full bg-slate-800 rounded-full overflow-hidden">
        <div 
          className={`h-full transition-all duration-1000 ${color.replace('text-', 'bg-')}`} 
          style={{ width: `${value}%` }} 
        />
      </div>
    </div>
  );

  useEffect(() => {
    fetchInitialData();
    const timer = setInterval(() => {
      fetchPendingActions();
      fetchDeviceStatuses();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  const fetchDeviceStatuses = async () => {
    try {
      const res = await axios.get(`${API_BASE}/devices/status`);
      setDeviceStatuses(res.data);
    } catch (e) { console.error("Fetch status failed"); }
  };

  const fetchSkills = async () => {
    try {
      const res = await axios.get(`${API_BASE}/skills`);
      if (res.data) setSkills(res.data);
    } catch (e) { console.error("Fetch skills failed"); }
  };

  const fetchInitialData = async () => {
    try {
      const [aiRes, devRes, setRes, skillRes, backupRes] = await Promise.all([
        axios.get(`${API_BASE}/config/ai`),
        axios.get(`${API_BASE}/devices`),
        axios.get(`${API_BASE}/config/settings`),
        axios.get(`${API_BASE}/skills`),
        axios.get(`${API_BASE}/config/backup`)
      ]);
      if (aiRes.data) {
        setGlobalAi(aiRes.data);
        if (aiRes.data.api_key) fetchAiModels(aiRes.data);
      }
      if (devRes.data) {
        const normalizedDevices = devRes.data.map(d => ({ ...d, id: getDeviceId(d) }));
        setDevices(normalizedDevices);
        if (normalizedDevices.length > 0 && !selectedDeviceHost) setSelectedDeviceHost(normalizedDevices[0].id);
      }
      if (setRes.data) setSettings(setRes.data);
      if (skillRes.data) setSkills(skillRes.data);
      if (backupRes.data) setBackupServers(backupRes.data);
    } catch (e) { console.error("Initial fetch failed"); }
  };

  const fetchAiModels = async (config, skipSave = false) => {
    const activeConfig = config || globalAi;
    if (!activeConfig?.api_key) {
      alert("请先填写 API Key");
      return;
    }
    
    setLoading(true);
    try {
      if (!skipSave) {
        await axios.post(`${API_BASE}/config/ai`, activeConfig);
      }
      
      const res = await axios.get(`${API_BASE}/config/ai/models`);
      if (Array.isArray(res.data) && res.data.length > 0) {
        setAiModels(res.data);
      } else {
        setAiModels([]);
        alert("未获取到模型列表，请检查 API Key 或 Base URL");
      }
    } catch (e) {
      alert("获取模型失败: " + (e.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };

  const handleSaveAi = async () => {
    const trimmedKey = (globalAi.api_key || "").trim();
    if (!trimmedKey) {
      alert("请先填写 API Key");
      return;
    }
    try {
      setAiSaving(true);
      const trimmedModel = (globalAi.model || "").trim() || "gpt-4-turbo";
      const trimmedBaseUrl = (globalAi.base_url || "").trim();
      const payload = {
        ...globalAi,
        model: trimmedModel,
        base_url: trimmedBaseUrl ? trimmedBaseUrl : null,
        api_key: trimmedKey
      };
      await axios.post(`${API_BASE}/config/ai`, payload, { timeout: 15000 });
      const saved = await axios.get(`${API_BASE}/config/ai`);
      if (saved.data) {
        setGlobalAi(saved.data);
        alert(`AI 配置已保存（前端提交模型：${payload.model || "未知"}；后端生效模型：${saved.data.model || "未知"}）`);
      } else {
        alert("AI 配置已保存（后端未返回配置）");
      }
      fetchAiModels(null, true); // 保存后刷新模型列表
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      if (String(e?.code || "").toUpperCase() === "ECONNABORTED") {
        alert("保存超时：后端未在 15 秒内响应，请检查后端是否卡住或被防火墙拦截。");
      } else {
        alert("保存失败: " + detail);
      }
    } finally {
      setAiSaving(false);
    }
  };

  const handleAddBackupServer = async () => {
    try {
      if (!newBackupServer.id || !newBackupServer.server_ip) return alert("请填写 ID 和 IP");
      await axios.post(`${API_BASE}/config/backup`, newBackupServer);
      setNewBackupServer({ id: "", server_ip: "", protocol: "tftp", username: "", password: "", path: "/" });
      fetchInitialData();
      alert("备份服务器已添加");
    } catch (e) { alert("添加失败"); }
  };

  const handleDeleteBackupServer = async (id) => {
    if (!window.confirm("确定删除该备份服务器吗？")) return;
    try {
      await axios.delete(`${API_BASE}/config/backup/${id}`);
      fetchInitialData();
    } catch (e) { alert("删除失败"); }
  };

  const handleAddSkill = async () => {
    try {
      const payload = {
        ...newSkill,
        id: `skill_user_${Date.now()}`,
        commands: newSkill.commands.split('\n').filter(c => c.trim()),
        source: "user",
        created_at: new Date().toISOString()
      };
      await axios.post(`${API_BASE}/skills`, payload);
      setNewSkill({ brand: "Cisco", device_version: "", intent: "", commands: "", description: "" });
      fetchInitialData();
      alert("自定义技能已添加");
    } catch (e) { alert("添加技能失败"); }
  };

  const handleDeleteSkill = async (id) => {
    if (!window.confirm("确定删除该技能吗？")) return;
    try {
      await axios.delete(`${API_BASE}/skills/${id}`);
      fetchInitialData();
    } catch (e) { alert("删除技能失败"); }
  };

  const fetchPendingActions = async () => {
    try {
      const res = await axios.get(`${API_BASE}/inspections/pending`);
      setPendingActions(res.data);
    } catch (e) { console.error("Fetch pending failed"); }
  };

  const fetchPolicyHistory = async (deviceId) => {
    try {
      const res = await axios.get(`${API_BASE}/devices/${encodeURIComponent(deviceId)}/policies`);
      setHistoryModal({ show: true, host: deviceId, data: res.data });
    } catch (e) { alert("获取策略历史失败"); }
  };

  const handleAddDevice = async () => {
    try {
      const port = Number(newDevice.port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        alert("端口号必须是 1-65535 的整数");
        return;
      }
      await axios.post(`${API_BASE}/devices`, newDevice);
      setNewDevice({ brand: "Cisco", host: "", port: 22, protocol: "ssh", alias: "", username: "", password: "", inspection_interval: 10, backup_server_id: "", backup_enabled: false, backup_interval: 1440, backup_filename_prefix: "" });
      fetchInitialData();
      alert("设备添加成功");
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      if (String(detail).toLowerCase().includes("network") || String(detail).toLowerCase().includes("failed to fetch")) {
        alert(`无法连接后端服务（${API_BASE}）。请确认后端已启动。\n${detail}`);
      } else {
        alert("添加失败: " + detail);
      }
    }
  };

  const handleUpdateAlias = async (deviceId) => {
    const newAlias = window.prompt("请输入新的设备别名:");
    if (newAlias === null) return;
    try {
      await axios.post(`${API_BASE}/devices/${encodeURIComponent(deviceId)}/alias?alias=${newAlias}`);
      fetchInitialData();
    } catch (e) { alert("更新别名失败"); }
  };

  const handleUpdateDeviceInterval = async (device, newInterval) => {
    try {
      const updatedDevice = { ...device, inspection_interval: parseInt(newInterval) };
      await axios.post(`${API_BASE}/devices`, updatedDevice);
      fetchInitialData();
    } catch (e) { alert("更新间隔失败"); }
  };

  const handleUpdateDeviceBackup = async (device, patch) => {
    try {
      const updatedDevice = { ...device, ...patch };
      await axios.post(`${API_BASE}/devices`, updatedDevice);
      await fetchInitialData();
      await fetchDeviceStatuses();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      alert("更新备份配置失败: " + detail);
    }
  };

  const handleRunBackup = async (deviceId) => {
    try {
      await axios.post(`${API_BASE}/backup/run/${encodeURIComponent(deviceId)}`);
      await fetchDeviceStatuses();
      await fetchSkills();
      alert("备份已触发（成功后会自动沉淀备份 Skill）");
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      alert("备份失败: " + detail);
    }
  };

  const handleDeleteDevice = async (deviceId) => {
    if (!window.confirm("确定删除该设备吗？")) return;
    try {
      await axios.delete(`${API_BASE}/devices/${encodeURIComponent(deviceId)}`);
      fetchInitialData();
    } catch (e) { alert("删除失败"); }
  };

  const handleUpdateSettings = async (newSets) => {
    try {
      const res = await axios.post(`${API_BASE}/config/settings`, newSets);
      setSettings(res.data);
    } catch (e) { alert("更新设置失败"); }
  };

  const handleConfirmAction = async (actionId, approve) => {
    setLoading(approve); // 仅在批准时显示加载状态，因为包含备份过程
    try {
      const res = await axios.post(`${API_BASE}/inspections/confirm/${actionId}?approve=${approve}`);
      alert(res.data.message || (approve ? "策略下发成功" : "已忽略风险"));
      fetchPendingActions();
    } catch (e) { 
      alert("操作失败: " + (e.response?.data?.detail || e.message)); 
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedDeviceHost) return alert("请先选择设备");
    setLoading(true);
    try {
      setAnalysisMode("security");
      const response = await axios.get(`${API_BASE}/logs/analyze/${encodeURIComponent(selectedDeviceHost)}`);
      setRisks(response.data.risks || []);
      setSummary(response.data.summary || "");
      setAlarms([]);
      setAlarmSummary("");
      fetchDeviceStatuses(); // 顺便刷新状态
      fetchSkills();
    } catch (error) {
      alert("分析失败: " + (error.response?.data?.detail || error.message));
    } finally { setLoading(false); }
  };

  const handleAnalyzeAlarms = async () => {
    if (!selectedDeviceHost) return alert("请先选择设备");
    setLoading(true);
    try {
      setAnalysisMode("alarms");
      const response = await axios.get(`${API_BASE}/logs/alarms/${encodeURIComponent(selectedDeviceHost)}`);
      setAlarms(response.data.alarms || []);
      setAlarmSummary(response.data.summary || "");
      setRisks([]);
      setSummary("");
      fetchDeviceStatuses();
      fetchSkills();
    } catch (error) {
      alert("告警检测失败: " + (error.response?.data?.detail || error.message));
    } finally { setLoading(false); }
  };

  const handleGenerateTopology = async (options = {}) => {
    const silent = !!options?.silent;
    setTopologyLoading(true);
    try {
      const response = await axios.get(`${API_BASE}/topology/generate?scope=${encodeURIComponent(topologyScope)}`);
      const nodes = Array.isArray(response.data?.nodes) ? response.data.nodes : [];
      const links = Array.isArray(response.data?.links) ? response.data.links : [];
      setTopology({ nodes, links, summary: response.data?.summary || "", generated_at: response.data?.generated_at || "" });
      setTopologyError("");
      fetchSkills();
    } catch (error) {
      const detail = error.response?.data?.detail || error.message || "未知错误";
      setTopologyError(String(detail));
      if (!silent) alert("拓扑生成失败: " + detail);
    } finally {
      setTopologyLoading(false);
    }
  };

  const handleGlobalHealthCheck = async () => {
    const enabledEntries = Array.isArray(settings?.enabled_devices) ? settings.enabled_devices : [];
    const enabledSet = new Set(enabledEntries.map(x => String(x).trim()).filter(Boolean));
    const targets =
      enabledSet.size === 0
        ? (devices || [])
        : (devices || []).filter(d => enabledSet.has(getDeviceId(d)) || enabledSet.has(String(d?.host || "").trim()));

    if (!globalAi?.api_key?.trim()) {
      alert("请先在 AI 配置中填写 API Key，再执行巡检");
      return;
    }
    if (enabledSet.size === 0) {
      const ok = window.confirm("当前未配置“已启用设备”，是否对全部资产执行巡检？");
      if (!ok) return;
    }
    if (targets.length === 0) {
      alert("未找到已启用的设备，请先在资产管理中启用设备");
      return;
    }

    setLoading(true);
    try {
      const results = await Promise.allSettled(
        targets.map(d => axios.get(`${API_BASE}/logs/analyze/${encodeURIComponent(getDeviceId(d))}`))
      );

      const failures = results
        .map((r, idx) => ({ r, device: targets[idx] }))
        .filter(x => x.r.status === "rejected")
        .map(x => {
          const detail =
            x.r.reason?.response?.data?.detail ||
            x.r.reason?.message ||
            "未知错误";
          const name = x.device?.alias?.trim()
            ? `${x.device.alias} (${x.device.host}:${x.device.port})`
            : `${x.device.host}:${x.device.port}`;
          return `${name}: ${detail}`;
        });

      const successCount = results.length - failures.length;
      const failCount = failures.length;

      if (failCount === 0) {
        alert(`巡检已完成：成功 ${successCount}/${results.length}`);
      } else {
        alert(
          `巡检已完成：成功 ${successCount}/${results.length}，失败 ${failCount}/${results.length}\n` +
            `失败原因：\n` +
            failures.join("\n")
        );
      }

      fetchDeviceStatuses();
      fetchSkills();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      if (String(detail).toLowerCase().includes("network") || String(detail).toLowerCase().includes("failed to fetch")) {
        alert(`无法连接后端服务（${API_BASE}）。请确认后端已启动。\n${detail}`);
      } else {
        alert(`巡检启动失败：${detail}`);
      }
    } finally { setLoading(false); }
  };

  const handleRestartServices = async () => {
    setRestarting(true);
    try {
      const res = await axios.post(`${API_BASE}/admin/restart`, null, {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      alert(res.data?.message || "已触发后端重载");
      setTimeout(() => window.location.reload(), 1200);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      alert(`重启失败：${detail}`);
      setRestarting(false);
    }
  };

  const handleDeploy = async (ip) => {
    if (!window.confirm(`确定要封堵 IP: ${ip} 吗？`)) return;
    alert("当前版本未实现策略一键下发接口，请通过“待处理告警流”中的批准流程执行封堵。");
  };

  const topologyLayout = useMemo(() => {
    const nodes = Array.isArray(topology?.nodes) ? topology.nodes : [];
    const links = Array.isArray(topology?.links) ? topology.links : [];
    const width = 980;
    const height = 560;
    const margin = 60;
    const nodeIndex = new Map(nodes.map((n, i) => [String(n?.id ?? i), i]));
    const positions = nodes.map((n, i) => {
      const id = String(n?.id ?? i);
      const manual = topologyManualPositions?.[id];
      const mx = typeof manual?.x === "number" ? manual.x : null;
      const my = typeof manual?.y === "number" ? manual.y : null;
      let h = 2166136261;
      for (let k = 0; k < id.length; k++) {
        h ^= id.charCodeAt(k);
        h = Math.imul(h, 16777619);
      }
      const angle = ((h >>> 0) % 360) * (Math.PI / 180);
      const radius = Math.min(width, height) * 0.28;
      const cx = width / 2 + radius * Math.cos(angle);
      const cy = height / 2 + radius * Math.sin(angle);
      return { id, x: mx ?? cx, y: my ?? cy, vx: 0, vy: 0, fixed: mx !== null && my !== null };
    });

    const getPos = (id) => positions[nodeIndex.get(String(id))];

    const linkPairs = links
      .map(l => ({ s: String(l?.source ?? ""), t: String(l?.target ?? ""), local_port: l?.local_port, remote_port: l?.remote_port, expires_s: l?.expires_s, protocol: l?.protocol }))
      .filter(l => nodeIndex.has(l.s) && nodeIndex.has(l.t) && l.s !== l.t);

    const n = positions.length;
    const k = Math.sqrt((width * height) / Math.max(1, n));
    const repulsion = k * k;
    const linkDistance = k * 1.1;
    const damping = 0.85;

    for (let iter = 0; iter < 220; iter++) {
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = positions[i];
          const b = positions[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
          const force = repulsion / (dist * dist);
          dx = (dx / dist) * force;
          dy = (dy / dist) * force;
          a.vx += dx;
          a.vy += dy;
          b.vx -= dx;
          b.vy -= dy;
        }
      }

      for (const e of linkPairs) {
        const a = getPos(e.s);
        const b = getPos(e.t);
        if (!a || !b) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
        const delta = dist - linkDistance;
        const force = (delta / dist) * 0.08;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }

      for (const p of positions) {
        if (p.fixed) {
          p.vx = 0;
          p.vy = 0;
          continue;
        }
        p.vx *= damping;
        p.vy *= damping;
        p.x += p.vx;
        p.y += p.vy;
        p.x = Math.max(margin, Math.min(width - margin, p.x));
        p.y = Math.max(margin, Math.min(height - margin, p.y));
      }
    }

    const posMap = new Map(positions.map(p => [p.id, p]));
    const renderedLinks = linkPairs.map(l => ({
      ...l,
      x1: posMap.get(l.s)?.x ?? 0,
      y1: posMap.get(l.s)?.y ?? 0,
      x2: posMap.get(l.t)?.x ?? 0,
      y2: posMap.get(l.t)?.y ?? 0,
    }));

    const renderedNodes = nodes.map(n => {
      const id = String(n?.id ?? "");
      const p = posMap.get(id);
      const name = String((n?.label || id) ?? "").trim() || id;
      const hostPortRaw = String((n?.device_id || "") ?? "").trim() || String((n?.host || "") ?? "").trim();
      const hostPort = hostPortRaw && !name.includes(hostPortRaw) ? hostPortRaw : (hostPortRaw || "");
      return {
        id,
        name,
        hostPort,
        brand: n?.brand,
        x: p?.x ?? width / 2,
        y: p?.y ?? height / 2,
      };
    });

    return { width, height, nodes: renderedNodes, links: renderedLinks };
  }, [topology, topologyManualPositions]);

  useEffect(() => {
    const w = Number(topologyLayout?.width || 980);
    const h = Number(topologyLayout?.height || 560);
    const last = topologyLayoutSizeRef.current || { w: 0, h: 0 };
    topologyLayoutSizeRef.current = { w, h };

    setTopologyViewBox(prev => {
      if (!prev || !prev.w || !prev.h) return { x: 0, y: 0, w, h };
      if (!last.w || !last.h) return { x: 0, y: 0, w, h };
      const rx = w / last.w;
      const ry = h / last.h;
      return { x: prev.x * rx, y: prev.y * ry, w: prev.w * rx, h: prev.h * ry };
    });
  }, [topologyLayout?.width, topologyLayout?.height]);

  useEffect(() => {
    topologyViewBoxRef.current = topologyViewBox;
  }, [topologyViewBox]);

  useEffect(() => {
    const el = topologySvgRef.current;
    if (!el) return;

    const onWheel = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const rx = mx / rect.width;
      const ry = my / rect.height;
      const factor = e.deltaY < 0 ? 0.9 : 1.1;
      const baseW = Number(topologyLayout?.width || 980);
      const baseH = Number(topologyLayout?.height || 560);
      const minW = 140;
      const minH = 90;
      const maxW = baseW * 20;
      const maxH = baseH * 20;

      setTopologyViewBox(vb => {
        const px = vb.x + rx * vb.w;
        const py = vb.y + ry * vb.h;
        const nextW = Math.max(minW, Math.min(maxW, vb.w * factor));
        const nextH = Math.max(minH, Math.min(maxH, vb.h * factor));
        const nextX = px - rx * nextW;
        const nextY = py - ry * nextH;
        return { x: nextX, y: nextY, w: nextW, h: nextH };
      });
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [activeTab, topologyLayout?.width, topologyLayout?.height, topologyLayout?.nodes?.length, topologyLayout?.links?.length]);

  useEffect(() => {
    try {
      localStorage.setItem("topology.manual_positions.v1", JSON.stringify(topologyManualPositions || {}));
    } catch {
    }
  }, [topologyManualPositions]);

  const clientToViewBoxPoint = useCallback((clientX, clientY, vb) => {
    const el = topologySvgRef.current;
    if (!el || !vb) return null;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const rx = (clientX - rect.left) / rect.width;
    const ry = (clientY - rect.top) / rect.height;
    return { x: vb.x + rx * vb.w, y: vb.y + ry * vb.h };
  }, []);

  const onTopologyMouseMove = useCallback((e) => {
    const st = topologyDragRef.current;
    if (!st?.mode) return;
    if (st.mode === "pan") {
      const el = topologySvgRef.current;
      const vb = st.startVb;
      if (!el || !vb) return;
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const dx = (e.clientX - st.startClientX) / rect.width * vb.w;
      const dy = (e.clientY - st.startClientY) / rect.height * vb.h;
      setTopologyViewBox({ x: vb.x - dx, y: vb.y - dy, w: vb.w, h: vb.h });
      return;
    }
    if (st.mode === "node") {
      const vb = topologyViewBoxRef.current;
      const pt = clientToViewBoxPoint(e.clientX, e.clientY, vb);
      if (!pt || !st.startPoint || !st.startNode || !st.nodeId) return;
      const dx = pt.x - st.startPoint.x;
      const dy = pt.y - st.startPoint.y;
      const next = { x: st.startNode.x + dx, y: st.startNode.y + dy };
      setTopologyManualPositions(prev => ({ ...(prev || {}), [st.nodeId]: next }));
    }
  }, [clientToViewBoxPoint]);

  const endTopologyDrag = useCallback(() => {
    topologyDragRef.current = { mode: "", nodeId: "", startClientX: 0, startClientY: 0, startVb: null, startNode: null, startPoint: null };
    setTopologyDragMode("");
    setTopologyDraggingNodeId("");
    window.removeEventListener("mousemove", onTopologyMouseMove);
    window.removeEventListener("mouseup", endTopologyDrag);
  }, [onTopologyMouseMove]);

  const startTopologyPan = useCallback((e) => {
    if (e.button !== 0) return;
    const vb = topologyViewBoxRef.current;
    topologyDragRef.current = { mode: "pan", nodeId: "", startClientX: e.clientX, startClientY: e.clientY, startVb: vb, startNode: null, startPoint: null };
    setTopologyDragMode("pan");
    window.addEventListener("mousemove", onTopologyMouseMove);
    window.addEventListener("mouseup", endTopologyDrag);
  }, [endTopologyDrag, onTopologyMouseMove]);

  const startTopologyNodeDrag = useCallback((e, node) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const vb = topologyViewBoxRef.current;
    const pt = clientToViewBoxPoint(e.clientX, e.clientY, vb);
    if (!pt) return;
    const nodeId = String(node?.id ?? "");
    topologyDragRef.current = { mode: "node", nodeId, startClientX: e.clientX, startClientY: e.clientY, startVb: null, startNode: { x: node.x, y: node.y }, startPoint: pt };
    setTopologyDragMode("node");
    setTopologyDraggingNodeId(nodeId);
    window.addEventListener("mousemove", onTopologyMouseMove);
    window.addEventListener("mouseup", endTopologyDrag);
  }, [clientToViewBoxPoint, endTopologyDrag, onTopologyMouseMove]);

  useEffect(() => {
    if (activeTab !== "topology") return;
    if (!globalAi?.api_key?.trim()) return;
    handleGenerateTopology({ silent: true });
    const timer = setInterval(() => {
      handleGenerateTopology({ silent: true });
    }, 30000);
    return () => clearInterval(timer);
  }, [activeTab, topologyScope, globalAi?.api_key]);

  useEffect(() => {
    if (activeTab !== "agent") return;
    agentChatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeTab, agentMessages.length]);

  const toggleAgentDevice = (deviceId) => {
    setAgentUseAllDevices(false);
    setAgentSelectedDeviceIds(prev => {
      const set = new Set(prev || []);
      if (set.has(deviceId)) set.delete(deviceId);
      else set.add(deviceId);
      return Array.from(set);
    });
  };

  const handleAgentSend = async () => {
    const text = (agentInput || "").trim();
    if (!text || agentSending) return;
    const nextMessages = [...(agentMessages || []), { role: "user", content: text }];
    setAgentMessages(nextMessages);
    setAgentInput("");
    setAgentSending(true);
    try {
      const res = await axios.post(`${API_BASE}/agent/chat`, {
        messages: nextMessages.map(m => ({ role: m.role, content: m.content })),
        allow_config: !!agentAllowConfig,
        device_ids: agentUseAllDevices ? null : (agentSelectedDeviceIds || []),
        session_id: agentSessionId || null,
        auto_execute: !!agentAutoExecute,
      }, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (res.data?.session_id) setAgentSessionId(String(res.data.session_id));
      if (res.data?.run) setAgentRun(res.data.run);
      const msg = {
        role: "assistant",
        content: res.data?.message || "",
        plan: res.data?.plan || null,
        events: Array.isArray(res.data?.events) ? res.data.events : [],
        tool_log: Array.isArray(res.data?.tool_log) ? res.data.tool_log : [],
        skills_saved: Array.isArray(res.data?.skills_saved) ? res.data.skills_saved : [],
      };
      setAgentMessages(prev => [...(prev || []), msg]);
      agentChatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      const text = String(detail || "");
      if (text.includes("AI 工具调用循环未能收敛")) {
        setAgentMessages(prev => [...(prev || []), {
          role: "assistant",
          content: "AI 工具调用未能收敛，我已停止本次自动工具调用。\n建议：\n1) 设备选择改为单台设备；\n2) 关闭“自动执行”，改为逐步执行；\n3) 把需求拆成更小的步骤再发。\n\n如果你刚才开启了“全部设备”，建议先切到单台设备再试。",
        }]);
      } else {
        setAgentMessages(prev => [...(prev || []), { role: "assistant", content: `请求失败：${detail}` }]);
      }
    } finally {
      setAgentSending(false);
    }
  };

  const handleAgentRunNextStep = async (action = "next") => {
    if (!agentSessionId || !agentRun?.id || agentSending) return;
    setAgentSending(true);
    try {
      const res = await axios.post(`${API_BASE}/agent/run/step`, {
        session_id: agentSessionId,
        run_id: agentRun.id,
        action,
      }, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (res.data?.run) setAgentRun(res.data.run);
      if (res.data?.session_id) setAgentSessionId(String(res.data.session_id));
      const run = res.data?.run;
      const steps = Array.isArray(run?.steps) ? run.steps : [];
      const last = steps.slice().reverse().find(s => s?.ended_at) || steps.slice().reverse().find(s => s?.status === "running") || null;
      const txt = last ? `步骤 ${last.index + 1}：${last.text}\n状态：${last.status}\n${last.summary || ""}` : "已更新步骤状态。";
      setAgentMessages(prev => [...(prev || []), { role: "assistant", content: txt, events: Array.isArray(res.data?.events) ? res.data.events : [] }]);
      agentChatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "未知错误";
      setAgentMessages(prev => [...(prev || []), { role: "assistant", content: `步骤执行失败：${detail}` }]);
    } finally {
      setAgentSending(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 font-sans flex overflow-hidden">
      {/* 侧边导航栏 */}
      <aside className="w-72 bg-slate-800 border-r border-slate-700 flex flex-col z-50">
        <div className="p-8 border-b border-slate-700 flex items-center gap-3">
          <Shield className="w-8 h-8 text-blue-500" />
          <div className="flex flex-col leading-tight">
            <span className="font-bold text-xl tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">{APP_NAME}</span>
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500 mt-1">{APP_TAGLINE}</span>
          </div>
        </div>
        
        <nav className="flex-1 p-6 space-y-2">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] mb-4 ml-2">主控制台</div>
          {[
            { id: 'dashboard', label: '全局看板', icon: Activity },
            { id: 'analysis', label: '安全分析', icon: Shield },
            { id: 'topology', label: '拓扑生成', icon: Globe },
            { id: 'agent', label: 'AI 助手', icon: Code },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl font-bold transition-all duration-200 ${
                activeTab === item.id 
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40' 
                : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
              }`}
            >
              <item.icon className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          ))}

          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] mt-8 mb-4 ml-2">系统配置</div>
          {[
            { id: 'assets', label: '资产管理', icon: Server },
            { id: 'inspection', label: '自动化巡检', icon: Clock },
            { id: 'backup', label: '备份中心', icon: RotateCcw },
            { id: 'skills', label: '技能中心', icon: Zap },
            { id: 'ai', label: 'AI 配置', icon: Cpu },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-xl font-bold transition-all duration-200 ${
                activeTab === item.id 
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40' 
                : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
              }`}
            >
              <item.icon className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="p-6 border-t border-slate-700">
          <div className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-900/50 border border-slate-700/50`}>
            <div className={`w-2 h-2 rounded-full ${settings.auto_inspect ? 'bg-green-400 animate-ping' : 'bg-slate-600'}`} />
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
              {settings.auto_inspect ? '巡检引擎运行中' : '巡检引擎已停止'}
            </div>
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 h-screen overflow-y-auto relative bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-slate-800 via-slate-900 to-slate-950">
        {/* 顶部通告栏 */}
        {pendingActions.length > 0 && (
          <div className="bg-red-600 text-white px-8 py-3 flex items-center justify-between animate-pulse sticky top-0 z-40 shadow-xl">
            <div className="flex items-center gap-3 font-bold text-sm">
              <AlertTriangle className="w-5 h-5" />
              <span>实时告警：发现 {pendingActions.length} 个待处理风险</span>
            </div>
            <button onClick={() => setActiveTab('inspection')} className="bg-white text-red-600 px-5 py-1.5 rounded-full text-xs font-black uppercase hover:bg-slate-100 transition shadow-lg">
              立即处理
            </button>
          </div>
        )}

        <div className="p-10 max-w-7xl mx-auto">
          {activeTab === 'dashboard' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">全局看板</h1>
                <p className="text-slate-400 text-sm">实时监控全网安全态势与设备健康状况</p>
              </header>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
                {[
                  { label: '资产总数', value: devices.length, color: 'text-white', icon: Server },
                  { label: '在线设备', value: Object.values(deviceStatuses).filter(s => s.status === 'online' || s.status === 'threat_detected').length, color: 'text-green-400', icon: Activity },
                  { label: '高危告警', value: pendingActions.length, color: 'text-red-400', icon: AlertTriangle },
                  { label: '防御策略', value: Object.values(deviceStatuses).reduce((acc, curr) => acc + (curr.policy_count || 0), 0), color: 'text-blue-400', icon: Shield },
                ].map((stat, i) => (
                  <div key={i} className="bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl group hover:border-blue-500/30 transition-all">
                    <div className="flex justify-between items-start mb-4">
                      <div className="text-slate-500 text-[10px] font-black uppercase tracking-[0.2em]">{stat.label}</div>
                      <stat.icon className="w-5 h-5 text-slate-600 group-hover:text-blue-500 transition-colors" />
                    </div>
                    <div className={`text-4xl font-mono font-black ${stat.color}`}>{stat.value}</div>
                  </div>
                ))}
              </div>

              <div className="bg-slate-800/40 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl overflow-hidden">
                <div className="p-8 border-b border-slate-700/50 flex justify-between items-center">
                  <h3 className="font-bold text-lg text-slate-200">设备运行列表</h3>
                  <div className="flex gap-4">
                    <button 
                      onClick={handleGlobalHealthCheck}
                      disabled={loading}
                      className="px-6 py-2 rounded-xl bg-blue-600/10 text-blue-400 border border-blue-500/20 text-xs font-black uppercase tracking-widest hover:bg-blue-600 hover:text-white transition-all shadow-lg active:scale-95"
                    >
                      {loading ? '巡检中...' : '一键硬件巡检'}
                    </button>
                    <button
                      onClick={handleRestartServices}
                      disabled={restarting}
                      className="px-6 py-2 rounded-xl bg-orange-600/10 text-orange-400 border border-orange-500/20 text-xs font-black uppercase tracking-widest hover:bg-orange-600 hover:text-white transition-all shadow-lg active:scale-95"
                    >
                      {restarting ? '重启中...' : '重启服务'}
                    </button>
                    <div className="px-3 py-1 rounded-full bg-green-500/10 text-green-500 text-[10px] font-bold border border-green-500/20 flex items-center">HEALTHY</div>
                  </div>
                </div>
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="bg-slate-900/30 text-[10px] font-bold text-slate-500 uppercase tracking-widest border-b border-slate-700/50">
                      <th className="px-8 py-5">设备资产</th>
                      <th className="px-8 py-5">硬件健康</th>
                      <th className="px-8 py-5">网络状态</th>
                      <th className="px-8 py-5">巡检计划</th>
                      <th className="px-8 py-5">安全统计</th>
                      <th className="px-8 py-5 text-right">管理</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {devices.map(dev => {
                      const deviceId = getDeviceId(dev);
                      const status = deviceStatuses[deviceId];
                      return (
                        <tr key={deviceId} className="hover:bg-slate-700/20 transition group">
                          <td className="px-8 py-6">
                            <div className="font-bold text-slate-200 text-base">{dev.alias || '未命名'}</div>
                            <div className="text-[10px] text-slate-500 font-mono mt-1">{dev.brand} · {dev.host}:{dev.port}</div>
                          </td>
                          <td className="px-8 py-6">
                            <div className="flex gap-6 w-48">
                              <HealthGauge label="CPU" value={status?.health?.cpu_usage || 0} color={status?.health?.cpu_usage > 80 ? 'text-red-500' : 'text-blue-400'} />
                              <HealthGauge label="MEM" value={status?.health?.mem_usage || 0} color={status?.health?.mem_usage > 80 ? 'text-red-500' : 'text-blue-400'} />
                              <div className="flex flex-col gap-1 items-center justify-center border-l border-slate-800 pl-4">
                                <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest">TEMP</span>
                                <span className={`text-xs font-mono font-black ${status?.health?.temperature > 65 ? 'text-orange-500' : 'text-slate-300'}`}>
                                  {status?.health?.temperature || '--'}°C
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-8 py-6">
                            <div className="flex items-center gap-3">
                              <div className={`w-2.5 h-2.5 rounded-full ${
                                status?.status === 'online' || status?.status === 'threat_detected' ? 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.4)]' : 
                                status?.status === 'analyzing' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.4)]'
                              }`} />
                              <span className="text-xs font-bold uppercase tracking-wider">{status?.status || 'INITIALIZING...'}</span>
                            </div>
                          </td>
                          <td className="px-8 py-6">
                            <div className="flex items-center gap-4">
                              <div className={`text-[10px] font-black px-2.5 py-1 rounded-lg border ${status?.is_enabled ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-slate-800 text-slate-500 border-slate-700'}`}>
                                {status?.is_enabled ? 'ACTIVE' : 'IDLE'}
                              </div>
                              <div className="text-[10px] text-slate-400 font-bold">
                                每 {dev.inspection_interval} 分钟
                              </div>
                            </div>
                          </td>
                          <td className="px-8 py-6">
                            <button onClick={() => fetchPolicyHistory(deviceId)} className="flex items-center gap-2 text-blue-400 hover:text-blue-300 transition group/btn">
                              <Activity className="w-4 h-4" />
                              <span className="font-mono font-black border-b border-blue-400/30 group-hover/btn:border-blue-300 transition-all">{status?.policy_count || 0} 条策略</span>
                            </button>
                          </td>
                          <td className="px-8 py-6 text-right">
                            <button 
                              onClick={() => {
                                const newEnabled = status?.is_enabled 
                                  ? settings.enabled_devices.filter(d => d !== deviceId)
                                  : [...settings.enabled_devices, deviceId];
                                handleUpdateSettings({...settings, enabled_devices: newEnabled});
                              }}
                              className={`p-2.5 rounded-xl transition ${status?.is_enabled ? 'text-red-400 hover:bg-red-500/10 border border-transparent hover:border-red-500/20' : 'text-green-400 hover:bg-green-500/10 border border-transparent hover:border-green-500/20'}`}
                            >
                              {status?.is_enabled ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === 'topology' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">网络拓扑</h1>
                <p className="text-slate-400 text-sm">基于 LLDP 自动生成，并随网络变化自动刷新</p>
              </header>

              <div className="bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                <div className="flex flex-col lg:flex-row gap-6 lg:items-center lg:justify-between">
                  <div className="flex items-center gap-4">
                    <div className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">生成范围</div>
                    <select
                      value={topologyScope}
                      onChange={(e) => setTopologyScope(e.target.value)}
                      className="bg-slate-900/80 border border-slate-700 rounded-xl px-4 py-3 text-[10px] font-black text-slate-300 outline-none focus:ring-2 focus:ring-blue-500 transition"
                    >
                      <option value="enabled">已启用设备</option>
                      <option value="all">全部资产</option>
                    </select>
                    <button
                      onClick={handleGenerateTopology}
                      disabled={topologyLoading}
                      className="px-8 py-3 rounded-2xl bg-blue-600 hover:bg-blue-700 disabled:bg-slate-800 text-white text-[10px] font-black uppercase tracking-widest transition-all shadow-xl shadow-blue-900/20 active:scale-95 flex items-center gap-2"
                    >
                      {topologyLoading ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Globe className="w-4 h-4" />}
                      {topologyLoading ? "生成中..." : "立即刷新"}
                    </button>
                  </div>
                  <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                    {topologyError ? (
                      <span className="text-red-400">拓扑生成失败：{topologyError}</span>
                    ) : (
                      `${topology?.summary || `节点 ${topologyLayout.nodes.length} · 链路 ${topologyLayout.links.length}`}${topology?.generated_at ? ` · 更新时间 ${new Date(topology.generated_at).toLocaleString()}` : ""}`
                    )}
                  </div>
                </div>
              </div>

              <div className="bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl overflow-hidden">
                {topologyLayout.nodes.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-[520px] text-slate-600 border-2 border-dashed border-slate-700/50 rounded-3xl">
                    <Globe className="w-16 h-12 mb-6 opacity-10" />
                    <p className="text-sm font-bold uppercase tracking-widest opacity-40">暂无拓扑数据</p>
                    <p className="text-[10px] mt-3 opacity-30 uppercase tracking-[0.2em]">请确认设备已开启 LLDP，并点击立即刷新</p>
                  </div>
                ) : (
                  <svg
                    ref={topologySvgRef}
                    width="100%"
                    height={topologyLayout.height}
                    viewBox={`${topologyViewBox.x} ${topologyViewBox.y} ${topologyViewBox.w} ${topologyViewBox.h}`}
                    className="rounded-3xl bg-slate-950/30 border border-slate-800"
                    onMouseDown={startTopologyPan}
                    style={{ cursor: topologyDragMode === "pan" ? "grabbing" : "grab" }}
                  >
                    {topologyLayout.links.map((l, idx) => {
                      const nowMs = Date.now();
                      const genMs = topology?.generated_at ? Date.parse(topology.generated_at) : NaN;
                      const ageSec = Number.isFinite(genMs) ? Math.max(0, Math.floor((nowMs - genMs) / 1000)) : null;
                      const expires = typeof l.expires_s === "number" ? l.expires_s : null;
                      const expired = typeof expires === "number" && expires <= 0;
                      const nearExpiry = typeof expires === "number" && expires > 0 && expires <= 60;
                      const staleData = typeof ageSec === "number" && ageSec >= 300;

                      let stroke = "rgba(148,163,184,0.35)";
                      if (expired) stroke = "rgba(248,113,113,0.75)";
                      else if (nearExpiry) stroke = "rgba(251,191,36,0.65)";
                      else if (staleData) stroke = "rgba(148,163,184,0.18)";

                      const dash = expired || staleData ? "6 4" : undefined;

                      return (
                        <line
                          key={`${l.s}-${l.t}-${idx}`}
                          x1={l.x1}
                          y1={l.y1}
                          x2={l.x2}
                          y2={l.y2}
                          stroke={stroke}
                          strokeWidth="1.5"
                          strokeDasharray={dash}
                        />
                      );
                    })}

                    {topologyLayout.nodes.map((n) => (
                      <g
                        key={n.id}
                        onMouseEnter={() => setHoveredTopologyNodeId(String(n.id))}
                        onMouseLeave={() => setHoveredTopologyNodeId("")}
                        onMouseDown={(e) => startTopologyNodeDrag(e, n)}
                        style={{ cursor: topologyDragMode === "node" && topologyDraggingNodeId === String(n.id) ? "grabbing" : "grab" }}
                      >
                        <circle
                          cx={n.x}
                          cy={n.y}
                          r={hoveredTopologyNodeId === String(n.id) ? 24 : 18}
                          fill={hoveredTopologyNodeId === String(n.id) ? "rgba(59,130,246,0.26)" : "rgba(59,130,246,0.16)"}
                          stroke={hoveredTopologyNodeId === String(n.id) ? "rgba(96,165,250,0.95)" : "rgba(59,130,246,0.55)"}
                          strokeWidth={hoveredTopologyNodeId === String(n.id) ? 2.5 : 2}
                        />
                        <text x={n.x} y={n.y + 34} textAnchor="middle" fontSize="10" fill="rgba(226,232,240,0.9)" fontWeight="700">
                          {String(n.name).slice(0, 18)}
                        </text>
                        {n.hostPort && (
                          <text x={n.x} y={n.y + 48} textAnchor="middle" fontSize="8" fill="rgba(148,163,184,0.9)" fontWeight="700">
                            {String(n.hostPort).slice(0, 24)}
                          </text>
                        )}
                        {n.brand && (
                          <text x={n.x} y={n.y + (n.hostPort ? 62 : 48)} textAnchor="middle" fontSize="8" fill="rgba(148,163,184,0.9)" fontWeight="700">
                            {String(n.brand).slice(0, 16)}
                          </text>
                        )}

                        {hoveredTopologyNodeId === String(n.id) && (
                          <g>
                            {(() => {
                              const id = String(n.id);
                              const connected = (topologyLayout.links || []).filter(l => l.s === id || l.t === id);
                              const shown = connected.slice(0, 4);
                              const rows = 3 + shown.length;
                              const h = 16 + rows * 16;
                              return (
                                <>
                                  <rect
                                    x={n.x - 120}
                                    y={n.y - (h + 28)}
                                    width="240"
                                    height={h}
                                    rx="12"
                                    fill="rgba(2,6,23,0.92)"
                                    stroke="rgba(59,130,246,0.55)"
                                    strokeWidth="1.5"
                                  />
                                  <text x={n.x - 104} y={n.y - (h + 8)} fontSize="10" fill="rgba(226,232,240,0.95)" fontWeight="800">
                                    <tspan>别名：</tspan>
                                    <tspan>{String(n.name || "").slice(0, 26) || "-"}</tspan>
                                  </text>
                                  <text x={n.x - 104} y={n.y - (h - 12)} fontSize="10" fill="rgba(226,232,240,0.95)" fontWeight="800">
                                    <tspan>地址：</tspan>
                                    <tspan>{String(n.hostPort || n.id || "").slice(0, 30) || "-"}</tspan>
                                  </text>
                                  <text x={n.x - 104} y={n.y - (h - 32)} fontSize="10" fill="rgba(148,163,184,0.95)" fontWeight="800">
                                    <tspan>链路：</tspan>
                                    <tspan>{connected.length}</tspan>
                                  </text>
                                  {shown.map((l, i) => {
                                    const peer = l.s === id ? l.t : l.s;
                                    const localPort = l.s === id ? (l.local_port || "-") : (l.remote_port || "-");
                                    const remotePort = l.s === id ? (l.remote_port || "-") : (l.local_port || "-");
                                    const exp = typeof l.expires_s === "number" ? ` exp ${l.expires_s}s` : "";
                                    const line = `${String(peer).slice(0, 18)}  ${localPort} ↔ ${remotePort}${exp}`;
                                    return (
                                      <text key={`${peer}-${i}`} x={n.x - 104} y={n.y - (h - 52) + i * 16} fontSize="9" fill="rgba(148,163,184,0.95)" fontWeight="800">
                                        {line}
                                      </text>
                                    );
                                  })}
                                </>
                              );
                            })()}
                          </g>
                        )}
                      </g>
                    ))}
                  </svg>
                )}
              </div>
            </div>
          )}

          {activeTab === 'agent' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <h1 className="text-3xl font-black text-white mb-2">AI 助手</h1>
                    <p className="text-slate-400 text-sm">自然语言驱动的网络运维助手：建议、配置生成、必要时在资产设备上执行命令，并沉淀可复用技能</p>
                    {agentSessionId && <div className="text-[10px] text-slate-500 font-mono mt-2">Session: {agentSessionId}</div>}
                  </div>
                  <button
                    onClick={() => {
                      setAgentSessionId("");
                      setAgentAllowConfig(false);
                      setAgentAutoExecute(true);
                      setAgentUseAllDevices(true);
                      setAgentSelectedDeviceIds([]);
                      setAgentRun(null);
                      setAgentMessages([{ role: "assistant", content: "我是网络 AI 助手。你可以用自然语言描述需求（排障、生成配置、网络部署建议等）。我会在需要时调用资产库设备执行只读命令，并自动沉淀可复用的 Skill。" }]);
                      setAgentInput("");
                    }}
                    className="px-6 py-3 rounded-2xl bg-slate-800/60 text-slate-200 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 transition-all active:scale-95"
                  >
                    新会话
                  </button>
                </div>
              </header>

              <div className="max-w-6xl mx-auto">
                <div className="bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                    <div className="h-[520px] overflow-y-auto rounded-3xl bg-slate-950/30 border border-slate-800 p-6 space-y-4">
                      {(agentMessages || []).map((m, idx) => {
                        const isUser = m.role === "user";
                        const plan = m.plan && typeof m.plan === "object" ? m.plan : null;
                        const planSteps = Array.isArray(plan?.plan) ? plan.plan : [];
                        const events = Array.isArray(m.events) ? m.events : [];
                        const toolLog = Array.isArray(m.tool_log) ? m.tool_log : [];
                        const saved = Array.isArray(m.skills_saved) ? m.skills_saved : [];
                        return (
                          <div key={idx} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                            <div className={`${isUser ? "bg-blue-600/20 border-blue-500/30" : "bg-slate-900/70 border-slate-700/60"} border rounded-2xl px-5 py-4 max-w-[92%]`}>
                              <div className="text-sm leading-relaxed whitespace-pre-wrap text-slate-100">{m.content}</div>
                              {plan && (
                                <div className="mt-4 bg-black/40 border border-slate-800 rounded-xl p-4">
                                  <div className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em] mb-2">Plan</div>
                                  <div className="text-[10px] text-slate-300 font-mono">
                                    {plan?.intent ? `意图：${String(plan.intent).slice(0, 80)}` : ""}
                                  </div>
                                  {planSteps.length > 0 && (
                                    <pre className="mt-2 text-[10px] font-mono text-slate-300 whitespace-pre-wrap leading-relaxed">
                                      {planSteps.map((s, i) => `${i + 1}. ${s}`).join("\n")}
                                    </pre>
                                  )}
                                  {(plan?.need_config && !agentAllowConfig) && (
                                    <div className="mt-3 text-[10px] text-amber-400">
                                      该计划包含配置变更。需要开启“允许配置下发”后再执行。
                                    </div>
                                  )}
                                </div>
                              )}
                              {events.length > 0 && (
                                <div className="mt-4 bg-black/40 border border-slate-800 rounded-xl p-4">
                                  <div className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em] mb-2">Timeline</div>
                                  <pre className="text-[10px] font-mono text-slate-300 whitespace-pre-wrap leading-relaxed">
                                    {events.slice(-12).map((e, i) => `${i + 1}. ${String(e.ts || "").slice(11, 19)} ${e.type}${e.tool ? " · " + e.tool : ""}${e.device_id ? " · " + e.device_id : ""}${e.intent ? " · " + e.intent : ""}`).join("\n")}
                                  </pre>
                                </div>
                              )}
                              {toolLog.length > 0 && (
                                <div className="mt-4 bg-black/40 border border-slate-800 rounded-xl p-4">
                                  <div className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em] mb-2">Tools</div>
                                  <pre className="text-[10px] font-mono text-slate-300 whitespace-pre-wrap leading-relaxed">
                                    {toolLog.map((t, i) => `${i + 1}. ${t.tool} ${t.ok ? "ok" : "fail"} ${t.dt_ms}ms${t.error ? " · " + t.error : ""}`).join("\n")}
                                  </pre>
                                </div>
                              )}
                              {saved.length > 0 && (
                                <div className="mt-3 text-[10px] font-mono text-emerald-400">
                                  已沉淀 Skill：{saved.join(", ")}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      <div ref={agentChatEndRef} />
                    </div>

                    {!agentAutoExecute && agentRun?.steps && (
                      <div className="mt-6 flex flex-wrap gap-3">
                        <button
                          onClick={() => handleAgentRunNextStep("next")}
                          disabled={agentSending || !agentSessionId || !agentRun?.id}
                          className="px-6 py-3 rounded-2xl bg-emerald-600/20 text-emerald-300 border border-emerald-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-emerald-600/30 disabled:opacity-40 transition-all active:scale-95"
                        >
                          执行下一步
                        </button>
                        <button
                          onClick={() => handleAgentRunNextStep("retry")}
                          disabled={agentSending || !agentSessionId || !agentRun?.id}
                          className="px-6 py-3 rounded-2xl bg-amber-600/20 text-amber-300 border border-amber-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-amber-600/30 disabled:opacity-40 transition-all active:scale-95"
                        >
                          重试失败/待执行
                        </button>
                        <div className="text-[10px] text-slate-500 font-mono self-center">
                          Run: {String(agentRun?.id || "")} · {String(agentRun?.status || "")}
                        </div>
                      </div>
                    )}

                    <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
                      <div className="bg-slate-900/60 border border-slate-700/50 rounded-2xl p-4">
                        <div className="text-[10px] font-black uppercase tracking-[0.2em] text-blue-400 flex items-center gap-2 mb-3">
                          <Settings className="w-4 h-4" /> 工作范围
                        </div>
                        <div className="space-y-3">
                          <div className="flex items-center justify-between bg-slate-950/30 border border-slate-800 rounded-2xl p-4">
                            <div>
                              <div className="text-[10px] font-black uppercase tracking-widest text-slate-300">允许配置下发</div>
                              <div className="text-[10px] text-slate-500 mt-1 leading-relaxed">关闭时仅允许只读命令（show/display/get/ping/traceroute）</div>
                            </div>
                            <input type="checkbox" checked={agentAllowConfig} onChange={(e) => setAgentAllowConfig(e.target.checked)} className="w-5 h-5 accent-blue-500" />
                          </div>

                          <div className="flex items-center justify-between bg-slate-950/30 border border-slate-800 rounded-2xl p-4">
                            <div>
                              <div className="text-[10px] font-black uppercase tracking-widest text-slate-300">自动执行</div>
                              <div className="text-[10px] text-slate-500 mt-1 leading-relaxed">开启后一条消息会自动完成所有步骤；关闭后可逐步执行并支持重试</div>
                            </div>
                            <input type="checkbox" checked={agentAutoExecute} onChange={(e) => setAgentAutoExecute(e.target.checked)} className="w-5 h-5 accent-blue-500" />
                          </div>

                          <div className="flex items-center justify-between bg-slate-950/30 border border-slate-800 rounded-2xl p-4">
                            <div>
                              <div className="text-[10px] font-black uppercase tracking-widest text-slate-300">使用全部资产</div>
                              <div className="text-[10px] text-slate-500 mt-1 leading-relaxed">开启后助手可选择任意资产设备执行命令</div>
                            </div>
                            <input
                              type="checkbox"
                              checked={agentUseAllDevices}
                              onChange={(e) => {
                                const v = !!e.target.checked;
                                setAgentUseAllDevices(v);
                                if (v) {
                                  setAgentSelectedDeviceIds([]);
                                } else {
                                  const firstId = devices?.length ? getDeviceId(devices[0]) : "";
                                  setAgentSelectedDeviceIds(prev => (prev && prev.length ? prev : (firstId ? [firstId] : [])));
                                }
                              }}
                              className="w-5 h-5 accent-blue-500"
                            />
                          </div>
                        </div>
                      </div>

                      <div className="bg-slate-900/60 border border-slate-700/50 rounded-2xl p-4">
                        <div className="text-[10px] font-black uppercase tracking-[0.2em] text-blue-400 flex items-center gap-2 mb-3">
                          <Globe className="w-4 h-4" /> 设备选择
                        </div>
                        <div className="flex gap-3 items-center">
                          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">设备</div>
                          <select
                            value={agentUseAllDevices ? "__all__" : ((agentSelectedDeviceIds || []).length === 1 ? (agentSelectedDeviceIds || [])[0] : "__multi__")}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (v === "__all__") {
                                setAgentUseAllDevices(true);
                                setAgentSelectedDeviceIds([]);
                                return;
                              }
                              if (v === "__multi__") return;
                              setAgentUseAllDevices(false);
                              setAgentSelectedDeviceIds([v]);
                            }}
                            className="flex-1 bg-slate-900/80 border border-slate-700 rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner"
                            disabled={agentSending}
                          >
                            <option value="__all__">全部设备</option>
                            {(agentSelectedDeviceIds || []).length > 1 && <option value="__multi__">多设备（已选 {(agentSelectedDeviceIds || []).length} 台）</option>}
                            {devices.map(d => {
                              const id = getDeviceId(d);
                              const label = `${d.alias || "未命名"} · ${d.host}:${d.port}`;
                              return <option key={id} value={id}>{label}</option>;
                            })}
                          </select>
                        </div>
                        <div className="mt-2 text-[10px] text-slate-600 font-mono truncate">
                          {agentUseAllDevices ? "Scope: all" : ((agentSelectedDeviceIds || []).length === 1 ? `Scope: ${agentSelectedDeviceIds[0]}` : `Scope: multi(${(agentSelectedDeviceIds || []).length})`)}
                        </div>

                        {!agentUseAllDevices && (
                          <div className="mt-4 bg-slate-950/30 border border-slate-800 rounded-2xl p-4">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-300 mb-3">指定资产设备</div>
                            <div className="max-h-48 overflow-y-auto space-y-2 pr-1">
                              {devices.length === 0 && <div className="text-[10px] text-slate-500">暂无资产设备</div>}
                              {devices.map(d => {
                                const id = getDeviceId(d);
                                const checked = (agentSelectedDeviceIds || []).includes(id);
                                return (
                                  <label key={id} className="flex items-center justify-between gap-3 bg-slate-950/40 border border-slate-800 rounded-xl px-3 py-2">
                                    <div className="min-w-0">
                                      <div className="text-[10px] font-black text-slate-200 truncate">{d.alias || '未命名'}</div>
                                      <div className="text-[10px] text-slate-500 font-mono truncate">{d.brand} · {d.host}:{d.port}</div>
                                    </div>
                                    <input type="checkbox" checked={checked} onChange={() => toggleAgentDevice(id)} className="w-4 h-4 accent-blue-500" />
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="mt-6 flex gap-4">
                      <input
                        value={agentInput}
                        onChange={(e) => setAgentInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleAgentSend();
                          }
                        }}
                        placeholder="例如：帮我检查 127.0.0.1:2000 上 LLDP 是否启用，并给出排障建议"
                        className="flex-1 bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner"
                        disabled={agentSending}
                      />
                      <button
                        onClick={handleAgentSend}
                        disabled={agentSending || !(agentInput || '').trim()}
                        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:hover:bg-blue-600 text-white px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-xs transition shadow-xl shadow-blue-900/20 active:scale-95"
                      >
                        {agentSending ? "处理中" : "发送"}
                      </button>
                    </div>
                  </div>
                </div>
            </div>
          )}

          {activeTab === 'analysis' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">安全分析</h1>
                <p className="text-slate-400 text-sm">手动执行深度风险分析与应急策略下发</p>
              </header>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <div className="lg:col-span-1 space-y-6">
                  <div className="bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                    <h3 className="font-black mb-8 text-blue-400 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em]">
                      <Activity className="w-4 h-4" /> 分析控制台
                    </h3>
                    <div className="mb-8">
                      <label className="block text-[10px] font-black text-slate-500 uppercase mb-3 ml-1 tracking-widest">选择目标设备资产</label>
                      <select value={selectedDeviceHost} onChange={(e) => setSelectedDeviceHost(e.target.value)} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner">
                        {devices.length === 0 && <option>请先接入资产</option>}
                        {devices.map(d => {
                          const deviceId = getDeviceId(d);
                          const status = deviceStatuses[deviceId]?.status;
                          const statusIcon = status === 'online' || status === 'threat_detected' ? '🟢' : status === 'analyzing' ? '🟡' : '🔴';
                          return <option key={deviceId} value={deviceId}>{statusIcon} {d.alias || '未命名'} ({d.host}:{d.port})</option>
                        })}
                      </select>
                    </div>
                    
                    {deviceStatuses[selectedDeviceHost]?.status === 'offline' && (
                      <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-[10px] text-red-400 leading-relaxed">
                        <div className="font-black flex items-center gap-2 mb-2 uppercase tracking-widest">
                          <AlertTriangle className="w-3 h-3" /> 连接异常
                        </div>
                        <div className="opacity-80">原因: {deviceStatuses[selectedDeviceHost]?.error}</div>
                      </div>
                    )}
                    
                    <div className="grid grid-cols-2 gap-4">
                      <button onClick={handleAnalyze} disabled={loading || devices.length === 0} className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-800 py-4 rounded-2xl font-black uppercase tracking-widest text-xs flex items-center justify-center gap-3 transition-all shadow-xl shadow-blue-900/20 active:scale-95">
                        {loading && analysisMode === "security" ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                        {loading && analysisMode === "security" ? "分析中..." : "安全研判"}
                      </button>
                      <button onClick={handleAnalyzeAlarms} disabled={loading || devices.length === 0} className="w-full bg-amber-600 hover:bg-amber-700 disabled:bg-slate-800 py-4 rounded-2xl font-black uppercase tracking-widest text-xs flex items-center justify-center gap-3 transition-all shadow-xl shadow-amber-900/20 active:scale-95">
                        {loading && analysisMode === "alarms" ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />}
                        {loading && analysisMode === "alarms" ? "检测中..." : "告警检测"}
                      </button>
                    </div>
                  </div>
                  
                  {analysisMode === "security" && summary && (
                    <div className="bg-slate-800/40 p-8 rounded-3xl border border-blue-500/20 backdrop-blur-xl shadow-2xl">
                      <h3 className="font-black mb-4 text-blue-300 text-[10px] uppercase tracking-[0.2em] flex items-center gap-2">
                        <Cpu className="w-4 h-4" /> AI 智能研判
                      </h3>
                      <p className="text-sm text-slate-300 italic leading-relaxed border-l-2 border-blue-500/30 pl-4">"{summary}"</p>
                    </div>
                  )}
                  {analysisMode === "alarms" && alarmSummary && (
                    <div className="bg-slate-800/40 p-8 rounded-3xl border border-amber-500/20 backdrop-blur-xl shadow-2xl">
                      <h3 className="font-black mb-4 text-amber-300 text-[10px] uppercase tracking-[0.2em] flex items-center gap-2">
                        <Bell className="w-4 h-4" /> 告警检测结论
                      </h3>
                      <p className="text-sm text-slate-300 italic leading-relaxed border-l-2 border-amber-500/30 pl-4">"{alarmSummary}"</p>
                    </div>
                  )}
                </div>

                <div className="lg:col-span-2 bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl min-h-[500px]">
                  {analysisMode === "security" ? (
                    <>
                      <h3 className="font-black mb-8 text-orange-400 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em]">
                        <AlertTriangle className="w-4 h-4" /> 风险威胁看板 ({risks.length})
                      </h3>
                      {risks.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-80 text-slate-600 border-2 border-dashed border-slate-700/50 rounded-3xl">
                          <Shield className="w-16 h-12 mb-6 opacity-10" />
                          <p className="text-sm font-bold uppercase tracking-widest opacity-40">当前环境暂无风险记录</p>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {risks.map((risk, index) => (
                            <div key={index} className="flex items-center justify-between p-6 bg-slate-900/80 rounded-2xl border border-slate-700 group hover:border-orange-500/50 transition shadow-xl">
                              <div>
                                <div className="font-mono text-2xl text-white mb-2 font-black">{risk.ip}</div>
                                <div className="flex gap-3 text-[10px] font-black uppercase tracking-widest">
                                  <span className="px-2.5 py-1 rounded bg-orange-500/10 text-orange-500 border border-orange-500/20">{risk.type}</span>
                                  <span className={`px-2.5 py-1 rounded border ${risk.level === '高' ? 'bg-red-500/10 text-red-500 border-red-500/20' : 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20'}`}>{risk.level}级风险</span>
                                </div>
                                <div className="text-xs text-slate-500 mt-4 leading-relaxed max-w-md">{risk.reason}</div>
                              </div>
                              <button onClick={() => handleDeploy(risk.ip)} className="bg-red-600 hover:bg-red-700 text-white px-8 py-4 rounded-2xl font-black uppercase tracking-widest text-xs transition shadow-xl shadow-red-900/20 active:scale-95">
                                立即封堵
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <h3 className="font-black mb-8 text-amber-400 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em]">
                        <Bell className="w-4 h-4" /> 设备告警看板 ({alarms.length})
                      </h3>
                      {alarms.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-80 text-slate-600 border-2 border-dashed border-slate-700/50 rounded-3xl">
                          <Bell className="w-16 h-12 mb-6 opacity-10" />
                          <p className="text-sm font-bold uppercase tracking-widest opacity-40">当前环境暂无告警事件</p>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {alarms.map((alarm, index) => (
                            <div key={index} className="p-6 bg-slate-900/80 rounded-2xl border border-slate-700 hover:border-amber-500/50 transition shadow-xl">
                              <div className="flex justify-between items-start gap-6">
                                <div>
                                  <div className="font-mono text-2xl text-white mb-2 font-black">{alarm.target || "-"}</div>
                                  <div className="flex flex-wrap gap-3 text-[10px] font-black uppercase tracking-widest">
                                    <span className="px-2.5 py-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">{alarm.type || "告警事件"}</span>
                                    <span className={`px-2.5 py-1 rounded border ${(alarm.level || "").includes('高') ? 'bg-red-500/10 text-red-500 border-red-500/20' : (alarm.level || "").includes('中') ? 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20' : 'bg-slate-500/10 text-slate-400 border-slate-500/20'}`}>{alarm.level || "未知"}级</span>
                                    {alarm.time && <span className="px-2.5 py-1 rounded bg-slate-700/30 text-slate-300 border border-slate-700/50">{alarm.time}</span>}
                                  </div>
                                  {alarm.reason && <div className="text-xs text-slate-500 mt-4 leading-relaxed max-w-2xl">{alarm.reason}</div>}
                                  {alarm.suggestion && <div className="text-xs text-slate-400 mt-3 leading-relaxed max-w-2xl">建议：{alarm.suggestion}</div>}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'assets' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">资产管理</h1>
                <p className="text-slate-400 text-sm">配置与维护受保护的网络设备资产库</p>
              </header>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
                <div className="space-y-8">
                  <h2 className="text-xl font-black text-blue-400 flex items-center gap-3 uppercase tracking-widest"><Plus className="w-6 h-6" /> 接入新设备</h2>
                  <div className="space-y-6 bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                    <div className="space-y-2">
                      <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">设备标识（别名）</label>
                      <input placeholder="例如：核心出口防火墙-A" value={newDevice.alias} onChange={(e) => setNewDevice({...newDevice, alias: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">品牌</label>
                          <select value={newDevice.brand} onChange={(e) => setNewDevice({...newDevice, brand: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                              {brands.map(b => <option key={b} value={b}>{b}</option>)}
                          </select>
                      </div>
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">关联备份服务器</label>
                          <select value={newDevice.backup_server_id} onChange={(e) => setNewDevice({...newDevice, backup_server_id: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                              <option value="">未选择 (备份将不可用)</option>
                              {backupServers.map(s => <option key={s.id} value={s.id}>{s.id} ({s.server_ip})</option>)}
                          </select>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">接入协议</label>
                          <select value={newDevice.protocol} onChange={(e) => setNewDevice({...newDevice, protocol: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                              <option value="ssh">SSH</option>
                              <option value="telnet">Telnet</option>
                          </select>
                      </div>
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">巡检间隔 (min)</label>
                          <input type="number" value={newDevice.inspection_interval} onChange={(e) => setNewDevice({...newDevice, inspection_interval: parseInt(e.target.value)})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">定期备份</label>
                        <select value={newDevice.backup_enabled ? "on" : "off"} onChange={(e) => setNewDevice({ ...newDevice, backup_enabled: e.target.value === "on" })} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                          <option value="off">关闭</option>
                          <option value="on">开启</option>
                        </select>
                      </div>
                      <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">备份间隔 (min)</label>
                        <input type="number" value={newDevice.backup_interval} onChange={(e) => setNewDevice({ ...newDevice, backup_interval: parseInt(e.target.value) || 0 })} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">备份文件前缀 (可选)</label>
                      <input placeholder="例如：core-fw-a" value={newDevice.backup_filename_prefix} onChange={(e) => setNewDevice({ ...newDevice, backup_filename_prefix: e.target.value })} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <div className="grid grid-cols-3 gap-6">
                      <div className="col-span-2 space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">管理 IP 地址</label>
                        <input placeholder="0.0.0.0" value={newDevice.host} onChange={(e) => setNewDevice({...newDevice, host: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                      </div>
                      <div className="col-span-1 space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">
                          {newDevice.protocol === "telnet" ? "Telnet 端口" : "SSH 端口"}
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={65535}
                          step={1}
                          placeholder={newDevice.protocol === "telnet" ? "23" : "22"}
                          value={newDevice.port}
                          onWheel={(e) => e.currentTarget.blur()}
                          onChange={(e) => setNewDevice({ ...newDevice, port: parseInt(e.target.value) })}
                          className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <input placeholder="SSH 用户名" value={newDevice.username} onChange={(e) => setNewDevice({...newDevice, username: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                      <input type="password" placeholder="SSH 密码" value={newDevice.password} onChange={(e) => setNewDevice({...newDevice, password: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <button onClick={handleAddDevice} className="w-full bg-green-600 hover:bg-green-700 text-white font-black uppercase tracking-widest text-xs py-5 rounded-2xl shadow-xl shadow-green-900/20 active:scale-95 transition-all mt-4">确认接入资产库</button>
                  </div>
                </div>
                <div className="space-y-8">
                  <div className="flex justify-between items-end mb-4">
                    <h2 className="text-xl font-black text-slate-400 flex items-center gap-3 uppercase tracking-widest"><Server className="w-6 h-6" /> 已接入资产库 ({devices.length})</h2>
                    <div className="flex items-center gap-3">
                      <select
                        value={devicePageSize}
                        onChange={(e) => { setDevicePage(1); setDevicePageSize(parseInt(e.target.value)); }}
                        className="bg-slate-900/80 border border-slate-700 rounded-xl px-3 py-2 text-[10px] font-bold text-slate-300 outline-none focus:ring-2 focus:ring-blue-500 transition"
                      >
                        {[6, 8, 12, 16].map(n => <option key={n} value={n}>{n}/页</option>)}
                      </select>
                    </div>
                  </div>
                  {devices.length > 0 && (
                    <div className="flex justify-between items-center">
                      <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                        显示 {deviceStart + 1}-{Math.min(deviceStart + devicePageSize, devices.length)} / {devices.length}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setDevicePage(p => Math.max(1, p - 1))}
                          disabled={safeDevicePage <= 1}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          上一页
                        </button>
                        <div className="text-[10px] text-slate-400 font-black uppercase tracking-widest px-3">
                          {safeDevicePage}/{deviceTotalPages}
                        </div>
                        <button
                          onClick={() => setDevicePage(p => Math.min(deviceTotalPages, p + 1))}
                          disabled={safeDevicePage >= deviceTotalPages}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          下一页
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="space-y-4">
                    {pagedDevices.map(dev => {
                      const deviceId = getDeviceId(dev);
                      const status = deviceStatuses[deviceId]?.status;
                      const statusColor = status === 'online' || status === 'threat_detected' ? 'bg-green-500' : status === 'analyzing' ? 'bg-yellow-500' : 'bg-red-500';
                      const linkedBackupServerId = (dev.backup_server_id || "").trim();
                      return (
                        <div key={deviceId} className="flex items-center justify-between p-6 bg-slate-800/40 border border-slate-700/50 backdrop-blur-xl rounded-3xl group hover:border-blue-500/50 transition-all shadow-2xl relative">
                          <div className={`absolute left-0 top-1/2 -translate-y-1/2 w-1.5 h-10 rounded-r-full ${statusColor} shadow-[0_0_15px_rgba(0,0,0,0.5)]`} />
                          <div className="pl-4">
                            <div className="flex items-center gap-3 mb-2">
                              <span className="font-black text-blue-400 text-lg uppercase tracking-tight">{dev.alias || '未命名'}</span>
                              <button onClick={() => handleUpdateAlias(deviceId)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-blue-300 transition-all"><Edit3 className="w-4 h-4" /></button>
                            </div>
                            <div className="text-[10px] text-slate-500 font-black tracking-widest uppercase">{dev.brand} · {dev.host}:{dev.port} · {status || 'OFFLINE'}</div>
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <select
                                value={linkedBackupServerId}
                                onChange={(e) => handleUpdateDeviceBackup(dev, { backup_server_id: e.target.value })}
                                className="bg-slate-900/70 border border-slate-700/50 rounded-xl px-3 py-2 text-[10px] font-black text-slate-300 uppercase tracking-widest outline-none focus:ring-2 focus:ring-blue-500 transition"
                              >
                                <option value="">未关联备份服务器</option>
                                {backupServers.map(s => <option key={s.id} value={s.id}>{s.id} ({s.server_ip})</option>)}
                              </select>
                            </div>
                            {linkedBackupServerId && (
                              <div className="mt-3 flex flex-wrap items-center gap-2">
                                <select
                                  value={dev.backup_enabled ? "on" : "off"}
                                  onChange={(e) => handleUpdateDeviceBackup(dev, { backup_enabled: e.target.value === "on" })}
                                  className="bg-slate-900/70 border border-slate-700/50 rounded-xl px-3 py-2 text-[10px] font-black text-slate-300 uppercase tracking-widest outline-none focus:ring-2 focus:ring-blue-500 transition"
                                >
                                  <option value="off">备份关闭</option>
                                  <option value="on">备份开启</option>
                                </select>
                                <div className="flex items-center gap-2 bg-slate-900/70 border border-slate-700/50 rounded-xl px-3 py-2">
                                  <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">间隔</span>
                                  <input
                                    type="number"
                                    value={Number.isFinite(dev.backup_interval) ? dev.backup_interval : 1440}
                                    onChange={(e) => handleUpdateDeviceBackup(dev, { backup_interval: parseInt(e.target.value) || 0 })}
                                    className="w-16 bg-transparent text-[10px] text-center font-black text-blue-300 outline-none"
                                  />
                                  <span className="text-[10px] font-black uppercase tracking-widest text-slate-600">MIN</span>
                                </div>
                                <button
                                  onClick={() => handleRunBackup(deviceId)}
                                  className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-black uppercase tracking-widest shadow-xl shadow-blue-900/20 active:scale-95 transition"
                                >
                                  立即备份
                                </button>
                              </div>
                            )}
                          </div>
                          <button onClick={() => handleDeleteDevice(deviceId)} className="text-slate-700 hover:text-red-500 p-3 transition-colors bg-slate-900/50 rounded-2xl border border-transparent hover:border-red-500/20"><Trash2 className="w-5 h-5" /></button>
                        </div>
                      )
                    })}
                    {devices.length === 0 && <div className="py-20 text-center text-slate-600 italic uppercase text-xs tracking-widest font-bold opacity-30 border-2 border-dashed border-slate-800 rounded-3xl">暂无资产接入</div>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'inspection' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">自动化巡检</h1>
                <p className="text-slate-400 text-sm">配置无人值守安全巡检任务与风险闭环流程</p>
              </header>

              <div className="flex items-center justify-between bg-slate-800/40 p-10 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl mb-12">
                <div className="flex items-center gap-8">
                  <div className={`p-6 rounded-3xl shadow-2xl ${settings.auto_inspect ? 'bg-green-500/10 text-green-500 border border-green-500/20' : 'bg-slate-900 text-slate-700 border border-slate-800'}`}>
                    {settings.auto_inspect ? <Play className="w-8 h-8 animate-pulse" /> : <Pause className="w-8 h-8" />}
                  </div>
                  <div>
                    <div className="font-black text-2xl mb-2 uppercase tracking-tight">智能巡检引擎</div>
                    <div className="text-sm text-slate-500 max-w-md">引擎启动后将根据每台设备的独立计划自动抓取日志并进行 AI 安全研判。</div>
                  </div>
                </div>
                <button onClick={() => handleUpdateSettings({...settings, auto_inspect: !settings.auto_inspect})} className={`px-12 py-5 rounded-2xl font-black uppercase text-xs tracking-[0.2em] transition-all shadow-2xl active:scale-95 ${settings.auto_inspect ? 'bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20' : 'bg-blue-600 text-white hover:bg-blue-500 shadow-blue-900/30'}`}>
                  {settings.auto_inspect ? '停止自动化' : '启动自动化'}
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-5 gap-12">
                <div className="lg:col-span-2 space-y-8">
                  <h3 className="font-black text-slate-500 uppercase text-[10px] tracking-[0.3em] flex items-center gap-3 ml-2">
                    <Server className="w-4 h-4 text-blue-500" /> 巡检计划表
                  </h3>
                  <div className="space-y-4">
                    {devices.map(dev => (
                      <div key={getDeviceId(dev)} className={`flex flex-col p-6 border rounded-3xl transition-all duration-300 ${settings.enabled_devices.includes(getDeviceId(dev)) ? 'bg-slate-800/60 border-blue-500/30 shadow-xl' : 'bg-slate-900/30 border-slate-800 opacity-40 hover:opacity-60'}`}>
                        <div className="flex items-center justify-between mb-6">
                            <div className="flex items-center gap-4">
                                <div className="relative">
                                  <input 
                                      type="checkbox" 
                                      checked={settings.enabled_devices.includes(getDeviceId(dev))}
                                      onChange={(e) => {
                                          const newEnabled = e.target.checked 
                                              ? [...settings.enabled_devices, getDeviceId(dev)]
                                              : settings.enabled_devices.filter(d => d !== getDeviceId(dev));
                                          handleUpdateSettings({...settings, enabled_devices: newEnabled});
                                      }}
                                      className="w-6 h-6 rounded-lg border-slate-700 bg-slate-900 text-blue-600 focus:ring-blue-500 focus:ring-offset-slate-900 transition-all cursor-pointer"
                                  />
                                </div>
                                <div>
                                    <div className="font-black text-sm text-slate-200 uppercase tracking-tight">{dev.alias || dev.host}</div>
                                    <div className="text-[10px] text-slate-500 font-black tracking-widest mt-1 uppercase">{dev.host}:{dev.port}</div>
                                </div>
                            </div>
                            {settings.enabled_devices.includes(getDeviceId(dev)) && settings.auto_inspect && (
                                <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-green-500/10 text-green-500 text-[10px] font-black border border-green-500/20">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-ping" />
                                    MONITORING
                                </div>
                            )}
                        </div>
                        <div className="flex items-center gap-3 mt-auto pt-6 border-t border-slate-700/30">
                            <Clock className="w-4 h-4 text-slate-600" />
                            <span className="text-[10px] text-slate-500 font-black uppercase tracking-widest">执行周期:</span>
                            <div className="flex items-center gap-2 bg-slate-900/50 px-3 py-1.5 rounded-xl border border-slate-700/50">
                              <input 
                                  type="number" 
                                  value={dev.inspection_interval} 
                                  onChange={(e) => handleUpdateDeviceInterval(dev, e.target.value)}
                                  className="w-10 bg-transparent text-xs text-center font-black text-blue-400 outline-none" 
                              />
                              <span className="text-[10px] text-slate-600 font-black uppercase tracking-widest">MIN</span>
                            </div>
                        </div>
                      </div>
                    ))}
                    {devices.length === 0 && <div className="py-20 text-center text-slate-600 italic uppercase text-xs tracking-widest font-bold opacity-30 border-2 border-dashed border-slate-800 rounded-3xl">暂无资产</div>}
                  </div>
                </div>

                <div className="lg:col-span-3 space-y-8">
                  <h3 className="font-black text-slate-500 uppercase text-[10px] tracking-[0.3em] flex items-center gap-3 ml-2">
                    <Bell className="w-4 h-4 text-red-500 animate-bounce" /> 待处理告警流 ({pendingActions.length})
                  </h3>
                  <div className="space-y-6">
                    {pendingActions.map(action => (
                      <div key={action.id} className="bg-slate-800/40 p-8 rounded-3xl border border-red-500/20 backdrop-blur-xl shadow-2xl relative overflow-hidden group hover:border-red-500/40 transition-all">
                        <div className="absolute top-0 left-0 w-1.5 h-full bg-red-600 shadow-[0_0_15px_rgba(220,38,38,0.5)]" />
                        <div className="flex justify-between items-start mb-6">
                          <div>
                            <div className="text-xl font-black text-red-400 mb-2 uppercase tracking-tight">{action.alias || action.host}</div>
                            <div className="text-[10px] text-slate-500 font-black tracking-[0.2em] uppercase">{new Date(action.time).toLocaleTimeString()} · {action.host}</div>
                          </div>
                          <div className="flex gap-3">
                            <button onClick={() => handleConfirmAction(action.id, true)} className="bg-red-600 hover:bg-red-700 text-white px-6 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest shadow-xl shadow-red-900/30 active:scale-95 transition-all">同意下发</button>
                            <button onClick={() => handleConfirmAction(action.id, false)} className="bg-slate-900 hover:bg-slate-800 text-slate-400 px-6 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest border border-slate-700 active:scale-95 transition-all">忽略</button>
                          </div>
                        </div>
                        <div className="bg-slate-900/80 p-5 rounded-2xl text-xs text-slate-400 italic leading-relaxed border border-slate-800 shadow-inner border-l-2 border-red-500/30">
                          AI 安全评估结论: "{action.summary}"
                        </div>
                      </div>
                    ))}
                    {pendingActions.length === 0 && <div className="text-center py-40 text-slate-600 font-black uppercase tracking-[0.3em] bg-slate-800/20 rounded-[40px] text-xs border-2 border-dashed border-slate-800/50 opacity-30">全网环境受控 · 无活动威胁</div>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'backup' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">备份中心 (Backup Hub)</h1>
                <p className="text-slate-400 text-sm">管理多协议备份服务器，为不同设备分配独立的备份策略</p>
              </header>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
                <div className="lg:col-span-1 space-y-8">
                  <h2 className="text-xl font-black text-green-400 flex items-center gap-3 uppercase tracking-widest"><Plus className="w-6 h-6" /> 添加备份服务器</h2>
                  <div className="space-y-6 bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">服务器 ID (唯一标识)</label>
                        <input placeholder="例如：IDC-TFTP-01" value={newBackupServer.id} onChange={(e) => setNewBackupServer({...newBackupServer, id: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">服务器 IP</label>
                          <input placeholder="0.0.0.0" value={newBackupServer.server_ip} onChange={(e) => setNewBackupServer({...newBackupServer, server_ip: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                      </div>
                      <div className="space-y-2">
                          <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">传输协议</label>
                          <select value={newBackupServer.protocol} onChange={(e) => setNewBackupServer({...newBackupServer, protocol: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                              <option value="tftp">TFTP</option>
                              <option value="ftp">FTP</option>
                              <option value="sftp">SFTP</option>
                          </select>
                      </div>
                    </div>
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">备份存储路径</label>
                        <input placeholder="/" value={newBackupServer.path} onChange={(e) => setNewBackupServer({...newBackupServer, path: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    {newBackupServer.protocol !== 'tftp' && (
                      <div className="grid grid-cols-2 gap-6 animate-in slide-in-from-top-2">
                        <div className="space-y-2">
                            <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">用户名</label>
                            <input placeholder="User" value={newBackupServer.username} onChange={(e) => setNewBackupServer({...newBackupServer, username: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                        </div>
                        <div className="space-y-2">
                            <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">密码</label>
                            <input type="password" placeholder="Pass" value={newBackupServer.password} onChange={(e) => setNewBackupServer({...newBackupServer, password: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                        </div>
                      </div>
                    )}
                    <button onClick={handleAddBackupServer} className="w-full bg-green-600 hover:bg-green-700 text-white font-black uppercase tracking-widest text-xs py-5 rounded-2xl shadow-xl shadow-green-900/20 active:scale-95 transition-all mt-4">确认添加服务器</button>
                  </div>
                </div>

                <div className="lg:col-span-2 space-y-8">
                  <div className="flex justify-between items-end mb-4">
                    <h2 className="text-xl font-black text-slate-400 flex items-center gap-3 uppercase tracking-widest"><RotateCcw className="w-6 h-6" /> 已就绪服务器 ({backupServers.length})</h2>
                    <div className="flex items-center gap-3">
                      <select
                        value={backupPageSize}
                        onChange={(e) => { setBackupPage(1); setBackupPageSize(parseInt(e.target.value)); }}
                        className="bg-slate-900/80 border border-slate-700 rounded-xl px-3 py-2 text-[10px] font-bold text-slate-300 outline-none focus:ring-2 focus:ring-blue-500 transition"
                      >
                        {[6, 8, 12, 16].map(n => <option key={n} value={n}>{n}/页</option>)}
                      </select>
                    </div>
                  </div>
                  {backupServers.length > 0 && (
                    <div className="flex justify-between items-center">
                      <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                        显示 {backupStart + 1}-{Math.min(backupStart + backupPageSize, backupServers.length)} / {backupServers.length}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setBackupPage(p => Math.max(1, p - 1))}
                          disabled={safeBackupPage <= 1}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          上一页
                        </button>
                        <div className="text-[10px] text-slate-400 font-black uppercase tracking-widest px-3">
                          {safeBackupPage}/{backupTotalPages}
                        </div>
                        <button
                          onClick={() => setBackupPage(p => Math.min(backupTotalPages, p + 1))}
                          disabled={safeBackupPage >= backupTotalPages}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          下一页
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {pagedBackupServers.map(server => (
                      <div key={server.id} className="bg-slate-800/40 border border-slate-700/50 backdrop-blur-xl rounded-3xl p-8 hover:border-green-500/50 transition-all shadow-2xl relative group">
                        <div className="flex justify-between items-start mb-6">
                          <div>
                            <div className="text-[10px] font-black px-2 py-0.5 rounded bg-green-500/10 text-green-500 border border-green-500/20 uppercase tracking-widest mb-3 inline-block">{server.protocol}</div>
                            <h4 className="font-black text-white text-xl tracking-tight">{server.id}</h4>
                            <div className="text-[10px] text-slate-500 font-black tracking-widest uppercase mt-1">{server.server_ip}</div>
                          </div>
                          <button onClick={() => handleDeleteBackupServer(server.id)} className="text-slate-700 hover:text-red-500 p-3 transition-colors bg-slate-900/50 rounded-2xl border border-transparent hover:border-red-500/20"><Trash2 className="w-5 h-5" /></button>
                        </div>
                        <div className="space-y-3 pt-4 border-t border-slate-700/50">
                          <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                            <span className="text-slate-500">存储路径</span>
                            <span className="text-slate-300">{server.path}</span>
                          </div>
                          {server.username && (
                            <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                              <span className="text-slate-500">认证账号</span>
                              <span className="text-slate-300">{server.username}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    {backupServers.length === 0 && <div className="col-span-2 py-40 text-center text-slate-600 font-black uppercase tracking-[0.3em] bg-slate-800/20 rounded-[40px] text-xs border-2 border-dashed border-slate-800/50 opacity-30">暂无备份服务器</div>}
                  </div>

                  <div className="mt-10 bg-slate-800/25 border border-slate-700/40 rounded-3xl p-8 shadow-2xl">
                    <div className="flex justify-between items-end mb-6">
                      <h2 className="text-xl font-black text-blue-300 uppercase tracking-widest">定期备份任务</h2>
                      <div className="text-[10px] text-slate-500 font-black uppercase tracking-widest">从资产管理启用</div>
                    </div>
                    <div className="space-y-4">
                      {(devices || []).filter(d => (d?.backup_server_id || "").trim()).map((d) => {
                        const deviceId = getDeviceId(d);
                        const st = deviceStatuses?.[deviceId] || {};
                        const server = (backupServers || []).find(s => s.id === d.backup_server_id);
                        const last = st?.last_backup ? new Date(st.last_backup).toLocaleString() : "-";
                        const next = st?.next_backup ? new Date(st.next_backup).toLocaleString() : "-";
                        return (
                          <div key={deviceId} className="p-6 bg-slate-900/70 rounded-2xl border border-slate-700/50 hover:border-blue-500/40 transition shadow-xl">
                            <div className="flex justify-between items-start gap-6">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-3 mb-3">
                                  <div className="font-black text-white text-lg truncate">{d.alias || deviceId}</div>
                                  <div className="text-[10px] font-black px-2 py-0.5 rounded bg-slate-700/30 text-slate-200 border border-slate-700/60 uppercase tracking-widest">{d.brand}</div>
                                  <div className={`text-[10px] font-black px-2 py-0.5 rounded border uppercase tracking-widest ${d.backup_enabled ? "bg-blue-500/10 text-blue-300 border-blue-500/20" : "bg-slate-500/10 text-slate-400 border-slate-500/20"}`}>
                                    {d.backup_enabled ? "已开启" : "未开启"}
                                  </div>
                                  {server?.protocol && <div className="text-[10px] font-black px-2 py-0.5 rounded bg-green-500/10 text-green-400 border border-green-500/20 uppercase tracking-widest">{server.protocol}</div>}
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest">
                                  <div className="flex justify-between bg-slate-800/30 rounded-xl px-4 py-3 border border-slate-700/40">
                                    <span className="text-slate-500">服务器</span>
                                    <span className="text-slate-200 truncate ml-3">{server ? `${server.id} (${server.server_ip})` : d.backup_server_id}</span>
                                  </div>
                                  <div className="flex justify-between bg-slate-800/30 rounded-xl px-4 py-3 border border-slate-700/40">
                                    <span className="text-slate-500">间隔</span>
                                    <span className="text-slate-200">{Number.isFinite(d.backup_interval) ? `${d.backup_interval} min` : "-"}</span>
                                  </div>
                                  <div className="flex justify-between bg-slate-800/30 rounded-xl px-4 py-3 border border-slate-700/40">
                                    <span className="text-slate-500">上次</span>
                                    <span className="text-slate-200">{last}</span>
                                  </div>
                                  <div className="flex justify-between bg-slate-800/30 rounded-xl px-4 py-3 border border-slate-700/40">
                                    <span className="text-slate-500">下次</span>
                                    <span className="text-slate-200">{next}</span>
                                  </div>
                                </div>
                              </div>
                              <div className="flex flex-col gap-3">
                                <button onClick={() => handleRunBackup(deviceId)} className="px-6 py-3 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-black uppercase tracking-widest shadow-xl shadow-blue-900/20 active:scale-95 transition">
                                  立即备份
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                      {(devices || []).filter(d => (d?.backup_server_id || "").trim()).length === 0 && (
                        <div className="py-24 text-center text-slate-600 font-black uppercase tracking-[0.3em] bg-slate-800/20 rounded-[40px] text-xs border-2 border-dashed border-slate-800/50 opacity-30">
                          暂无已关联备份服务器的设备
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'skills' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">技能中心 (Skill Hub)</h1>
                <p className="text-slate-400 text-sm">管理 AI 自动生成的指令库或手动录入自定义运维技能</p>
              </header>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
                <div className="lg:col-span-1 space-y-8">
                  <h2 className="text-xl font-black text-blue-400 flex items-center gap-3 uppercase tracking-widest"><Plus className="w-6 h-6" /> 创建新技能</h2>
                  <div className="space-y-6 bg-slate-800/40 p-8 rounded-3xl border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">目标设备品牌</label>
                        <select value={newSkill.brand} onChange={(e) => setNewSkill({...newSkill, brand: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition">
                            {brands.map(b => <option key={b} value={b}>{b}</option>)}
                        </select>
                    </div>
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">技能意图 (Intent)</label>
                        <input placeholder="例如：查看 CPU 使用率" value={newSkill.intent} onChange={(e) => setNewSkill({...newSkill, intent: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">适用版本 (可选)</label>
                        <input placeholder="例如：V200R005 / 7.0.16" value={newSkill.device_version} onChange={(e) => setNewSkill({...newSkill, device_version: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">CLI 指令集 (每行一条)</label>
                        <textarea rows={4} placeholder="display cpu-usage..." value={newSkill.commands} onChange={(e) => setNewSkill({...newSkill, commands: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner font-mono" />
                    </div>
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-widest">技能描述</label>
                        <input placeholder="简述该技能的作用" value={newSkill.description} onChange={(e) => setNewSkill({...newSkill, description: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-4 text-sm outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner" />
                    </div>
                    <button onClick={handleAddSkill} className="w-full bg-blue-600 hover:bg-blue-700 text-white font-black uppercase tracking-widest text-xs py-5 rounded-2xl shadow-xl shadow-blue-900/20 active:scale-95 transition-all mt-4 flex items-center justify-center gap-2">
                      <Code className="w-4 h-4" /> 存入技能库
                    </button>
                  </div>
                </div>

                <div className="lg:col-span-2 space-y-8">
                  <div className="flex justify-between items-end mb-4">
                    <h2 className="text-xl font-black text-slate-400 flex items-center gap-3 uppercase tracking-widest"><Zap className="w-6 h-6" /> 已就绪技能库 ({skills.length})</h2>
                    <div className="flex items-center gap-3">
                      <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">优先匹配库中技能以节约 Token</div>
                      <select
                        value={skillPageSize}
                        onChange={(e) => { setSkillPage(1); setSkillPageSize(parseInt(e.target.value)); }}
                        className="bg-slate-900/80 border border-slate-700 rounded-xl px-3 py-2 text-[10px] font-bold text-slate-300 outline-none focus:ring-2 focus:ring-blue-500 transition"
                      >
                        {[6, 8, 12, 16].map(n => <option key={n} value={n}>{n}/页</option>)}
                      </select>
                    </div>
                  </div>
                  {skills.length > 0 && (
                    <div className="flex justify-between items-center">
                      <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                        显示 {skillStart + 1}-{Math.min(skillStart + skillPageSize, skills.length)} / {skills.length}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setSkillPage(p => Math.max(1, p - 1))}
                          disabled={safeSkillPage <= 1}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          上一页
                        </button>
                        <div className="text-[10px] text-slate-400 font-black uppercase tracking-widest px-3">
                          {safeSkillPage}/{skillTotalPages}
                        </div>
                        <button
                          onClick={() => setSkillPage(p => Math.min(skillTotalPages, p + 1))}
                          disabled={safeSkillPage >= skillTotalPages}
                          className="px-4 py-2 rounded-xl bg-slate-800/60 text-slate-300 border border-slate-700/50 text-[10px] font-black uppercase tracking-widest hover:bg-slate-700/40 disabled:opacity-40 disabled:hover:bg-slate-800/60 transition-all active:scale-95"
                        >
                          下一页
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {pagedSkills.map(skill => (
                      <div key={skill.id} className="bg-slate-800/40 border border-slate-700/50 backdrop-blur-xl rounded-3xl p-6 hover:border-blue-500/50 transition-all shadow-2xl relative group">
                        <div className="flex justify-between items-start mb-4">
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] font-black px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">{skill.brand}</span>
                              {skill.device_version && (
                                <span className="text-[10px] font-black px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 uppercase">{skill.device_version}</span>
                              )}
                              <span className={`text-[10px] font-black px-2 py-0.5 rounded uppercase ${skill.source === 'ai' ? 'bg-purple-500/10 text-purple-400 border-purple-500/20' : 'bg-green-500/10 text-green-400 border-green-500/20'}`}>
                                {skill.source === 'ai' ? 'AI Generated' : 'User Manual'}
                              </span>
                            </div>
                            <h4 className="font-black text-slate-200 text-base uppercase tracking-tight">{skill.intent}</h4>
                          </div>
                          <button onClick={() => handleDeleteSkill(skill.id)} className="text-slate-600 hover:text-red-500 transition-colors"><Trash2 className="w-4 h-4" /></button>
                        </div>
                        <div className="bg-black/40 rounded-xl p-4 mb-4 border border-slate-700/50">
                          <div className="text-[8px] font-black text-slate-600 uppercase tracking-[0.2em] mb-2">指令序列</div>
                          <pre className="text-[10px] font-mono text-green-500/80 leading-relaxed overflow-x-auto">
                            {skill.commands.join('\n')}
                          </pre>
                        </div>
                        <p className="text-[10px] text-slate-500 italic">“{skill.description}”</p>
                        <div className="absolute bottom-4 right-6 opacity-0 group-hover:opacity-100 transition-opacity">
                          <RotateCcw className="w-3 h-3 text-slate-600 animate-spin-slow" />
                        </div>
                      </div>
                    ))}
                    {skills.length === 0 && <div className="col-span-2 py-40 text-center text-slate-600 font-black uppercase tracking-[0.3em] bg-slate-800/20 rounded-[40px] text-xs border-2 border-dashed border-slate-800/50 opacity-30">技能库空空如也 · 等待 AI 学习或手动注入</div>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'ai' && (
            <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <header>
                <h1 className="text-3xl font-black text-white mb-2">系统核心配置</h1>
                <p className="text-slate-400 text-sm">配置 AI 智能引擎参数，驱动核心研判逻辑</p>
              </header>

              <div className="max-w-2xl mx-auto">
                <div className="bg-slate-800/40 p-12 rounded-[40px] border border-slate-700/50 backdrop-blur-xl shadow-2xl">
                  <div className="text-center mb-12">
                    <div className="bg-blue-600/10 w-20 h-20 rounded-[30px] flex items-center justify-center mx-auto mb-6 border border-blue-500/20 shadow-inner">
                      <Cpu className="w-10 h-10 text-blue-500" />
                    </div>
                    <h2 className="text-2xl font-black text-white uppercase tracking-tight">智能引擎参数</h2>
                  </div>
                  
                  <div className="space-y-8">
                    <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-[0.2em]">API Key</label>
                        <input type="password" placeholder="sk-..." value={globalAi.api_key} onChange={(e) => setGlobalAi({...globalAi, api_key: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-5 outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner font-mono text-sm" />
                    </div>
                    <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-[0.2em]">Base URL (可选)</label>
                        <input placeholder="https://api.openai.com/v1" value={globalAi.base_url} onChange={(e) => setGlobalAi({...globalAi, base_url: e.target.value})} className="w-full bg-slate-900/80 border border-slate-700 rounded-2xl p-5 outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner text-sm" />
                    </div>
                    <div className="space-y-3">
                        <label className="text-[10px] font-black text-slate-500 uppercase ml-1 tracking-[0.2em]">LLM 模型型号</label>
                        <div className="flex gap-4">
                          <select value={globalAi.model} onChange={(e) => setGlobalAi({...globalAi, model: e.target.value})} className="flex-1 bg-slate-900/80 border border-slate-700 rounded-2xl p-5 outline-none focus:ring-2 focus:ring-blue-500 transition font-black uppercase text-xs tracking-widest">
                              {aiModels.length > 0 ? (
                                aiModels.map(m => <option key={m} value={m}>{m}</option>)
                              ) : (
                                <option value={globalAi.model}>{globalAi.model} (未刷新列表)</option>
                              )}
                          </select>
                          <button onClick={() => fetchAiModels(globalAi)} className="px-6 bg-slate-700 hover:bg-slate-600 rounded-2xl transition-colors text-blue-400">
                            <RotateCcw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
                          </button>
                        </div>
                    </div>
                    <button
                      type="button"
                      onClick={handleSaveAi}
                      disabled={aiSaving}
                      className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-white font-black uppercase tracking-[0.3em] text-xs py-6 rounded-2xl shadow-2xl shadow-blue-900/40 transition-all mt-8 active:scale-95"
                    >
                      {aiSaving ? "保存中..." : "保存引擎配置"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>
      </main>

      {/* 策略历史弹窗 */}
      {historyModal.show && (
        <div className="fixed inset-0 bg-black/95 backdrop-blur-xl flex items-center justify-center z-[100] p-8">
          <div className="bg-slate-800 border border-slate-700 rounded-[40px] max-w-4xl w-full shadow-[0_0_100px_rgba(0,0,0,0.8)] flex flex-col max-h-[90vh] overflow-hidden">
            <div className="p-10 border-b border-slate-700/50 flex justify-between items-center bg-slate-800/50">
              <div>
                <h3 className="text-2xl font-black text-blue-400 uppercase tracking-tight">策略下发历史</h3>
                <p className="text-[10px] text-slate-500 font-bold mt-2 uppercase tracking-widest">设备资产: {historyModal.host}</p>
              </div>
              <button onClick={() => setHistoryModal({ show: false, host: "", data: [] })} className="p-4 hover:bg-slate-700 rounded-3xl transition-all text-slate-400 hover:text-white border border-transparent hover:border-slate-600 shadow-xl">
                <X className="w-6 h-6" />
              </button>
            </div>
            <div className="p-10 overflow-y-auto flex-1 space-y-8 custom-scrollbar">
              {historyModal.data.length === 0 ? (
                <div className="text-center py-40 text-slate-600 font-black uppercase text-xs tracking-[0.3em] opacity-30">暂无策略下发记录</div>
              ) : (
                historyModal.data.map((item, idx) => (
                  <div key={idx} className="bg-slate-900/80 rounded-3xl border border-slate-700 overflow-hidden shadow-2xl">
                    <div className="bg-slate-800/30 px-8 py-5 flex justify-between items-center border-b border-slate-700/50">
                      <div className="flex items-center gap-4">
                        <Clock className="w-4 h-4 text-blue-500" />
                        <span className="font-mono text-xs font-black text-slate-400 uppercase tracking-widest">{new Date(item.time).toLocaleString()}</span>
                      </div>
                      <div className="text-[10px] font-black px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 tracking-widest uppercase shadow-inner">DEPLOYED</div>
                    </div>
                    <div className="p-8 space-y-6">
                      <div className="bg-slate-800/50 p-6 rounded-2xl text-sm text-slate-300 italic border-l-4 border-blue-600 shadow-inner">
                        AI 分析简报: "{item.summary}"
                      </div>
                      <div className="space-y-4">
                        <div className="text-[10px] font-black text-slate-500 uppercase tracking-[0.3em] ml-2">执行命令序列</div>
                        <pre className="bg-black/80 p-6 rounded-2xl font-mono text-xs text-green-400 border border-slate-800 overflow-x-auto shadow-inner leading-relaxed">
                          {item.commands.join('\n')}
                        </pre>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
