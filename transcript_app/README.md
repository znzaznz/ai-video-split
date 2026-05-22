# 视频转写纠错（独立应用）

**转写 + 纠错/润色**，不含智能切片。与根目录「视频切片机」共用 `runs/`，可在切片机「解析」页继续切片。

## 能力（对齐 bilibili-to-text 转写线）

| 能力 | 说明 |
|------|------|
| 平台 | 本地视频、**B 站**、**抖音**（分享文案自动抽链） |
| 后处理 | **纠错**（热词+词表+LLM，默认）/ **润色**（轻量 Qwen）/ **仅转写** |
| Tk GUI | `transcript_gui.py` → `视频转写纠错.exe` |
| Electron 查证 | `chat-ui/`：解析视频 + Gemini 对话（样式同 b2t） |
| CLI | 仓库根 `transcript_cli.py`（chat-ui 子进程调用） |
| 排障 | `python tools/doctor.py` |

## 依赖

- Windows 10+
- Python 3.10+、`pip install -r requirements.txt`（含 `yt-dlp`）
- [ffmpeg](https://ffmpeg.org/)（PATH）
- 根目录 `.env`：`DASHSCOPE_API_KEY=sk-...`
- 抖音：`cookies.txt` 或 Electron 登录同步，见 [docs/troubleshoot-douyin.md](../docs/troubleshoot-douyin.md)
- chat-ui 对话：`GEMINI_API_KEY` 或 `GOOGLE_API_KEY`（可选）

## Tk 开发运行

```powershell
cd c:\code\video-to-word
pip install -r requirements.txt
python transcript_app\transcript_gui.py
```

链接框可粘贴**整段抖音分享文案**；「转写后」可选纠错 / 润色 / 仅转写。

## 转写查证（Electron，与 b2t 同款 UI）

```powershell
cd transcript_app\chat-ui
npm install
npm run dev
```

- 解析视频会 `spawn` 仓库根 `transcript_cli.py`
- Cookie 写入仓库根 `cookies.txt`
- 可选 `.env` 中 `TRANSCRIPT_POST_ASR_MODE=polish|correct|none`

## CLI（命令行）

```powershell
python transcript_cli.py "https://www.bilibili.com/video/BVxxxx"
python transcript_cli.py "抖音分享文案..."
python transcript_cli.py --local path\to\video.mp4
python transcript_cli.py --post-asr-mode polish "链接"
python transcript_cli.py --doctor
```

## 打包 exe

```powershell
.\transcript_app\build_transcript_exe.ps1
```

生成 **`视频转写纠错.exe`**（仓库根目录）。

## 环境变量

| 变量 | 说明 |
|------|------|
| `TRANSCRIPT_POST_ASR_MODE` | `correct` / `polish` / `none` |
| `YT_DLP_COOKIES` | 抖音 Cookie 文件路径 |
| `TRANSCRIPT_KEYWORDS` | 本期关键词 |
| `TRANSCRIPT_LLM_CORRECT` | 纠错模式下是否用 LLM（`0` 关闭） |

## 验收清单

1. `scripts/verify.ps1` 通过
2. 本地 mp4 → `runs/.../result.json`
3. B 站 / 抖音链接（需 Cookie）→ 同上
4. 纠错 / 润色切换后 `result.json` 文本有变化
5. `npm run dev` 可解析并加载 `result.json` 对话（需 Gemini Key）
