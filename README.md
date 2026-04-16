# News Justify

`news-justify` 现在可以作为一个独立项目直接复制到别的目录或别的电脑运行。

## 独立运行原则

这个目录内部已经自带：
- `demo_backend/`：FastAPI 后端和 pipeline 逻辑
- `wechat/`：公众号发布相关逻辑
- `assets/`：项目内静态资源
- `.env.example`：环境变量模板
- `requirements.txt`：依赖清单
- `start.ps1` / `start.bat`：本地启动脚本

重要约定：
- 后端配置固定从项目根目录下的 `.env` 读取，不依赖你从哪个终端目录启动。
- 运行产物固定写在当前项目目录下，不会写回外层大仓库。

## 首次使用

### 1. 复制项目

把整个 `news-justify` 文件夹复制到目标机器，例如：

```powershell
D:\workspace\news-justify
```

### 2. 安装依赖

在项目根目录执行：

```powershell
cd D:\workspace\news-justify
pip install -r requirements.txt
```

### 3. 配置环境变量

先复制模板：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`。

如果你走 DashScope：
- 填 `DASHSCOPE_API_KEY`
- 需要生成图片时，填 `DASHSCOPE_IMAGE_MODEL=wan2.7-image`

如果你走共享 OpenAI-compatible 服务：
- 填 `SHARED_MODEL_BASE_URL`
- 填 `SHARED_MODEL_API_KEY`
- 填 `SHARED_MODEL_NAME`
- 如图片模型和文本模型不同，再填 `SHARED_IMAGE_MODEL_NAME`

## 启动

推荐直接在项目根目录运行：

```powershell
.\start.ps1
```

或者：

```powershell
python -m uvicorn demo_backend.app:app --reload --host 0.0.0.0 --port 8080
```

## 自检

服务起来后，先访问：

```powershell
irm http://127.0.0.1:8080/health
```

你会看到：
- `project_root`
- `env_file`
- `env_exists`
- `data_dirs`

这几个字段可以直接确认：
- 当前跑的是不是这份 `news-justify`
- `.env` 有没有读到
- JSON、数据库、图片会写到哪个目录

## 运行 pipeline

### 获取新闻

```powershell
irm "http://127.0.0.1:8080/api/news/issue?mock=true"
```

### 跑一次完整 pipeline

```powershell
$resp = irm -Method POST "http://127.0.0.1:8080/api/pipeline/demo-run?mock=true"
$resp | ConvertTo-Json -Depth 20
```

## 产物目录

所有产物都在当前项目目录下：

- 调试 JSON：`demo_backend/data/debug_pipeline/`
- 脚本数据库：`demo_backend/data/pipeline_scripts.db`
- 生成图片：`demo_backend/data/generated_images/`
- 公众号发布工作区：`content_store/issues/`

可以直接打开：

```powershell
explorer .\demo_backend\data
explorer .\content_store
```

## 常见问题

### 1. 为什么我复制到别的目录后跑不起来？

先看 `/health`：
- 如果 `env_exists=false`，说明项目根目录没有 `.env`
- 如果模型配置为空，说明 `.env` 没填完整

### 2. 为什么接口成功了但没看到文件？

以 `/health` 返回的 `data_dirs` 为准去找，不要再去外层旧仓库里找。

### 3. PowerShell 下为什么 `curl -X POST` 报错？

PowerShell 里的 `curl` 默认映射到 `Invoke-WebRequest`。建议改用：

```powershell
irm -Method POST "http://127.0.0.1:8080/api/pipeline/demo-run?mock=true"
```
