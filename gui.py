#!/usr/bin/env python3
"""
Simple desktop GUI for video-to-text pipeline.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import main as pipeline_main
import auto_clip_from_transcript as clipper


def load_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def save_env_key(api_key: str) -> None:
    env_path = Path.cwd() / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated = False
    for i, raw in enumerate(lines):
        if raw.strip().startswith("DASHSCOPE_API_KEY="):
            lines[i] = f"DASHSCOPE_API_KEY={api_key}"
            updated = True
            break

    if not updated:
        lines.insert(0, f"DASHSCOPE_API_KEY={api_key}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def get_runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_stats_path() -> Path:
    current = get_runtime_base_dir() / "usage_stats.json"
    if current.exists():
        return current

    legacy_candidates = [
        get_runtime_base_dir() / "dist" / "usage_stats.json",
        Path.cwd() / "dist" / "usage_stats.json",
        get_runtime_base_dir().parent / "dist" / "usage_stats.json",
    ]
    for legacy in legacy_candidates:
        if not legacy.exists():
            continue
        try:
            current.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            return current
        except Exception:
            continue
    return current


def load_usage_stats(stats_path: Path) -> dict[str, float]:
    if not stats_path.exists():
        return {
            "total_cost_cny": 0.0,
            "total_seconds": 0.0,
            "total_jobs": 0.0,
            "clip_cost_cny": 0.0,
            "clip_jobs": 0.0,
        }
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        return {
            "total_cost_cny": float(data.get("total_cost_cny", 0.0)),
            "total_seconds": float(data.get("total_seconds", 0.0)),
            "total_jobs": float(data.get("total_jobs", 0.0)),
            "clip_cost_cny": float(data.get("clip_cost_cny", 0.0)),
            "clip_jobs": float(data.get("clip_jobs", 0.0)),
        }
    except Exception:
        return {
            "total_cost_cny": 0.0,
            "total_seconds": 0.0,
            "total_jobs": 0.0,
            "clip_cost_cny": 0.0,
            "clip_jobs": 0.0,
        }


def save_usage_stats(stats_path: Path, stats: dict[str, float]) -> None:
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def find_env_values() -> dict[str, str]:
    candidates: list[Path] = []
    # 1) Current working directory
    candidates.append(Path.cwd() / ".env")
    # 2) Script directory (for python gui.py)
    candidates.append(Path(__file__).resolve().parent / ".env")
    # 3) Exe directory (for packaged app)
    candidates.append(Path(sys.executable).resolve().parent / ".env")
    # 4) Parent of exe directory (common layout: dist/ -> project root)
    candidates.append(Path(sys.executable).resolve().parent.parent / ".env")

    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        values = load_env_values(p)
        if values:
            return values
    return {}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Video To Word")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.stats_path = resolve_stats_path()
        self.usage_stats = load_usage_stats(self.stats_path)
        self.cost_summary_var = tk.StringVar()
        self._refresh_cost_summary()

        env = find_env_values()
        self.mode_var = tk.StringVar(value="local")
        self.api_key_var = tk.StringVar(value=env.get("DASHSCOPE_API_KEY", ""))
        self.out_dir_var = tk.StringVar(
            value=str(Path(env.get("OUTPUT_DIR", "runs")).resolve())
        )
        self.poll_var = tk.StringVar(value=env.get("POLL_INTERVAL", "2"))
        self.timeout_var = tk.StringVar(value=env.get("TIMEOUT", "900"))

        self.local_files: list[str] = []
        self.parse_tasks: list[dict[str, str]] = []
        self.clip_worker: threading.Thread | None = None
        self.clip_cancel_event = threading.Event()

        if not self.api_key_var.get().startswith("sk-"):
            key = simpledialog.askstring(
                "请输入 API Key",
                "未在 .env 检测到有效 DASHSCOPE_API_KEY。\n请输入 sk- 开头的 Key：",
                show="*",
                parent=self.root,
            )
            if not key or not key.strip().startswith("sk-"):
                messagebox.showerror("参数错误", "未提供有效的 sk- API Key，程序即将退出。")
                self.root.destroy()
                return
            self.api_key_var.set(key.strip())
            save_env_key(self.api_key_var.get())

        self._build_ui()
        self._tick_logs()
        self.refresh_parse_tasks()

    def _style_notebook_tabs(self, nb: ttk.Notebook) -> None:
        style = ttk.Style()
        try:
            style.configure("BigTab.TNotebook.Tab", padding=(18, 10), font=("Microsoft YaHei UI", 11, "bold"))
        except Exception:
            style.configure("BigTab.TNotebook.Tab", padding=(18, 10), font=("Segoe UI", 11, "bold"))
        nb.configure(style="BigTab.TNotebook")

    def _build_ui(self) -> None:
        self.root.geometry("1024x700")

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            textvariable=self.cost_summary_var,
            foreground="#0b6a0b",
        ).pack(anchor="w", pady=(0, 6))

        nb = ttk.Notebook(outer)
        nb.pack(fill=tk.BOTH, expand=True)

        tab_trans = ttk.Frame(nb, padding=6)
        tab_parse = ttk.Frame(nb, padding=6)
        nb.add(tab_trans, text="转写")
        nb.add(tab_parse, text="解析")
        self._style_notebook_tabs(nb)

        # --- Transcribe tab (existing UI) ---
        frm = ttk.Frame(tab_trans)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="模式:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(frm, text="本地视频", value="local", variable=self.mode_var, command=self._refresh_mode).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Radiobutton(frm, text="视频链接", value="url", variable=self.mode_var, command=self._refresh_mode).grid(
            row=0, column=2, sticky="w"
        )

        ttk.Label(frm, text="输出目录:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.out_dir_var, width=70).grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(frm, text="选择", command=self._pick_out_dir).grid(row=1, column=4, sticky="ew")

        ttk.Label(frm, text="轮询间隔(s):").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.poll_var, width=10).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="超时(s):").grid(row=2, column=2, sticky="e")
        ttk.Entry(frm, textvariable=self.timeout_var, width=10).grid(row=2, column=3, sticky="w")

        self.local_frame = ttk.LabelFrame(frm, text="本地视频输入")
        self.local_frame.grid(row=3, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        ttk.Button(self.local_frame, text="选择一个或多个视频", command=self._pick_local_files).pack(anchor="w", pady=4)
        self.local_list = tk.Listbox(self.local_frame, height=6)
        self.local_list.pack(fill=tk.BOTH, expand=True)

        self.url_frame = ttk.LabelFrame(frm, text="链接输入（每行一个URL）")
        self.url_frame.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        self.url_text = scrolledtext.ScrolledText(self.url_frame, height=7)
        self.url_text.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(6, 6))
        self.run_btn = ttk.Button(btns, text="开始执行", command=self._run)
        self.run_btn.pack(side=tk.LEFT)
        self.pause_btn = ttk.Button(btns, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.cancel_btn = ttk.Button(btns, text="取消", command=self._cancel_run, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(frm, text="运行日志")
        log_frame.grid(row=6, column=0, columnspan=5, sticky="nsew", pady=(6, 0))
        self.log = scrolledtext.ScrolledText(log_frame, height=14)
        self.log.pack(fill=tk.BOTH, expand=True)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)
        frm.columnconfigure(3, weight=1)
        frm.rowconfigure(3, weight=1)
        frm.rowconfigure(4, weight=1)
        frm.rowconfigure(6, weight=2)

        self._refresh_mode()

        # --- Parse tab ---
        paned = ttk.Panedwindow(tab_parse, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=4)
        right = ttk.Frame(paned, padding=4)
        paned.add(left, weight=1)
        paned.add(right, weight=2)

        ttk.Label(left, text="已完成任务（来自转写输出目录）").pack(anchor="w")
        row_btns = ttk.Frame(left)
        row_btns.pack(fill=tk.X, pady=(4, 4))
        ttk.Button(row_btns, text="刷新列表", command=self.refresh_parse_tasks).pack(side=tk.LEFT)
        ttk.Button(row_btns, text="打开任务目录", command=self._open_selected_task_dir).pack(side=tk.LEFT, padx=(8, 0))

        self.parse_list = tk.Listbox(left, height=18, exportselection=False, selectmode=tk.EXTENDED)
        self.parse_list.pack(fill=tk.BOTH, expand=True)
        self.parse_list.bind("<<ListboxSelect>>", self._on_parse_select)

        ttk.Label(right, text="解析文件表", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        parse_table_wrap = ttk.Frame(right)
        parse_table_wrap.pack(fill=tk.X, pady=(6, 0))
        self.parse_selected_table = tk.Listbox(parse_table_wrap, height=5, exportselection=False)
        self.parse_selected_table.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.parse_selected_scroll = ttk.Scrollbar(
            parse_table_wrap, orient=tk.VERTICAL, command=self.parse_selected_table.yview
        )
        self.parse_selected_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.parse_selected_table.configure(yscrollcommand=self.parse_selected_scroll.set)
        self.parse_selected_table.insert(tk.END, "（未选择任务）")

        ttk.Label(right, text="选段策略", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(10, 0))
        tmpl_row = ttk.Frame(right)
        tmpl_row.pack(fill=tk.X, pady=(4, 0))
        self.prompt_templates = {
            "默认爆点": (
                "优先找：冲突、反转、情绪高点、信息密度高、能独立看懂的片段；"
                "优先完整观点或完整事件单元，避免掐头去尾；"
                "优先有明确起承转合（铺垫→爆点→结论）的段落；"
                "优先金句、结论句、态度鲜明句、争议点；"
                "尽量避开寒暄、口头禅、重复表达、空洞过渡。"
            ),
            "搞笑吐槽": "优先找：包袱、夸张吐槽、节奏密集的互怼、反转笑点。",
            "吃瓜爆料": "优先找：关键人物/事件点名、爆料细节、冲突升级、结论金句。",
            "干货教程": "优先找：定义/结论/步骤/举例，信息密度高且能独立看懂的一段。",
        }
        self.template_choice = tk.StringVar(value="默认爆点")
        self.template_combo = ttk.Combobox(
            tmpl_row,
            textvariable=self.template_choice,
            values=list(self.prompt_templates.keys()),
            state="readonly",
            width=18,
        )
        self.template_combo.pack(side=tk.LEFT)
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_prompt_template())

        self.strategy_text = scrolledtext.ScrolledText(right, height=10, wrap=tk.WORD)
        self.strategy_text.pack(fill=tk.BOTH, expand=False, pady=(6, 0))
        self._apply_prompt_template()

        opts = ttk.Frame(right)
        opts.pack(fill=tk.X, pady=(8, 0))
        self.clip_max_clips = tk.StringVar(value="6")
        self.clip_min_sec = tk.StringVar(value="20")
        self.clip_max_sec = tk.StringVar(value="60")
        self.clip_chunk_min = tk.StringVar(value="30")
        self.clip_chunk_retries = tk.StringVar(value="2")
        self.clip_rule_fallback = tk.BooleanVar(value=False)

        ttk.Label(opts, text="max").grid(row=0, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.clip_max_clips, width=6).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(opts, text="min秒").grid(row=0, column=2, sticky="w")
        ttk.Entry(opts, textvariable=self.clip_min_sec, width=6).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Label(opts, text="max秒").grid(row=0, column=4, sticky="w")
        ttk.Entry(opts, textvariable=self.clip_max_sec, width=6).grid(row=0, column=5, sticky="w", padx=(4, 12))
        ttk.Label(opts, text="分段(分)").grid(row=0, column=6, sticky="w")
        ttk.Entry(opts, textvariable=self.clip_chunk_min, width=6).grid(row=0, column=7, sticky="w", padx=(4, 12))
        ttk.Label(opts, text="重试").grid(row=0, column=8, sticky="w")
        ttk.Entry(opts, textvariable=self.clip_chunk_retries, width=6).grid(row=0, column=9, sticky="w", padx=(4, 12))
        ttk.Checkbutton(opts, text="失败规则兜底", variable=self.clip_rule_fallback).grid(row=0, column=10, sticky="w", padx=(8, 0))

        clip_btns = ttk.Frame(right)
        clip_btns.pack(fill=tk.X, pady=(8, 0))
        self.clip_run_btn = ttk.Button(clip_btns, text="开始切片", command=self._run_clip)
        self.clip_run_btn.pack(side=tk.LEFT)
        self.clip_cancel_btn = ttk.Button(clip_btns, text="取消切片", command=self._cancel_clip, state=tk.DISABLED)
        self.clip_cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(clip_btns, text="清空解析日志", command=self._clear_parse_log).pack(side=tk.LEFT, padx=(8, 0))

        parse_log_frame = ttk.LabelFrame(right, text="解析日志")
        parse_log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.parse_log = scrolledtext.ScrolledText(parse_log_frame, height=10)
        self.parse_log.pack(fill=tk.BOTH, expand=True)

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.out_dir_var.set(path)
            self.refresh_parse_tasks()

    def _pick_local_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("所有文件", "*.*"),
            ],
        )
        if files:
            self.local_files = list(files)
            self.local_list.delete(0, tk.END)
            for f in self.local_files:
                self.local_list.insert(tk.END, f)

    def _refresh_mode(self) -> None:
        mode = self.mode_var.get()
        if mode == "local":
            self.local_frame.grid()
            self.url_frame.grid_remove()
        else:
            self.url_frame.grid()
            self.local_frame.grid_remove()

    def _clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def _clear_parse_log(self) -> None:
        self.parse_log.delete("1.0", tk.END)

    def _parse_log(self, msg: str) -> None:
        self.parse_log.insert(tk.END, msg + "\n")
        self.parse_log.see(tk.END)

    def _log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _refresh_cost_summary(self) -> None:
        hours = float(self.usage_stats["total_seconds"]) / 3600.0
        asr_cost = float(self.usage_stats.get("total_cost_cny", 0.0))
        clip_cost = float(self.usage_stats.get("clip_cost_cny", 0.0))
        all_cost = asr_cost + clip_cost
        self.cost_summary_var.set(
            "累计已消耗费用："
            f"¥{all_cost:.6f}（转写¥{asr_cost:.6f} + 解析¥{clip_cost:.6f}）    "
            f"(累计时长 {hours:.3f}h, "
            f"累计任务 {int(self.usage_stats['total_jobs'])} + 解析 {int(self.usage_stats.get('clip_jobs', 0.0))})"
        )

    def _tick_logs(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.insert(tk.END, msg + "\n")
                self.log.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(120, self._tick_logs)

    def _validate(self) -> tuple[bool, list[str]]:
        api_key = self.api_key_var.get().strip()
        if not api_key.startswith("sk-"):
            messagebox.showerror("参数错误", "请在 .env 中填写正确的 DASHSCOPE_API_KEY=sk-...")
            return False, []

        mode = self.mode_var.get()
        if mode == "local":
            if not self.local_files:
                messagebox.showerror("参数错误", "请至少选择一个本地视频文件。")
                return False, []
            items = self.local_files
        else:
            lines = [x.strip() for x in self.url_text.get("1.0", tk.END).splitlines()]
            items = [x for x in lines if x]
            if not items:
                messagebox.showerror("参数错误", "请至少填写一个视频 URL。")
                return False, []

        return True, items

    def _run(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在执行", "当前任务还在运行，请稍后。")
            return
        if self.clip_worker and self.clip_worker.is_alive():
            messagebox.showinfo("正在切片", "解析页正在切片，请稍后。")
            return

        ok, items = self._validate()
        if not ok:
            return

        self.cancel_event.clear()
        self.pause_event.clear()
        self.pause_btn.configure(state=tk.NORMAL, text="暂停")
        self.cancel_btn.configure(state=tk.NORMAL)
        self.run_btn.configure(state=tk.DISABLED)
        self._log("开始执行...")
        self.worker = threading.Thread(target=self._run_job, args=(items,), daemon=True)
        self.worker.start()

    def _toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.configure(text="暂停")
            self._log("已继续。")
        else:
            self.pause_event.set()
            self.pause_btn.configure(text="继续")
            self._log("已暂停（下载/轮询阶段会等待继续）。")

    def _cancel_run(self) -> None:
        self.cancel_event.set()
        self.pause_event.clear()
        self._log("已请求取消…")

    def _run_job(self, items: list[str]) -> None:
        try:
            mode = self.mode_var.get()
            args = argparse_namespace(
                api_key=self.api_key_var.get().strip(),
                out_dir=Path(self.out_dir_var.get().strip() or "runs"),
                poll_interval=int(self.poll_var.get().strip() or "2"),
                timeout=int(self.timeout_var.get().strip() or "900"),
                mode=mode,
                videos=items if mode == "local" else None,
                urls=items if mode == "url" else None,
            )

            self._log(f"模式: {mode}，条目数: {len(items)}")
            sink = QueueWriter(self._log)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                if mode == "local":
                    summary = pipeline_main.run_local(
                        args, cancel_event=self.cancel_event, pause_event=self.pause_event
                    )
                else:
                    summary = pipeline_main.run_url(
                        args, cancel_event=self.cancel_event, pause_event=self.pause_event
                    )

            self.usage_stats["total_cost_cny"] += float(summary.get("total_cost_cny", 0.0))
            self.usage_stats["total_seconds"] += float(summary.get("total_seconds", 0.0))
            self.usage_stats["total_jobs"] += float(summary.get("processed_count", 0.0))
            save_usage_stats(self.stats_path, self.usage_stats)
            self.root.after(0, self._refresh_cost_summary)
            if self.cancel_event.is_set():
                self._log("已取消（未处理完的条目已跳过）。")
            else:
                self._log("全部完成。")
            self.root.after(0, self.refresh_parse_tasks)
        except Exception as exc:
            self._log(f"失败: {exc}")
        finally:
            self.pause_event.clear()

            def _reset_controls() -> None:
                self.run_btn.configure(state=tk.NORMAL)
                self.pause_btn.configure(state=tk.DISABLED, text="暂停")
                self.cancel_btn.configure(state=tk.DISABLED)

            self.root.after(0, _reset_controls)

    def refresh_parse_tasks(self) -> None:
        out_root = Path(self.out_dir_var.get().strip() or "runs").resolve()
        self.parse_tasks = []
        if not out_root.exists():
            self.parse_list.delete(0, tk.END)
            return
        manifests = sorted(out_root.rglob(pipeline_main.MANIFEST_NAME), key=lambda p: p.stat().st_mtime, reverse=True)
        for m in manifests:
            if "_url_tmp" in m.parts or "_audio_tmp" in m.parts:
                continue
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except Exception:
                continue
            task_dir = m.parent
            title = str(data.get("task_name") or task_dir.name)
            self.parse_tasks.append(
                {
                    "title": title,
                    "dir": str(task_dir),
                    "manifest": str(m),
                    "result_json": str(data.get("result_json") or (task_dir / "result.json")),
                    "local_video": str(data.get("local_video") or ""),
                    "local_audio": str(data.get("local_audio") or ""),
                    "source_url": str(data.get("source_url") or ""),
                    "mode": str(data.get("mode") or ""),
                }
            )

        self.parse_list.delete(0, tk.END)
        for t in self.parse_tasks:
            self.parse_list.insert(tk.END, t["title"])

    def _resolve_clip_video_for_task(self, task: dict) -> str:
        """manifest.local_video → 任务目录内 source.*（B 站新流程）。"""
        lv = (task.get("local_video") or "").strip()
        if lv:
            p = Path(lv)
            if p.is_file():
                return str(p.resolve())
        found = pipeline_main.find_merged_source_video(Path(task["dir"]))
        if found:
            return str(found.resolve())
        return ""

    def _on_parse_select(self, _evt=None) -> None:
        idxs = self.parse_list.curselection()
        self.parse_selected_table.delete(0, tk.END)
        if not idxs:
            self.parse_selected_table.insert(tk.END, "（未选择任务）")
            return
        tasks = [self.parse_tasks[int(i)] for i in idxs]
        for t in tasks:
            self.parse_selected_table.insert(tk.END, str(t.get("title") or "未命名任务"))

    def _open_selected_task_dir(self) -> None:
        idxs = self.parse_list.curselection()
        if not idxs:
            messagebox.showinfo("提示", "请先选择一个任务。")
            return
        task = self.parse_tasks[int(idxs[0])]
        d = Path(task["dir"])
        try:
            os.startfile(d)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showerror("错误", f"无法打开目录：{d}")

    def _apply_prompt_template(self) -> None:
        name = self.template_choice.get()
        body = self.prompt_templates.get(name, self.prompt_templates["默认爆点"])
        self.strategy_text.delete("1.0", tk.END)
        self.strategy_text.insert(tk.END, body)

    def _cancel_clip(self) -> None:
        self.clip_cancel_event.set()
        self._parse_log("已请求取消切片…")

    def _run_clip(self) -> None:
        if self.clip_worker and self.clip_worker.is_alive():
            messagebox.showinfo("正在切片", "切片任务还在运行。")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在转写", "转写任务还在运行，请稍后再切片。")
            return

        idxs = self.parse_list.curselection()
        if not idxs:
            messagebox.showinfo("提示", "请先在左侧选择一个已完成任务。")
            return
        selected_tasks = [self.parse_tasks[int(i)] for i in idxs]

        api_key = self.api_key_var.get().strip()
        if not api_key.startswith("sk-"):
            messagebox.showerror("错误", "需要有效的 sk- API Key。")
            return

        try:
            max_clips = int(self.clip_max_clips.get().strip())
            min_sec = int(self.clip_min_sec.get().strip())
            max_sec = int(self.clip_max_sec.get().strip())
            chunk_min = int(self.clip_chunk_min.get().strip())
            chunk_retries = int(self.clip_chunk_retries.get().strip())
        except Exception:
            messagebox.showerror("错误", "切片参数必须是整数。")
            return

        strategy = self.strategy_text.get("1.0", tk.END).strip()

        self.clip_cancel_event.clear()
        self.clip_run_btn.configure(state=tk.DISABLED)
        self.clip_cancel_btn.configure(state=tk.NORMAL)

        def job() -> None:
            ok_count = 0
            total_cost = 0.0
            try:
                sink = QueueWriter(self._parse_log)
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    for i, task in enumerate(selected_tasks, start=1):
                        title = task.get("title") or f"任务{i}"
                        transcript = Path(task["result_json"])
                        video_s = self._resolve_clip_video_for_task(task)
                        video = Path(video_s) if video_s else Path()
                        out_dir = Path(task["dir"]) / "clip_output"

                        if not transcript.is_file():
                            self._parse_log(f"[{i}/{len(selected_tasks)}] {title} 跳过：找不到 result.json")
                            continue
                        if not video.is_file():
                            self._parse_log(f"[{i}/{len(selected_tasks)}] {title} 跳过：找不到本地视频")
                            continue

                        self._parse_log(f"[{i}/{len(selected_tasks)}] 开始：{title}")
                        _outputs, clip_cost = clipper.run_auto_clip(
                            video=video,
                            transcript_json=transcript,
                            out_dir=out_dir,
                            api_key=api_key,
                            max_clips=max_clips,
                            min_sec=min_sec,
                            max_sec=max_sec,
                            chunk_minutes=chunk_min,
                            chunk_retries=chunk_retries,
                            rule_fallback_after_retries=bool(self.clip_rule_fallback.get()),
                            strategy_instructions=strategy or None,
                            custom_user_prompt=None,
                        )
                        total_cost += float(clip_cost)
                        ok_count += 1
                        self._parse_log(f"[{i}/{len(selected_tasks)}] 完成：{title}")
                self.usage_stats["clip_cost_cny"] = float(self.usage_stats.get("clip_cost_cny", 0.0)) + total_cost
                self.usage_stats["clip_jobs"] = float(self.usage_stats.get("clip_jobs", 0.0)) + float(ok_count)
                save_usage_stats(self.stats_path, self.usage_stats)
                self.root.after(0, self._refresh_cost_summary)
                self._parse_log(f"批量切片完成：成功 {ok_count}/{len(selected_tasks)}。")
            except Exception as exc:
                self._parse_log(f"切片失败: {exc}")
            finally:

                def _reset() -> None:
                    self.clip_run_btn.configure(state=tk.NORMAL)
                    self.clip_cancel_btn.configure(state=tk.DISABLED)

                self.root.after(0, _reset)

        self.clip_worker = threading.Thread(target=job, daemon=True)
        self.clip_worker.start()


def argparse_namespace(**kwargs):
    class NS:
        pass

    ns = NS()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


class QueueWriter:
    def __init__(self, logger_func) -> None:
        self.logger_func = logger_func
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.logger_func(line)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self.logger_func(self._buf.strip())
        self._buf = ""


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
