#!/usr/bin/env python3
"""
Simple desktop GUI for video-to-text pipeline.
"""

from __future__ import annotations

import contextlib
import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import main as pipeline_main


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
        return {"total_cost_cny": 0.0, "total_seconds": 0.0, "total_jobs": 0.0}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        return {
            "total_cost_cny": float(data.get("total_cost_cny", 0.0)),
            "total_seconds": float(data.get("total_seconds", 0.0)),
            "total_jobs": float(data.get("total_jobs", 0.0)),
        }
    except Exception:
        return {"total_cost_cny": 0.0, "total_seconds": 0.0, "total_jobs": 0.0}


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
        self.root.geometry("860x620")

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

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm,
            textvariable=self.cost_summary_var,
            foreground="#0b6a0b",
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))

        ttk.Label(frm, text="模式:").grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(frm, text="本地视频", value="local", variable=self.mode_var, command=self._refresh_mode).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Radiobutton(frm, text="视频链接", value="url", variable=self.mode_var, command=self._refresh_mode).grid(
            row=1, column=2, sticky="w"
        )

        ttk.Label(frm, text="输出目录:").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.out_dir_var, width=70).grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(frm, text="选择", command=self._pick_out_dir).grid(row=2, column=4, sticky="ew")

        ttk.Label(frm, text="轮询间隔(s):").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.poll_var, width=10).grid(row=3, column=1, sticky="w")
        ttk.Label(frm, text="超时(s):").grid(row=3, column=2, sticky="e")
        ttk.Entry(frm, textvariable=self.timeout_var, width=10).grid(row=3, column=3, sticky="w")

        self.local_frame = ttk.LabelFrame(frm, text="本地视频输入")
        self.local_frame.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        ttk.Button(self.local_frame, text="选择一个或多个视频", command=self._pick_local_files).pack(anchor="w", pady=4)
        self.local_list = tk.Listbox(self.local_frame, height=6)
        self.local_list.pack(fill=tk.BOTH, expand=True)

        self.url_frame = ttk.LabelFrame(frm, text="链接输入（每行一个URL）")
        self.url_frame.grid(row=5, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        self.url_text = scrolledtext.ScrolledText(self.url_frame, height=7)
        self.url_text.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=5, sticky="ew", pady=(6, 6))
        self.run_btn = ttk.Button(btns, text="开始执行", command=self._run)
        self.run_btn.pack(side=tk.LEFT)
        self.pause_btn = ttk.Button(btns, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.cancel_btn = ttk.Button(btns, text="取消", command=self._cancel_run, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(frm, text="运行日志")
        log_frame.grid(row=7, column=0, columnspan=5, sticky="nsew", pady=(6, 0))
        self.log = scrolledtext.ScrolledText(log_frame, height=14)
        self.log.pack(fill=tk.BOTH, expand=True)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)
        frm.columnconfigure(3, weight=1)
        frm.rowconfigure(4, weight=1)
        frm.rowconfigure(5, weight=1)
        frm.rowconfigure(7, weight=2)

        self._refresh_mode()

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.out_dir_var.set(path)

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

    def _log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _refresh_cost_summary(self) -> None:
        hours = float(self.usage_stats["total_seconds"]) / 3600.0
        self.cost_summary_var.set(
            "累计已消耗费用："
            f"¥{self.usage_stats['total_cost_cny']:.6f}    "
            f"(累计时长 {hours:.3f}h, "
            f"累计任务 {int(self.usage_stats['total_jobs'])})"
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
        except Exception as exc:
            self._log(f"失败: {exc}")
        finally:
            self.pause_event.clear()

            def _reset_controls() -> None:
                self.run_btn.configure(state=tk.NORMAL)
                self.pause_btn.configure(state=tk.DISABLED, text="暂停")
                self.cancel_btn.configure(state=tk.DISABLED)

            self.root.after(0, _reset_controls)


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
