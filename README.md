<div align="center">

# 视频切片机

**本地视频 / 链接 → 语音转写 → AI 智能切片 → 导出片段**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![DashScope](https://img.shields.io/badge/ASR-paraformer--v2-FF6A00)](https://help.aliyun.com/zh/model-studio/)

Windows 图形界面：

- **`视频切片机.exe`** — 转写 + 智能切片（`build_exe.ps1`）
- **`视频转写纠错.exe`** — 仅转写与纠错（`transcript_app/build_transcript_exe.ps1`）

</div>

---

## 它能做什么

| 步骤 | 说明 |
|------|------|
| **输入** | 本地 MP4/MKV 等，或 B 站 / 直链 URL（B 站自动 `yt-dlp` 拉音频） |
| **转写** | 百炼 `paraformer-v2`，句级时间戳 → `runs/.../result.json` |
| **切片** | 六种切片逻辑 + 自适应流水线（检索 / 粗分 / 精切，长稿自动分档） |
| **输出** | `clip_output/` 下导出剪辑片段 |

```mermaid
flowchart LR
  A[视频 / 链接] --> B[提取音频]
  B --> C[DashScope 转写]
  C --> D[AI 规划切片]
  D --> E[ffmpeg 导出]
```

---

## 快速开始

### 环境

- Windows 10+
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/)（加入 `PATH`）
- 处理 B 站链接时需 [yt-dlp](https://github.com/yt-dlp/yt-dlp)

### 配置密钥

```bash
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY=sk-...
```

> `.env` 已在 `.gitignore` 中，**不要提交到 Git**。

### 启动 GUI（推荐）

```bash
pip install -r requirements.txt
python gui.py
```

填写 API Key（或使用 `.env`），选择**本地 / 链接**模式，再选切片逻辑并填写本期目标。

### 命令行（可选）

```bash
python main.py --api-key "sk-xxxx" --out-dir runs local "video/a.mp4"
python main.py --api-key "sk-xxxx" --out-dir runs url "https://www.bilibili.com/video/BVxxxx"
```

---

## 六种切片逻辑

| 模式 | 适用场景 |
|------|----------|
| **按主题/关键词** | 某品牌、产品、话题的连续讲述 |
| **按人物/嘉宾** | 按姓名/称呼划段 |
| **按议题/问题** | 访谈、答疑：一问一答完整保留 |
| **按章节/段落** | 教程、发布会、直播环节 |
| **按时间范围** | 已知起止时间，直接裁剪 |
| **高光混剪** | 多条短高光，而非一整段长主题 |

长转写自动 **S / M / L** 分档：规划 → 检索 → 粗分（turbo）→ 精切（plus）。

---

## 打包 exe

**视频切片机（转写 + 切片）**

```powershell
.\build_exe.ps1
```

**视频转写纠错（仅转写，无切片）**

```powershell
.\transcript_app\build_transcript_exe.ps1
```

均在仓库根目录生成对应 exe。打包前请关闭正在运行的旧 exe。详见 [transcript_app/README.md](transcript_app/README.md)。

转写任务费用在日志与 GUI 顶栏按 **转写（ASR）**、**纠错（LLM）** 分项显示，**合计 = 转写 + 纠错**（不再只显示转写金额）。

---

## 目录说明

| 路径 | 说明 |
|------|------|
| `gui.py` | 切片机图形界面（转写 + 解析） |
| `transcript_app/transcript_gui.py` | 转写纠错独立 GUI |
| `transcript_pipeline.py` | 共享转写管线（ASR + 纠错） |
| `transcript_correct.py` | 热词 / 词表 / LLM 纠错 |
| `main.py` | CLI 批量转写（切片机会复制 source 视频） |
| `auto_clip_from_transcript.py` | 切片流水线 |
| `slice_logic.py` / `slice_strategy.py` | 六种模式与自适应策略 |
| `runs/` | 转写结果（本地，不提交） |

---

## 常见问题

<details>
<summary><b>为什么 GitHub 首页显示 README？</b></summary>

GitHub 默认渲染根目录 `README.md` 作为项目介绍页，不是代码列表。
</details>

<details>
<summary><b>本地音频如何识别？</b></summary>

工具会上传至 DashScope 临时存储（`oss://`）再调用 paraformer；也可自行提供可访问的音频 URL。
</details>

---

## 致谢

- [阿里云百炼](https://help.aliyun.com/zh/model-studio/) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [ffmpeg](https://ffmpeg.org/)