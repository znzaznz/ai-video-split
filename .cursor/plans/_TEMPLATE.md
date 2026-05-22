# [计划标题]

> **用法（Plan Mode + 本仓库）**
> 1. Cursor 里 `Shift+Tab` 进 Plan，描述功能；回答澄清问题。
> 2. 生成计划后 **人工改** 下文各节，再点 Build。
> 3. 点 **Save to Workspace** → 保存到 `.cursor/plans/YYYY-MM-DD-简短描述.md`（可进 Git）。
> 4. **不要一次 Build 全部 TODO**：按「阶段」分组 Build；每阶段结束跑「本阶段验收」，再开下一阶段或新 Agent。
> 5. 架构/方案拿不准 → 新开 **Ask** 会话问清，把结论写入「关键决策」。
> 6. 全文 Build 完成前须勾选文末 **交付勾选**。

参考：[Engincan Veske — How I Use Cursor Plan Mode](https://engincanveske.substack.com/p/how-i-use-cursor-plan-mode-for-real)

---

## 需求来源（可选）

- 对话说明 / 本地 issue 摘要：
- 样例数据路径（如 `runs/.../result.json`）：
- 相关 GitHub Issue（若有）：

---

## 目标

（本计划要达成什么，1～3 句；用户可感知的结果。）

---

## 范围

### 涉及

- 文件/模块：

### 不在本次

-

### 优先级

| 优先级 | 内容 | 放在哪一阶段 |
|--------|------|----------------|
| **核心（必做）** | | 阶段 1 |
| **增强（nice-to-have）** | | 阶段 2（阶段 1 跑通后再做） |

> 先写清核心，不要把 edge case / 美化一口气塞进阶段 1。

---

## 架构（可选）

```mermaid
flowchart LR
  A[输入] --> B[处理]
  B --> C[输出]
```

（复杂改动再画；简单任务可删本节。）

---

## 实施节奏

- [ ] **阶段 1 — 核心**：TODO 见下；本阶段结束必须跑「阶段 1 验收」且主路径可运行。
- [ ] **阶段 2 — 增强**（可选）：核心勾选完成后再 Build；可新开 Agent 并 `@` 本 plan 文件。

**禁止**：一次 Build 勾选全部 TODO。偏离实现时在本文件追加「关键决策」，勿只在聊天里口头说。

---

## 阶段 1 — 核心 TODO

> 每条实现后都要有可验证项（不要只写「实现 X」）。

- [ ] **1.1** （实现项）
  - 验证：（命令 / 界面行为 / 输出路径）
- [ ] **1.2**
  - 验证：
- [ ] **1.3**
  - 验证：

### 阶段 1 验收（Agent 必跑）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
```

按需追加（在对应项打勾）：

- [ ] `python scripts/smoke_test_transcript.py`（转写/管线）
- [ ] `python tools/doctor.py` 或 `python transcript_cli.py --doctor`（抖音/yt-dlp）
- [ ] `build_exe.ps1`（改了打进 `视频切片机.exe` 的源码；先关旧 exe）
- [ ] `transcript_app/build_transcript_exe.ps1`（改了打进 `视频转写纠错.exe` 的源码）
- [ ] 启动**新生成** exe 或 `python gui.py` / `transcript_gui` 走通主路径

### 阶段 1 完成标准

（行为、输出路径、与 `result.json` / GUI 的可见变化。）

---

## 阶段 2 — 增强 TODO（可选）

- [ ] **2.1**
  - 验证：
- [ ] **2.2**
  - 验证：

### 阶段 2 验收

（可复用阶段 1 命令；仅补本轮改动相关项。）

---

## 关键决策（实施过程中追加）

| 日期 | 决策 | 原因 |
|------|------|------|
| | | |

（Build 中发现方案变更时写一行，保持 plan 与代码一致。）

---

## 总体验收标准

（全部阶段完成后，怎样算「做完」。）

---

## 交付勾选（全部阶段 / Plan 宣称完成前必过）

对照 [.cursor/rules/plan-done-checklist.mdc](../rules/plan-done-checklist.mdc) 与 [ship-workflow.mdc](../rules/ship-workflow.mdc)。未勾完不得宣称交付完成。

### 代码联动

- [ ] 改 `slice_logic` / `slice_strategy` / `auto_clip` → 已查 `gui.py`、`main.py` 调用与参数一致
- [ ] 改 `run_auto_clip` / `execute_slice_pipeline` 等签名 → 已 grep 全部调用方
- [ ] 删变量/函数/参数 → 已全仓库 grep，无残留引用
- [ ] 新增核心 `.py` → 已加入 `scripts/verify.ps1` 的 `$modules`
- [ ] 新增 Python 依赖 → 已更新 `requirements.txt` 与 `build_exe.ps1`（`--hidden-import` 等）

### 验收与打包

- [ ] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1` 通过
- [ ] Agent 已按 [execute-dont-preach.mdc](../rules/execute-dont-preach.mdc) 跑过 smoke/E2E（非只写教程）
- [ ] 若本轮修改打进 `视频切片机.exe` 的源码 → 已跑 `build_exe.ps1`（先关闭正在运行的 exe）
- [ ] 若本轮修改打进 `视频转写纠错.exe` 的源码 → 已跑 `transcript_app/build_transcript_exe.ps1`
- [ ] 已用**新生成**的 exe 或 `python gui.py` 走通主路径（勿用旧 exe）

### Git 安全

- [ ] `git status` + `git diff --cached --name-only` 无 `.env`、`.env.local`、`__pycache__/`、`runs/`、`build/`、`dist/`、`*.exe`
- [ ] 未使用 `git add -A` / `git add .`；只 add 明确路径
- [ ] 仅在你明确要求时 `git commit`；**不自动** `git push`

### 文档（若本轮改了行为或配置）

- [ ] `.env.example` / README 与实现一致

### 可选：听书壳 / 新产品线（仅相关计划勾选）

- [ ] 新模块与切片流水线隔离，未硬塞进 `run_auto_clip`
- [ ] GUI 新 Tab 或独立入口；`verify.ps1` 已含新模块

---

## 完成记录

- 完成日期：
- 已 Build 阶段：1 / 2
- 备注（已知限制、待办）：
