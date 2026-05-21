# 视频转写纠错（独立应用）

仅包含 **转写 + 热词/词表/LLM 纠错**，不含智能切片。与根目录「视频切片机」共用 `runs/` 输出格式，可在切片机「解析」页继续处理同一任务。

## 依赖

- Windows 10+
- Python 3.10+（开发运行）
- [ffmpeg](https://ffmpeg.org/)（PATH）
- B 站 / 链接模式需 [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- 根目录 `.env` 中 `DASHSCOPE_API_KEY=sk-...`

## 开发运行

```bash
cd ..   # 仓库根目录
pip install -r requirements.txt
python transcript_app/transcript_gui.py
```

## 打包 exe

```powershell
.\transcript_app\build_transcript_exe.ps1
```

在仓库根目录生成 **`视频转写纠错.exe`**（会先清理旧 `build/`、`dist/` 与同名校验 exe）。

## 费用说明

- 日志与顶栏按 **转写（ASR）**、**纠错（LLM，含可选抽专名）** 分项显示，**合计 = 转写 + 纠错**。
- 纠错 LLM 阶段会打印 `纠错 LLM：第 x/y 批` 进度；长稿请耐心等待。

## 抽专名（可选）

- 默认开启 `TRANSCRIPT_GLOSSARY_LLM=1`：从正文抽样，**优先本机 Ollama**（`OLLAMA_BASE_URL` / `OLLAMA_MODEL`），不可用且未填「本期关键词」时用 DashScope `qwen-turbo`。
- 「本期关键词」仍可用于补充热词与规则词表。

## 验收清单（打包后）

1. 无 `.env` 时启动，提示输入 `sk-` Key 并写入 exe 同目录 `.env`
2. 本地短 mp4：生成 `runs/<名>/result.json`（含 `start_ms` / `end_ms` / `text`）
3. 勾选「转写后 AI 纠错」：日志有热词/规则/LLM 相关输出
4. 取消/暂停不崩溃，可再次运行
5. 选已有任务点「仅重跑纠错」：不重新提交 ASR
