#!/usr/bin/env python3
"""Standalone GUI: video/URL -> ASR -> transcript correction."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk


def _ensure_repo_on_path() -> Path:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


_ensure_repo_on_path()

import transcript_correct as tc  # noqa: E402
import transcript_pipeline as tp  # noqa: E402

QueueWriter = tp.QueueWriter
argparse_namespace = tp.argparse_namespace


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("视频转写纠错")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.correct_worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.stats_path = tp.resolve_transcript_stats_path()
        self.usage_stats = tp.load_transcript_usage_stats(self.stats_path)
        self.cost_summary_var = tk.StringVar()
        self._refresh_cost_summary()

        tp.apply_dotenv_to_environ()
        env = tp.find_env_values()
        self.mode_var = tk.StringVar(value="local")
        self.api_key_var = tk.StringVar(value=env.get("DASHSCOPE_API_KEY", ""))
        self.out_dir_var = tk.StringVar(
            value=str(Path(env.get("OUTPUT_DIR", "runs")).resolve())
        )
        self.poll_var = tk.StringVar(value=env.get("POLL_INTERVAL", "2"))
        self.timeout_var = tk.StringVar(value=env.get("TIMEOUT", "900"))
        self.keywords_var = tk.StringVar(value=env.get("TRANSCRIPT_KEYWORDS", ""))
        self.llm_correct_var = tk.BooleanVar(value=env.get("TRANSCRIPT_LLM_CORRECT", "1") != "0")

        self.local_files: list[str] = []
        self.tasks: list[dict[str, str]] = []

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
            tp.save_env_key(self.api_key_var.get())

        self._build_ui()
        self._tick_logs()
        self.refresh_tasks()

    def _build_ui(self) -> None:
        self.root.geometry("1024x720")

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, textvariable=self.cost_summary_var, foreground="#0b6a0b").pack(
            anchor="w", pady=(0, 6)
        )

        paned = ttk.Panedwindow(outer, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(paned, padding=4)
        bottom = ttk.Frame(paned, padding=4)
        paned.add(top, weight=3)
        paned.add(bottom, weight=1)

        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="模式:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            frm, text="本地视频", value="local", variable=self.mode_var, command=self._refresh_mode
        ).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            frm, text="视频链接", value="url", variable=self.mode_var, command=self._refresh_mode
        ).grid(row=0, column=2, sticky="w")

        ttk.Label(frm, text="输出目录:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.out_dir_var, width=70).grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=4
        )
        ttk.Button(frm, text="选择", command=self._pick_out_dir).grid(row=1, column=4, sticky="ew")

        ttk.Label(frm, text="轮询间隔(s):").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.poll_var, width=10).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="超时(s):").grid(row=2, column=2, sticky="e")
        ttk.Entry(frm, textvariable=self.timeout_var, width=10).grid(row=2, column=3, sticky="w")

        ttk.Label(frm, text="本期关键词:").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(frm, textvariable=self.keywords_var, width=70).grid(
            row=3, column=1, columnspan=3, sticky="ew", pady=(4, 0)
        )
        ttk.Checkbutton(frm, text="转写后 AI 纠错", variable=self.llm_correct_var).grid(
            row=3, column=4, sticky="w", pady=(4, 0)
        )

        self.local_frame = ttk.LabelFrame(frm, text="本地视频输入")
        self.local_frame.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        ttk.Button(self.local_frame, text="选择一个或多个视频", command=self._pick_local_files).pack(
            anchor="w", pady=4
        )
        self.local_list = tk.Listbox(self.local_frame, height=5)
        self.local_list.pack(fill=tk.BOTH, expand=True)

        self.url_frame = ttk.LabelFrame(frm, text="链接输入（每行一个URL）")
        self.url_frame.grid(row=5, column=0, columnspan=5, sticky="nsew", pady=(8, 6))
        self.url_text = scrolledtext.ScrolledText(self.url_frame, height=5)
        self.url_text.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=5, sticky="ew", pady=(6, 6))
        self.run_btn = ttk.Button(btns, text="开始转写", command=self._run)
        self.run_btn.pack(side=tk.LEFT)
        self.pause_btn = ttk.Button(btns, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.cancel_btn = ttk.Button(btns, text="取消", command=self._cancel_run, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(frm, text="运行日志")
        log_frame.grid(row=7, column=0, columnspan=5, sticky="nsew", pady=(6, 0))
        self.log = scrolledtext.ScrolledText(log_frame, height=10)
        self.log.pack(fill=tk.BOTH, expand=True)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)
        frm.columnconfigure(3, weight=1)
        frm.rowconfigure(4, weight=1)
        frm.rowconfigure(5, weight=1)
        frm.rowconfigure(7, weight=2)
        self._refresh_mode()

        ttk.Label(bottom, text="已完成任务").pack(anchor="w")
        task_btns = ttk.Frame(bottom)
        task_btns.pack(fill=tk.X, pady=(4, 4))
        ttk.Button(task_btns, text="刷新", command=self.refresh_tasks).pack(side=tk.LEFT)
        ttk.Button(task_btns, text="打开目录", command=self._open_selected_task_dir).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(task_btns, text="仅重跑纠错", command=self._rerun_correction).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(task_btns, text="删除任务", command=self._delete_selected_tasks).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self.task_list = tk.Listbox(bottom, height=6, exportselection=False, selectmode=tk.EXTENDED)
        self.task_list.pack(fill=tk.BOTH, expand=True)

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.out_dir_var.set(path)
            self.refresh_tasks()

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
        if self.mode_var.get() == "local":
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
        self.cost_summary_var.set(tp.format_transcript_cost_summary(self.usage_stats))

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
        if not self.api_key_var.get().strip().startswith("sk-"):
            messagebox.showerror("参数错误", "请在 .env 中填写正确的 DASHSCOPE_API_KEY=sk-...")
            return False, []
        mode = self.mode_var.get()
        if mode == "local":
            if not self.local_files:
                messagebox.showerror("参数错误", "请至少选择一个本地视频文件。")
                return False, []
            return True, self.local_files
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
        if self.correct_worker and self.correct_worker.is_alive():
            messagebox.showinfo("正在纠错", "纠错任务还在运行，请稍后。")
            return
        ok, items = self._validate()
        if not ok:
            return

        self.cancel_event.clear()
        self.pause_event.clear()
        self.pause_btn.configure(state=tk.NORMAL, text="暂停")
        self.cancel_btn.configure(state=tk.NORMAL)
        self.run_btn.configure(state=tk.DISABLED)
        self._log("开始转写...")
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
            self._log("已暂停。")

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
                user_keywords=self.keywords_var.get().strip(),
                no_llm_correct=not bool(self.llm_correct_var.get()),
                mode=mode,
                videos=items if mode == "local" else None,
                urls=items if mode == "url" else None,
            )
            self._log(f"模式: {mode}，条目数: {len(items)}")
            sink = QueueWriter(self._log)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                if mode == "local":
                    summary = tp.run_local(
                        args,
                        cancel_event=self.cancel_event,
                        pause_event=self.pause_event,
                        copy_video_to_task=False,
                    )
                else:
                    summary = tp.run_url(
                        args, cancel_event=self.cancel_event, pause_event=self.pause_event
                    )

            self.usage_stats["asr_cost_cny"] += float(summary.get("asr_cost_cny", 0.0))
            self.usage_stats["llm_correct_cost_cny"] += float(
                summary.get("llm_correct_cost_cny", 0.0)
            )
            self.usage_stats["total_cost_cny"] = (
                self.usage_stats["asr_cost_cny"] + self.usage_stats["llm_correct_cost_cny"]
            )
            self.usage_stats["total_seconds"] += float(summary.get("total_seconds", 0.0))
            self.usage_stats["total_jobs"] += float(summary.get("processed_count", 0.0))
            tp.save_transcript_usage_stats(self.stats_path, self.usage_stats)
            self.root.after(0, self._refresh_cost_summary)
            if self.cancel_event.is_set():
                self._log("已取消。")
            else:
                self._log("全部完成。")
            self.root.after(0, self.refresh_tasks)
        except Exception as exc:
            self._log(f"失败: {exc}")
        finally:
            self.pause_event.clear()

            def _reset() -> None:
                self.run_btn.configure(state=tk.NORMAL)
                self.pause_btn.configure(state=tk.DISABLED, text="暂停")
                self.cancel_btn.configure(state=tk.DISABLED)

            self.root.after(0, _reset)

    def refresh_tasks(self) -> None:
        out_root = Path(self.out_dir_var.get().strip() or "runs").resolve()
        self.tasks = []
        if not out_root.exists():
            self.task_list.delete(0, tk.END)
            return
        manifests = sorted(
            out_root.rglob(tp.MANIFEST_NAME),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for m in manifests:
            if "_url_tmp" in m.parts or "_audio_tmp" in m.parts:
                continue
            task_dir = m.parent
            if not (task_dir / "result.json").is_file():
                continue
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            title = str(data.get("task_name") or task_dir.name)
            self.tasks.append({"title": title, "dir": str(task_dir)})

        self.task_list.delete(0, tk.END)
        for t in self.tasks:
            self.task_list.insert(tk.END, t["title"])

    def _open_selected_task_dir(self) -> None:
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showinfo("提示", "请先选择一个任务。")
            return
        d = Path(self.tasks[int(idxs[0])]["dir"])
        try:
            os.startfile(d)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showerror("错误", f"无法打开目录：{d}")

    def _delete_selected_tasks(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在转写", "转写进行中，请完成或取消后再删除。")
            return
        if self.correct_worker and self.correct_worker.is_alive():
            messagebox.showinfo("正在纠错", "纠错进行中，请稍后再删除。")
            return
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showinfo("提示", "请选择要删除的任务。")
            return
        selected = [self.tasks[int(i)] for i in idxs]
        if not messagebox.askyesno("确认删除", f"将删除 {len(selected)} 个任务目录，无法恢复。确定？"):
            return
        out_root = Path(self.out_dir_var.get().strip() or "runs").resolve()
        for t in selected:
            task_dir = Path(t["dir"]).resolve()
            try:
                task_dir.relative_to(out_root)
                shutil.rmtree(task_dir)
            except Exception as exc:
                self._log(f"删除失败 {task_dir.name}: {exc}")
        self.refresh_tasks()

    def _rerun_correction(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在转写", "请先完成或取消转写。")
            return
        if self.correct_worker and self.correct_worker.is_alive():
            messagebox.showinfo("正在纠错", "纠错任务还在运行。")
            return
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showinfo("提示", "请选择一个已有 result.json 的任务。")
            return
        api_key = self.api_key_var.get().strip()
        if not api_key.startswith("sk-"):
            messagebox.showerror("错误", "需要有效的 sk- API Key。")
            return
        tasks = [self.tasks[int(i)] for i in idxs]
        kw = self.keywords_var.get().strip()
        enable_llm = bool(self.llm_correct_var.get())

        self._log(f"仅重跑纠错：{len(tasks)} 个任务…")
        self.correct_worker = threading.Thread(
            target=self._correct_job,
            args=(tasks, api_key, kw, enable_llm),
            daemon=True,
        )
        self.correct_worker.start()

    def _correct_job(
        self, tasks: list[dict[str, str]], api_key: str, keywords: str, enable_llm: bool
    ) -> None:
        try:
            sink = QueueWriter(self._log)
            extra_llm = 0.0
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                for t in tasks:
                    task_dir = Path(t["dir"])
                    sentences = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
                    if not isinstance(sentences, list):
                        raise RuntimeError(f"{task_dir.name} result.json 格式错误")
                    _, cost = tc.run_post_asr_correction(
                        api_key=api_key,
                        output_dir=task_dir,
                        sentences=sentences,
                        task_title=t["title"],
                        user_keywords=keywords,
                        enable_llm=enable_llm,
                    )
                    extra_llm += float(cost)
            self.usage_stats["llm_correct_cost_cny"] += extra_llm
            self.usage_stats["total_cost_cny"] = (
                self.usage_stats["asr_cost_cny"] + self.usage_stats["llm_correct_cost_cny"]
            )
            tp.save_transcript_usage_stats(self.stats_path, self.usage_stats)
            self.root.after(0, self._refresh_cost_summary)
            self._log("纠错完成。")
            self.root.after(0, self.refresh_tasks)
        except Exception as exc:
            self._log(f"纠错失败: {exc}")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
