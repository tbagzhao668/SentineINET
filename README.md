# SentinelNet

网络运维与安全平台（资产管理 + 巡检 + 拓扑 + 网络 AI 助手）。

## 一条命令安装并运行（推荐）

前提：已安装 Docker Desktop（Windows）或 Docker Engine（Linux），并启用 `docker compose`。

### 方式一：不手动下载源码（自动拉取仓库并启动）

Linux/macOS/WSL：

```bash
curl -fsSL https://raw.githubusercontent.com/tbagzhao668/SentineINET/main/install.sh | bash
```

Windows PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/tbagzhao668/SentineINET/main/install.ps1 | iex"
```

默认会拉取 GitHub 仓库并启动容器；如需改为 Gitee，可在执行前设置环境变量：

```bash
REPO_URL="https://gitee.com/tisnzhao/SentinelNET.git" curl -fsSL https://raw.githubusercontent.com/tbagzhao668/SentineINET/main/install.sh | bash
```

### 方式二：已下载源码（本目录直接启动）

```bash
docker compose up -d --build
```

启动完成后：

- 前端：http://localhost:5175
- 后端：http://localhost:8000/docs

说明：

- 前端通过 Nginx 反向代理 `/api` 到后端容器，默认无需手动配置 API 地址。
- `backend/app/db.json` 会以卷方式挂载到容器内，用于保存资产/Skill/会话等数据。

## Windows（不使用 Docker 的开发模式）

前提：安装 Node.js（建议 18+）与 Python（建议 3.12+）。

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```powershell
cd frontend
npm ci
$env:VITE_API_BASE="http://127.0.0.1:8000"
npm run dev -- --host --port 5175
```

## Linux（不使用 Docker 的开发模式）

前提：安装 Node.js（建议 18+）与 Python（建议 3.12+）。

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd frontend
npm ci
export VITE_API_BASE="http://127.0.0.1:8000"
npm run dev -- --host --port 5175
```

## 运行前需要做的配置

- AI 配置：进入网页的 AI 配置页填写 `api_key / model / base_url`。
- 资产设备：在“资产管理”里添加设备，或直接编辑 `backend/app/db.json` 中的 `devices`（测试环境）。

## 常见问题（AI 助手配置设备）

### 1) 明明勾选了多台资产，但 AI 提示“仅设备1可用”

- 先看 AI 助手面板里的 `Scope:` 提示：`all / 单台 / multi(n)`，它代表本次请求后端收到的设备范围。
- 若你在同一个会话里频繁切换“全部/单台/多台”，建议点击“新会话”后再发起新请求，确保后端会话范围与前端选择一致。

### 2) 执行失败：Paramiko: 'No existing session'

这类报错通常出现在“资产协议/端口不匹配”或“端口上没有 SSH 服务”：

- 如果端口是 Telnet（常见 23，或实验环境自定义端口如 2000/2001）：请把资产协议设为 `telnet`。
- 如果端口是 SSH（常见 22，或实验环境自定义端口）：请把资产协议设为 `ssh`，并填写正确的 SSH 用户名/密码，确保设备已开启 SSH 服务且端口可达。

### 3) 自动执行建议

- 开启“自动执行”：一次消息可能会触发多次设备命令下发（适合批量变更）。
- 关闭“自动执行”：可使用“执行下一步”逐步执行与重试（适合排障与逐步确认输出）。
