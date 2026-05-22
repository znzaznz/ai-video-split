# 抖音链接排障剧本

按顺序执行，**不要**在 `douyin_simulate` 未通过前跑完整转写（避免 DashScope 白花钱）。

## 1. 一键预检

```powershell
cd c:\code\video-to-word
python tools/doctor.py
python tools/doctor.py --url "你的抖音链接"
```

看 JSON 里 `douyin_simulate.ok` 是否为 `true`。

Electron 预检同款：

```powershell
python tools/doctor.py --douyin-only --json --url "你的抖音链接"
```

## 2. Electron 内置登录（推荐）

1. `cd transcript_app\chat-ui` → `npm install` → `npm run dev`
2. 「解析视频」粘贴抖音链接或分享文案
3. 预检失败时在内置窗口登录 douyin.com，点「继续解析」
4. Cookie 写入仓库根 `cookies.txt` 后自动预检

## 3. 手动 cookies.txt

1. 浏览器登录 douyin.com，打开目标视频
2. 扩展「Get cookies.txt LOCALLY」导出 Netscape 格式到仓库根 `cookies.txt`
3. `.env` 设置 `YT_DLP_COOKIES=cookies.txt`（勿依赖 `YT_DLP_COOKIES_FROM_BROWSER`，Windows 易 DPAPI 失败）

## 4. 转写命令

```powershell
python transcript_cli.py "分享文案或链接"
```

或 Tk / 切片机共用 `runs/` 输出目录。
