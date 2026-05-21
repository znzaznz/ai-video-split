# [计划标题]

> 复制本文件为 `YYYY-MM-DD-简短描述.md`，填写上方标题与下方各节；Plan Build 完成前须勾选文末 **交付勾选**。

## 目标

（本计划要达成什么，1～3 句。）

## 范围

- 涉及文件/模块：
- 不在本次范围：

## 步骤

1. 
2. 
3. 

## 验收标准

（怎样算做完：行为、输出路径、用户可感知的变化。）

---

## 交付勾选（Plan / Build 完成前必过）

对照 [.cursor/rules/plan-done-checklist.mdc](../rules/plan-done-checklist.mdc) 与 [ship-workflow.mdc](../rules/ship-workflow.mdc)。未勾完不得宣称交付完成。

### 代码联动

- [ ] 改 `slice_logic` / `slice_strategy` / `auto_clip` → 已查 `gui.py`、`main.py` 调用与参数一致
- [ ] 改 `run_auto_clip` / `execute_slice_pipeline` 等签名 → 已 grep 全部调用方
- [ ] 删变量/函数/参数 → 已全仓库 grep，无残留引用
- [ ] 新增核心 `.py` → 已加入 `scripts/verify.ps1` 的 `$modules`
- [ ] 新增 Python 依赖 → 已更新 `requirements.txt` 与 `build_exe.ps1`（`--hidden-import` 等）

### 验收与打包

- [ ] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1` 通过
- [ ] 若本轮修改打进 `视频切片机.exe` 的源码 → 已跑 `build_exe.ps1`（先关闭正在运行的 exe）
- [ ] 已用**新生成**的 `视频切片机.exe` 或 `python gui.py` 走通主路径（勿用旧 exe）

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
- 备注（已知限制、待办）：
