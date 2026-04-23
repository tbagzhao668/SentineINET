# SentinelNet

网络运维与安全平台（资产管理 + 巡检 + 拓扑 + 网络 AI 助手）。

## 一条命令安装并运行（推荐）

前提：已安装 Docker Desktop（Windows）或 Docker Engine（Linux），并启用 `docker compose`。

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
