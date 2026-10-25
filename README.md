# PaperMind（论文记忆库）

把你和 ChatGPT 的论文总结对话变成一个**可分类、可检索、带知识图谱、会推荐新论文**的本地应用。
**无需任何 API key**，数据全部保存在你的电脑上。

## 一键启动

| 系统 | 做法 |
|---|---|
| Windows | 双击 `start.bat` |
| macOS | 双击 `start.command`（首次可能需要右键 → 打开） |
| Linux | 终端运行 `./start.sh` |

首次启动会自动：安装 [uv](https://docs.astral.sh/uv/) → 下载 Python 与依赖 → 打开浏览器 `http://127.0.0.1:8765`。
进入首页后，按向导选择内存档位并点「开始准备」，应用会获取 `llama-server`（先下载预编译包，失败则用 git+CMake 源码编译，也可手动指定路径）并下载模型（只需一次，支持 HF 镜像）。
前端已预先构建，**不需要安装 Node.js**。服务只监听 `127.0.0.1`。

## 硬件要求与两档模型

最低：4 核 CPU、8 GB 内存、约 10 GB 磁盘，无需 GPU。

| 档位 | 生成模型 | 嵌入模型 | 下载大小 | 运行内存（实测峰值） |
|---|---|---|---|---|
| 8 GB（默认） | Qwen3.5-4B（Q4_K_M） | EmbeddingGemma-2 | 约 3.1 GB | 约 5.5 GB + 0.5 GB |
| 16 GB（高质量） | Qwen3.5-9B（Q4_K_M） | EmbeddingGemma-2 | 约 6.0 GB | 约 9 GB + 0.5 GB |

选型依据与真实评测数据见 [`docs/模型评测.md`](docs/模型评测.md)。CPU 推理速度较慢（4 核约 3 token/s），导入时的 LLM 精修与自动分类会花几分钟；不勾选「使用 LLM 精修」时导入是规则解析，几秒完成。
没有模型也能用：规则解析导入、关键词搜索、论文库浏览、导出都不依赖模型。

## 导入聊天记录

「导入中心」支持：

1. **归档 Markdown**（如本仓库的 `论文总结记录.md`）——规则解析：自动拆分论文、合并重复（按 DOI/标题）、把追问挂到对应论文、跳过非论文轮次；
2. **ChatGPT 官方导出**（设置 → Data Controls → Export Data，上传其中的 `conversations.json`）；
3. **粘贴文本**：单篇总结或带「用户：/助手：」的对话。

重复导入同一份内容不会产生重复记录；你手动改过的字段不会被覆盖。想让以后的导入更准，在「设置」里复制「改进版总结 Prompt」给 ChatGPT，它会在总结末尾附带机器可读的 YAML 元数据块。

## 功能

论文库与卡片（五段总结、核实状态、追问与纠错）· 全文/语义/混合搜索 · 分类体系编辑器与自动归类（收件箱确认）· 知识图谱（全局/论文中心/概念）· 语义地图 · 时间线 · 主题综述（每句带来源）· 问答（带来源，库里没有就直说）· 论文推荐（OpenAlex/arXiv/bioRxiv/medRxiv/PubMed/Semantic Scholar，附理由与反馈）· 回忆闪卡（FSRS）· 导出（Markdown / Obsidian / BibTeX / JSON）。

## （可选）配置云端 API

「设置 → 云端 LLM」填写任意 OpenAI 兼容服务（Base URL、API Key、模型名，如 DeepSeek、通义千问、OpenAI）。启用后，论文笔记内容会发送到该服务；嵌入始终在本地。也可以在「外部端点」填已运行的 Ollama / LM Studio 地址。
推荐数据源可选填 OpenAlex API Key（共享网络被限流时）与 Semantic Scholar Key。

## 数据存放与备份

- 默认数据目录：仓库下的 `data/`（可用环境变量 `PAPERMIND_DATA_DIR` 修改）：`papermind.db`（数据库）、`raw/`（原始导入，只读）、`models/`、`bin/`、`backups/`、`settings.json`（含你填写的密钥，请勿分享）。
- 每次启动自动备份数据库（保留最近 7 份，`data/backups/`）；设置页可立即备份。
- 备份/迁移：复制整个 `data/` 目录；或「设置」里导出 JSON 全量备份，在另一台机器通过 `/api/import/json` 导入（会替换当前库，并先自动备份）。

## 开发

```bash
uv sync                       # 后端依赖
uv run pytest && uv run ruff check .
cd frontend && npm i && npm run build   # 构建产物输出到 backend/papermind/static/（已提交）
uv run papermind serve        # 启动
```

开发进度与决策见 [`docs/开发进度.md`](docs/开发进度.md)，完整设计见 [`docs/项目开发文档.md`](docs/项目开发文档.md)。
