import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import https from "node:https";
import type { ClientRequest } from "node:http";
import fs from "node:fs";
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import type { WebContents } from "electron";
import { HttpsProxyAgent } from "https-proxy-agent";
import {
  getDouyinSessionStatus,
  isDouyinUrlLike,
  openDouyinLoginFlow,
} from "./douyinSession";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** 与 Python gemini_via_proxy.py 一致，便于本机翻墙代理 */
const PROXY_URL = "http://127.0.0.1:7890";
const DEFAULT_MODEL = "gemini-3-flash-preview";

function repoRootFromChatUi(): string {
  if (app.isPackaged) {
    return path.dirname(process.execPath);
  }
  const candidates = [
    process.cwd(),
    path.resolve(process.cwd(), ".."),
    path.resolve(process.cwd(), "../.."),
    path.resolve(process.cwd(), "../../.."),
  ];
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, "transcript_cli.py"))) {
      return dir;
    }
  }
  return path.resolve(process.cwd(), "../..");
}

function transcriptCliPy(repoRoot: string): string {
  return path.join(repoRoot, "transcript_cli.py");
}

function transcriptCliExtraArgs(): string[] {
  const mode = (process.env.TRANSCRIPT_POST_ASR_MODE || "").trim().toLowerCase();
  if (mode === "polish" || mode === "none" || mode === "correct") {
    return ["--post-asr-mode", mode];
  }
  return [];
}

function loadDotEnvKeys(): { gemini?: string } {
  const envPath = path.join(repoRootFromChatUi(), ".env");
  let gemini: string | undefined;
  if (!fs.existsSync(envPath)) return {};
  const raw = fs.readFileSync(envPath, "utf-8");
  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const [k, ...rest] = t.split("=");
    const key = k.trim();
    const v = rest.join("=").trim().replace(/^["']|["']$/g, "");
    if (key === "GEMINI_API_KEY" || key === "GOOGLE_API_KEY") gemini = v;
  }
  return { gemini };
}

const GEMINI_KEY_MISSING_MSG =
  "请先在设置中填写 Gemini API Key（或配置项目根 .env 的 GEMINI_API_KEY）。";

type UserAppSettings = { geminiApiKey?: string };

function appSettingsFilePath(): string {
  return path.join(app.getPath("userData"), "app-settings.json");
}

function readUserAppSettings(): UserAppSettings {
  try {
    const p = appSettingsFilePath();
    if (!fs.existsSync(p)) return {};
    const raw = fs.readFileSync(p, "utf-8");
    const j = JSON.parse(raw) as UserAppSettings;
    return typeof j === "object" && j !== null ? j : {};
  } catch {
    return {};
  }
}

function writeUserAppSettings(settings: UserAppSettings): void {
  fs.mkdirSync(path.dirname(appSettingsFilePath()), { recursive: true });
  fs.writeFileSync(appSettingsFilePath(), JSON.stringify(settings, null, 2), "utf-8");
}

function maskApiKey(key: string): string {
  const t = key.trim();
  if (t.length <= 8) return "****";
  return `${t.slice(0, 4)}…${t.slice(-4)}`;
}

/** userData 设置优先，其次仓库 .env，最后进程环境变量 */
function resolveGeminiApiKey(): string {
  const fromUser = readUserAppSettings().geminiApiKey?.trim();
  if (fromUser) return fromUser;
  const { gemini } = loadDotEnvKeys();
  if (gemini?.trim()) return gemini.trim();
  return (process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY || "").trim();
}

let activeGeminiRequest: ClientRequest | null = null;

function abortActiveGeminiRequest(): void {
  if (activeGeminiRequest) {
    activeGeminiRequest.destroy();
    activeGeminiRequest = null;
  }
}

function extractStreamDelta(obj: Record<string, unknown>): string {
  const candidates = (obj.candidates as Record<string, unknown>[]) || [];
  if (!candidates.length) return "";
  const parts =
    (((candidates[0]?.content as Record<string, unknown> | undefined)?.parts as Record<string, unknown>[]) ||
      []) as { text?: string }[];
  return parts.map((p) => (typeof p.text === "string" ? p.text : "")).join("");
}

/** 从整条 generateContent / stream 块里尽量抽出全部文本（多 candidate 合并） */
function extractFullTextFromResponse(obj: Record<string, unknown>): string {
  const candidates = (obj.candidates as Record<string, unknown>[]) || [];
  const chunks: string[] = [];
  for (const c of candidates) {
    const parts =
      (((c?.content as Record<string, unknown> | undefined)?.parts as Record<string, unknown>[]) ||
        []) as { text?: string }[];
    for (const p of parts) {
      if (typeof p.text === "string" && p.text) chunks.push(p.text);
    }
  }
  return chunks.join("");
}

function extractStreamError(obj: Record<string, unknown>): string | null {
  const nested = obj.error as Record<string, unknown> | undefined;
  if (nested && typeof nested.message === "string") return nested.message;
  if (typeof obj.message === "string") return obj.message;
  return null;
}

/** 单条或 JSON 数组形式的 stream 块，提取 delta；遇 API error 字段则返回 error */
function processStreamJsonValue(
  parsed: unknown,
  sender: WebContents
): { hadDelta: boolean; error?: string } {
  const list = Array.isArray(parsed) ? parsed : [parsed];
  let hadDelta = false;
  for (const item of list) {
    if (typeof item !== "object" || item === null) continue;
    const obj = item as Record<string, unknown>;
    const errMsg = extractStreamError(obj);
    if (errMsg) return { hadDelta, error: errMsg };
    const delta = extractStreamDelta(obj);
    if (delta) {
      hadDelta = true;
      sender.send("bbchat:gemini-chunk", { delta });
    }
  }
  return { hadDelta };
}

/** 非流式 generateContent，与流式解析失败时搭配使用 */
function generateContentSync(
  apiKey: string,
  body: Record<string, unknown>,
  model: string,
  timeoutMs: number
): Promise<string> {
  const base = "https://generativelanguage.googleapis.com/v1beta";
  const url = `${base}/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;
  const bodyStr = JSON.stringify(body);
  const agent = new HttpsProxyAgent(PROXY_URL);

  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = https.request(
      {
        hostname: u.hostname,
        path: u.pathname + u.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(bodyStr),
        },
        agent,
        timeout: timeoutMs,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c) => chunks.push(c as Buffer));
        res.on("end", () => {
          const raw = Buffer.concat(chunks).toString("utf-8");
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}\n${raw.slice(0, 4000)}`));
            return;
          }
          try {
            const json = JSON.parse(raw) as Record<string, unknown>;
            if (json.error) {
              reject(new Error(JSON.stringify(json.error)));
              return;
            }
            const text = extractFullTextFromResponse(json);
            if (!text.trim()) {
              reject(new Error(`无文本：${raw.slice(0, 1500)}`));
              return;
            }
            resolve(text.trim());
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("请求超时（检查代理）"));
    });
    req.write(bodyStr);
    req.end();
  });
}

/** streamGenerateContent：按行解析 JSON / SSE `data:`，向渲染进程推送 delta */
function streamGenerateToSender(
  sender: WebContents,
  apiKey: string,
  body: Record<string, unknown>,
  model: string,
  timeoutMs: number,
  signal: { canceled: boolean }
): Promise<void> {
  abortActiveGeminiRequest();
  const base = "https://generativelanguage.googleapis.com/v1beta";
  const url = `${base}/models/${encodeURIComponent(model)}:streamGenerateContent?key=${encodeURIComponent(apiKey)}&alt=sse`;
  const payload = JSON.stringify(body);
  const agent = new HttpsProxyAgent(PROXY_URL);

  return new Promise<void>((resolve) => {
    let doneSent = false;
    const finish = (payload: { ok: false; error: string } | { ok: false; canceled: true } | { ok: true }) => {
      if (doneSent) return;
      doneSent = true;
      sender.send("bbchat:gemini-done", payload);
      resolve(undefined);
    };

    const u = new URL(url);
    const req = https.request(
      {
        hostname: u.hostname,
        path: u.pathname + u.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
        agent,
        timeout: timeoutMs,
      },
      (res) => {
        let lineBuf = "";
        let rawAccum = "";
        const RAW_ACCUM_MAX = 4_000_000;
        let hadText = false;

        if (res.statusCode && res.statusCode >= 400) {
          const chunks: Buffer[] = [];
          res.on("data", (c) => chunks.push(c as Buffer));
          res.on("end", () => {
            const raw = Buffer.concat(chunks).toString("utf-8");
            finish({ ok: false, error: `HTTP ${res.statusCode}\n${raw.slice(0, 4000)}` });
          });
          return;
        }

        res.on("data", (chunk: Buffer) => {
          if (signal.canceled || doneSent) return;
          const text = chunk.toString("utf-8").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
          rawAccum += text;
          if (rawAccum.length > RAW_ACCUM_MAX) {
            rawAccum = rawAccum.slice(-RAW_ACCUM_MAX);
          }
          lineBuf += text;
          for (;;) {
            const nl = lineBuf.indexOf("\n");
            if (nl < 0) break;
            const rawLine = lineBuf.slice(0, nl);
            lineBuf = lineBuf.slice(nl + 1);
            const line = rawLine.trim();
            if (!line || line === "[DONE]" || line === "data: [DONE]") continue;
            let jsonStr = line.startsWith("data:") ? line.slice(5).trim() : line;
            if (!jsonStr || jsonStr === "[DONE]") continue;
            try {
              const parsed = JSON.parse(jsonStr) as unknown;
              const r = processStreamJsonValue(parsed, sender);
              if (r.error) {
                finish({ ok: false, error: r.error });
                return;
              }
              if (r.hadDelta) hadText = true;
            } catch {
              /* 非完整 JSON 行，忽略 */
            }
          }
        });

        res.on("end", () => {
          if (doneSent) return;
          if (signal.canceled) {
            finish({ ok: false, canceled: true });
            return;
          }
          const tail = lineBuf.trim();
          if (tail) {
            let jsonStr = tail.startsWith("data:") ? tail.slice(5).trim() : tail;
            if (jsonStr && jsonStr !== "[DONE]") {
              try {
                const parsed = JSON.parse(jsonStr) as unknown;
                const r = processStreamJsonValue(parsed, sender);
                if (r.error) {
                  finish({ ok: false, error: r.error });
                  return;
                }
                if (r.hadDelta) hadText = true;
              } catch {
                /* ignore */
              }
            }
          }
          if (!hadText && rawAccum.trim()) {
            try {
              const parsed = JSON.parse(rawAccum.trim()) as unknown;
              const r = processStreamJsonValue(parsed, sender);
              if (r.error) {
                finish({ ok: false, error: r.error });
                return;
              }
              if (r.hadDelta) hadText = true;
            } catch {
              /* 非单行整包 JSON */
            }
          }
          if (hadText) {
            finish({ ok: true });
            return;
          }
          void generateContentSync(apiKey, body, model, timeoutMs)
            .then((full) => {
              if (doneSent || signal.canceled) return;
              sender.send("bbchat:gemini-chunk", { delta: full });
              finish({ ok: true });
            })
            .catch((e) => {
              if (doneSent || signal.canceled) return;
              const msg = e instanceof Error ? e.message : String(e);
              finish({
                ok: false,
                error:
                  msg ||
                  "模型未返回有效文本（可检查模型名与代理；流式解析失败且非流式回退也失败）",
              });
            });
        });

        res.on("error", (e) => {
          if (doneSent) return;
          if (signal.canceled) finish({ ok: false, canceled: true });
          else finish({ ok: false, error: e instanceof Error ? e.message : String(e) });
        });
      }
    );

    activeGeminiRequest = req;
    req.on("error", (e) => {
      activeGeminiRequest = null;
      if (doneSent) return;
      if (signal.canceled) finish({ ok: false, canceled: true });
      else finish({ ok: false, error: e instanceof Error ? e.message : String(e) });
    });
    req.on("timeout", () => {
      req.destroy();
      if (!doneSent && !signal.canceled) finish({ ok: false, error: "请求超时（检查代理）" });
    });
    req.write(payload);
    req.end();
  }).finally(() => {
    activeGeminiRequest = null;
  }) as Promise<void>;
}

let geminiStreamSession: { cancel: () => void } | null = null;

/** 开发 / 打包后均可解析的窗口图标（与 dist-electron 相对路径） */
function resolveWindowIcon(): string | undefined {
  const candidates =
    process.platform === "win32"
      ? [
          path.join(__dirname, "../resources/app-icon.ico"),
          path.join(__dirname, "../resources/app-icon.png"),
          path.join(__dirname, "../public/app-icon.png"),
          path.join(__dirname, "../dist/app-icon.png"),
        ]
      : [
          path.join(__dirname, "../resources/app-icon.png"),
          path.join(__dirname, "../public/app-icon.png"),
          path.join(__dirname, "../dist/app-icon.png"),
        ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 960,
    height: 720,
    minWidth: 360,
    minHeight: 480,
    icon: resolveWindowIcon(),
    title: "转写查证",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  attachExternalLinkPolicy(win);

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

function extractVideoUrlFromPaste(text: string): string {
  const raw = text.trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) {
    return raw.split(/\s/)[0]!.replace(/[.,;)\]}"']+$/, "");
  }
  const m = raw.match(/https?:\/\/[^\s\]\)"'<>]+/i);
  if (!m?.[0]) return raw;
  return m[0].replace(/[.,;)\]}"']+$/, "");
}

function isSupportedVideoUrlLike(u: string): boolean {
  const s = extractVideoUrlFromPaste(u).toLowerCase();
  return (
    s.includes("bilibili.com") ||
    s.includes("b23.tv") ||
    s.includes("douyin.com") ||
    s.includes("iesdouyin.com")
  );
}

function isHttpUrl(u: string): boolean {
  try {
    const p = new URL(u);
    return p.protocol === "http:" || p.protocol === "https:";
  } catch {
    return false;
  }
}

async function openInDefaultBrowser(url: string): Promise<void> {
  await shell.openExternal(url);
}

/** 禁止在应用内打开 http(s)，统一走系统默认浏览器 */
function attachExternalLinkPolicy(win: BrowserWindow): void {
  const wc = win.webContents;
  const devUrl = process.env.VITE_DEV_SERVER_URL || "";
  wc.setWindowOpenHandler(({ url }) => {
    if (isHttpUrl(url)) void openInDefaultBrowser(url);
    return { action: "deny" };
  });
  wc.on("will-navigate", (event, url) => {
    if (!isHttpUrl(url)) return;
    if (devUrl && url.startsWith(devUrl)) return;
    if (url.startsWith("file://")) return;
    event.preventDefault();
    void openInDefaultBrowser(url);
  });
}

function collectResultJsonMtimes(runsRoot: string): Map<string, number> {
  const m = new Map<string, number>();
  if (!fs.existsSync(runsRoot)) return m;
  const stack = [runsRoot];
  while (stack.length) {
    const dir = stack.pop() as string;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const ent of entries) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) stack.push(p);
      else if (ent.name === "result.json") {
        try {
          m.set(p, fs.statSync(p).mtimeMs);
        } catch {
          /* skip */
        }
      }
    }
  }
  return m;
}

function pickUpdatedResultJson(
  before: Map<string, number>,
  after: Map<string, number>
): string | null {
  let bestPath: string | null = null;
  let bestTime = 0;
  for (const [p, t2] of after) {
    const t1 = before.get(p);
    if (t1 !== undefined && t2 <= t1) continue;
    if (t2 > bestTime) {
      bestTime = t2;
      bestPath = p;
    }
  }
  return bestPath;
}

function extractBilibiliBvId(u: string): string | null {
  const m = u.match(/BV[a-z0-9]{10}/i);
  return m ? m[0].toUpperCase() : null;
}

function extractDouyinVideoId(u: string): string | null {
  const m = u.match(/(?:\/video\/|\/share\/video\/|modal_id=)(\d{15,22})/i);
  return m ? m[1]! : null;
}

function videoUrlMatchKey(u: string): string | null {
  const trimmed = u.trim();
  if (!trimmed) return null;
  const bv = extractBilibiliBvId(trimmed);
  if (bv) return `bv:${bv}`;
  const dy = extractDouyinVideoId(trimmed);
  if (dy) return `dy:${dy}`;
  try {
    const x = new URL(trimmed);
    const host = x.hostname.replace(/^www\./, "").toLowerCase();
    const pathOnly = x.pathname.replace(/\/+$/, "").toLowerCase();
    return `url:${host}${pathOnly}`;
  } catch {
    return null;
  }
}

function manifestMatchesUserUrl(manifestSourceUrl: string, userUrl: string): boolean {
  const su = manifestSourceUrl.trim();
  const u = extractVideoUrlFromPaste(userUrl).trim();
  if (!su || !u) return false;
  const km = videoUrlMatchKey(su);
  const ku = videoUrlMatchKey(u);
  if (km && ku && km === ku) return true;
  const bvM = extractBilibiliBvId(su);
  const bvU = extractBilibiliBvId(u);
  if (bvM && bvU && bvM === bvU) return true;
  const dyM = extractDouyinVideoId(su);
  const dyU = extractDouyinVideoId(u);
  return !!(dyM && dyU && dyM === dyU);
}

/**
 * 根据各任务目录下的 task_manifest.source_url 找回已有 result.json。
 * 用于：Python checkpoint 跳过、或用户重复粘贴同一链接时直接复用 runs 内结果。
 */
function findResultJsonByManifestUrl(runsRoot: string, userUrl: string): string | null {
  if (!fs.existsSync(runsRoot)) return null;
  let bestPath: string | null = null;
  let bestMtime = 0;
  const stack = [runsRoot];
  while (stack.length) {
    const dir = stack.pop() as string;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const ent of entries) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        stack.push(p);
        continue;
      }
      if (ent.name !== "task_manifest.json") continue;
      try {
        const raw = fs.readFileSync(p, "utf-8");
        const j = JSON.parse(raw) as { source_url?: string };
        const su = typeof j.source_url === "string" ? j.source_url.trim() : "";
        if (!su || !manifestMatchesUserUrl(su, userUrl)) continue;
        const rj = path.join(path.dirname(p), "result.json");
        if (!fs.existsSync(rj)) continue;
        const st = fs.statSync(rj);
        if (st.mtimeMs >= bestMtime) {
          bestMtime = st.mtimeMs;
          bestPath = rj;
        }
      } catch {
        /* 损坏或非 JSON */
      }
    }
  }
  return bestPath;
}

function resolvePythonExecutable(): string {
  for (const key of ["VIDEO_TO_WORD_PYTHON", "TRANSCRIPT_PYTHON", "BILIBILI_TO_TEXT_PYTHON"]) {
    const fromEnv = process.env[key]?.trim();
    if (fromEnv) return fromEnv;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function decodeChildOutput(chunk: Buffer | string): string {
  return Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk);
}

function formatChildExitCode(code: number | null): string {
  if (code == null) return "未知";
  if (code > 0x7fffffff) return String(code - 0x1_0000_0000);
  return String(code);
}

function pythonEnvWithCookies(repoRoot: string): NodeJS.ProcessEnv {
  const env = { ...process.env };
  env.PYTHONUTF8 = "1";
  env.PYTHONIOENCODING = "utf-8";
  const cookiesPath = path.join(repoRoot, "cookies.txt");
  if (fs.existsSync(cookiesPath)) {
    env.YT_DLP_COOKIES = cookiesPath;
  }
  const envPath = path.join(repoRoot, ".env");
  if (fs.existsSync(envPath)) {
    const raw = fs.readFileSync(envPath, "utf-8");
    for (const line of raw.split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith("#") || !t.includes("=")) continue;
      const eq = t.indexOf("=");
      const key = t.slice(0, eq).trim();
      const v = t
        .slice(eq + 1)
        .trim()
        .replace(/^["']|["']$/g, "");
      if (key && v && !env[key]) env[key] = v;
    }
  }
  return env;
}

type DoctorCheck = { ok?: boolean; message?: string };

function runDoctorDouyinOnly(
  repoRoot: string,
  url: string
): Promise<{ ok: boolean; detail: string }> {
  const py = resolvePythonExecutable();
  const doctorPy = path.join(repoRoot, "tools", "doctor.py");
  return new Promise((resolve) => {
    let stdout = "";
    const proc = spawn(py, [doctorPy, "--douyin-only", "--json", "--url", url], {
      cwd: repoRoot,
      env: pythonEnvWithCookies(repoRoot),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    proc.stdout?.on("data", (chunk: Buffer | string) => {
      stdout += decodeChildOutput(chunk);
      if (stdout.length > 32_000) stdout = stdout.slice(-32_000);
    });
    proc.on("error", (err) => {
      resolve({ ok: false, detail: err.message });
    });
    proc.on("close", (code) => {
      try {
        const checks = JSON.parse(stdout.trim()) as Record<string, DoctorCheck>;
        const cookies = checks.cookies;
        const sim = checks.douyin_simulate;
        const ok = !!(cookies?.ok && sim?.ok);
        const parts: string[] = [];
        if (!cookies?.ok && cookies?.message) parts.push(`Cookie: ${cookies.message}`);
        if (!sim?.ok && sim?.message) parts.push(`simulate: ${sim.message}`);
        resolve({
          ok,
          detail: parts.join("\n") || (ok ? "" : `doctor 退出码 ${code ?? 1}`),
        });
      } catch {
        resolve({
          ok: false,
          detail: stdout.trim().slice(-2000) || `doctor 退出码 ${code ?? 1}`,
        });
      }
    });
  });
}

async function ensureDouyinReady(
  repoRoot: string,
  url: string,
  onNeedLogin?: () => void
): Promise<{ ok: true } | { ok: false; error: string }> {
  let pre = await runDoctorDouyinOnly(repoRoot, url);
  if (pre.ok) return { ok: true };

  onNeedLogin?.();
  const login = await openDouyinLoginFlow({ repoRoot, videoUrl: url });
  if ("canceled" in login && login.canceled) {
    return { ok: false, error: "已取消抖音登录" };
  }
  if (!login.ok) {
    return { ok: false, error: login.error };
  }

  pre = await runDoctorDouyinOnly(repoRoot, url);
  if (pre.ok) return { ok: true };

  return {
    ok: false,
    error:
      `抖音下载预检未通过：${pre.detail}\n` +
      "请在内置窗口重新登录，或用手动保存的 mp4 通过「本地视频」转写。",
  };
}

function runPythonMainArgs(
  repoRoot: string,
  args: string[]
): Promise<{ code: number | null; stderrTail: string; stdoutTail: string }> {
  const py = resolvePythonExecutable();
  const mainPy = transcriptCliPy(repoRoot);
  return new Promise((resolve, reject) => {
    let stderr = "";
    let stdout = "";
    const proc = spawn(py, [mainPy, ...transcriptCliExtraArgs(), ...args], {
      cwd: repoRoot,
      env: pythonEnvWithCookies(repoRoot),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    proc.stderr?.on("data", (chunk: Buffer | string) => {
      stderr += decodeChildOutput(chunk);
      if (stderr.length > 120_000) stderr = stderr.slice(-120_000);
    });
    proc.stdout?.on("data", (chunk: Buffer | string) => {
      stdout += decodeChildOutput(chunk);
      if (stdout.length > 120_000) stdout = stdout.slice(-120_000);
    });
    proc.on("error", (err) => reject(err));
    proc.on("close", (code) => {
      resolve({
        code: code ?? 1,
        stderrTail: stderr.trim().slice(-8000),
        stdoutTail: stdout.trim().slice(-8000),
      });
    });
  });
}

function pythonFailureDetail(
  code: number | null,
  stderrTail: string,
  stdoutTail: string
): string {
  const parts: string[] = [`退出码 ${formatChildExitCode(code)}`];
  const errText = stderrTail.trim();
  const outText = stdoutTail.trim();
  if (errText) parts.push(errText);
  if (outText && outText !== errText) parts.push(outText);
  return parts.join("\n");
}

function runPythonMain(repoRoot: string, url: string): Promise<{ code: number | null; stderrTail: string }> {
  return runPythonMainArgs(repoRoot, [url]);
}

ipcMain.handle("bbchat:open-transcript", async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    title: "选择 result.json",
    properties: ["openFile"],
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (canceled || !filePaths[0]) return { ok: false as const, canceled: true };
  try {
    const raw = fs.readFileSync(filePaths[0], "utf-8");
    const data = JSON.parse(raw) as unknown;
    return { ok: true as const, path: filePaths[0], data };
  } catch (e) {
    return {
      ok: false as const,
      error: e instanceof Error ? e.message : String(e),
    };
  }
});

async function handleParseVideoUrl(url: string) {
  const raw = typeof url === "string" ? extractVideoUrlFromPaste(url) : "";
  if (!raw) return { ok: false as const, error: "链接为空" };
  if (!isSupportedVideoUrlLike(raw)) {
    return {
      ok: false as const,
      error:
        "仅支持 bilibili.com / b23.tv / douyin.com / iesdouyin.com 的视频链接。",
    };
  }
  const repoRoot = repoRootFromChatUi();
  const mainPy = transcriptCliPy(repoRoot);
  if (!fs.existsSync(mainPy)) {
    return {
      ok: false as const,
      error: `未找到 ${mainPy}：请在 video-to-word 仓库根目录运行 npm run dev。`,
    };
  }
  const runsDir = path.join(repoRoot, "runs");
  const tryReadPicked = (picked: string): { ok: true; path: string; data: unknown } | { ok: false; error: string } => {
    try {
      const data = JSON.parse(fs.readFileSync(picked, "utf-8")) as unknown;
      return { ok: true as const, path: picked, data };
    } catch (e) {
      return {
        ok: false as const,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  };

  const cachedPath = findResultJsonByManifestUrl(runsDir, raw);
  if (cachedPath) {
    const r = tryReadPicked(cachedPath);
    if (r.ok) return r;
  }

  if (isDouyinUrlLike(raw)) {
    const sendPhase = (phase: "douyin-login" | "running" | "idle") => {
      for (const w of BrowserWindow.getAllWindows()) {
        if (!w.isDestroyed()) {
          w.webContents.send("bbchat:parse-status", { phase });
        }
      }
    };
    const ready = await ensureDouyinReady(repoRoot, raw, () => sendPhase("douyin-login"));
    if (!ready.ok) {
      sendPhase("idle");
      return { ok: false as const, error: ready.error };
    }
    sendPhase("running");
  }

  const beforeMaps = collectResultJsonMtimes(runsDir);
  try {
    const { code, stderrTail, stdoutTail } = await runPythonMain(repoRoot, raw);
    const afterMaps = collectResultJsonMtimes(runsDir);
    let picked = pickUpdatedResultJson(beforeMaps, afterMaps);
    if (!picked) {
      picked = findResultJsonByManifestUrl(runsDir, raw);
    }
    if (code !== 0) {
      if (picked) {
        const recovered = tryReadPicked(picked);
        if (recovered.ok) return recovered;
      }
      const detail = pythonFailureDetail(code, stderrTail, stdoutTail);
      return {
        ok: false as const,
        error: `解析失败（${detail}）`,
      };
    }
    if (!picked) {
      const combined = `${stderrTail}\n${stdoutTail}`;
      const skipHint =
        combined.includes("[skip]") || combined.includes("已完成，跳过")
          ? " 若该链接曾被标记完成，Python 会跳过且不更新文件；可编辑 runs/_done_checkpoint.json（或旧版 _bilibili_done_checkpoint.json）去掉对应 URL 后重试。"
          : "";
      const detail = pythonFailureDetail(code, stderrTail, stdoutTail);
      return {
        ok: false as const,
        error:
          "Python 已结束但未在 runs/ 下检测到更新的 result.json，也无法根据 task_manifest 匹配到已有输出。" +
          skipHint +
          (detail ? `\n${detail.slice(-2000)}` : ""),
      };
    }
    return tryReadPicked(picked);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      ok: false as const,
      error: `无法启动 Python（${resolvePythonExecutable()}）：${msg}。可设置环境变量 VIDEO_TO_WORD_PYTHON 指定解释器。`,
    };
  } finally {
    if (isDouyinUrlLike(raw)) {
      for (const w of BrowserWindow.getAllWindows()) {
        if (!w.isDestroyed()) {
          w.webContents.send("bbchat:parse-status", { phase: "idle" });
        }
      }
    }
  }
}

ipcMain.handle("bbchat:parse-bilibili-url", async (_, url: string) => handleParseVideoUrl(url));
ipcMain.handle("bbchat:parse-video-url", async (_, url: string) => handleParseVideoUrl(url));

ipcMain.handle(
  "bbchat:douyin-open-login",
  async (_, arg: { url?: string } | undefined) => {
    const repoRoot = repoRootFromChatUi();
    const videoUrl =
      typeof arg?.url === "string" ? extractVideoUrlFromPaste(arg.url).trim() : "";
    const login = await openDouyinLoginFlow({
      repoRoot,
      videoUrl: videoUrl || undefined,
    });
    if ("canceled" in login && login.canceled) {
      return { ok: false as const, canceled: true as const };
    }
    if (!login.ok) {
      return { ok: false as const, error: login.error };
    }
    return { ok: true as const, cookieCount: login.cookieCount };
  }
);

ipcMain.handle("bbchat:douyin-session-status", async () => {
  const repoRoot = repoRootFromChatUi();
  const status = await getDouyinSessionStatus(repoRoot);
  return { ok: true as const, ...status };
});

ipcMain.handle("bbchat:gemini-chat-cancel", () => {
  geminiStreamSession?.cancel();
  return { ok: true as const };
});

ipcMain.handle(
  "bbchat:gemini-chat-start",
  async (
    event,
    arg: {
      system: string;
      contents: { role: "user" | "model"; text: string }[];
      model?: string;
    }
  ) => {
    const key = resolveGeminiApiKey();
    if (!key) {
      return {
        ok: false as const,
        error: GEMINI_KEY_MISSING_MSG,
      };
    }
    const model = (arg.model || DEFAULT_MODEL).trim();
    const contents = arg.contents.map((c) => ({
      role: c.role === "model" ? "model" : "user",
      parts: [{ text: c.text }],
    }));
    const body: Record<string, unknown> = {
      systemInstruction: { parts: [{ text: arg.system }] },
      contents,
      generationConfig: { temperature: 0.4, maxOutputTokens: 8192 },
    };

    geminiStreamSession?.cancel();
    const signal = { canceled: false };
    const cancel = () => {
      signal.canceled = true;
      abortActiveGeminiRequest();
    };
    const session = { cancel };
    geminiStreamSession = session;

    void streamGenerateToSender(event.sender, key, body, model, 120_000, signal).finally(() => {
      if (geminiStreamSession === session) geminiStreamSession = null;
    });

    return { ok: true as const };
  }
);

ipcMain.handle("bbchat:open-external", async (_, raw: string) => {
  const url = typeof raw === "string" ? raw.trim() : "";
  if (!url) return { ok: false as const, error: "链接为空" };
  if (!isHttpUrl(url)) return { ok: false as const, error: "仅支持 http/https 链接" };
  try {
    await openInDefaultBrowser(url);
    return { ok: true as const };
  } catch (e) {
    return { ok: false as const, error: e instanceof Error ? e.message : String(e) };
  }
});

ipcMain.handle("bbchat:platform", () => ({ kind: "electron" as const }));

ipcMain.handle("bbchat:get-api-settings", async () => {
  const key = resolveGeminiApiKey();
  return {
    ok: true as const,
    hasGeminiKey: Boolean(key),
    geminiMasked: key ? maskApiKey(key) : undefined,
  };
});

ipcMain.handle(
  "bbchat:save-api-settings",
  async (_event, arg: { geminiApiKey?: string } | undefined) => {
    const k = typeof arg?.geminiApiKey === "string" ? arg.geminiApiKey.trim() : "";
    if (!k) {
      return { ok: false as const, error: "API Key 不能为空" };
    }
    const prev = readUserAppSettings();
    writeUserAppSettings({ ...prev, geminiApiKey: k });
    return {
      ok: true as const,
      hasGeminiKey: true,
      geminiMasked: maskApiKey(k),
    };
  }
);

/** 与渲染进程 localStorage 镜像：解析稿 + 对话，避免清缓存后丢失 */
const APP_STATE_FILE = "chat-ui-state.json";

function appStateFilePath(): string {
  return path.join(app.getPath("userData"), APP_STATE_FILE);
}

ipcMain.handle("bbchat:save-app-persist", async (_, json: unknown) => {
  const data = typeof json === "string" ? json : "";
  if (!data.trim()) return { ok: false as const, error: "持久化内容为空" };
  try {
    fs.writeFileSync(appStateFilePath(), data, "utf-8");
    return { ok: true as const };
  } catch (e) {
    return {
      ok: false as const,
      error: e instanceof Error ? e.message : String(e),
    };
  }
});

ipcMain.handle("bbchat:load-app-persist", async () => {
  try {
    const p = appStateFilePath();
    if (!fs.existsSync(p)) return { ok: true as const, json: null as string | null };
    const json = fs.readFileSync(p, "utf-8");
    return { ok: true as const, json };
  } catch (e) {
    return {
      ok: false as const,
      error: e instanceof Error ? e.message : String(e),
    };
  }
});

const VERIFY_CITE_SYSTEM = `你是「必须联网检索」的事实核对助手。你必须使用 Google 搜索工具检索公开网页后再组织答案；禁止仅凭训练记忆、常识或未经验证的推断下结论。

用户材料：
- 「总结待核要点」：AI 归纳的可核对陈述（主对象）。
- 「稿内原话」：对应时段转写（仅帮助理解语境，核对仍以总结要点为准）。

硬性规则（写死遵守）：
1. 在输出任何「支持 / 部分支持 / 与公开信息不符」之前，必须先完成与结论相关的检索；若检索不到可引用的公开来源，该条结论只能写「无法核实」，并简要说明缺什么信息或搜到什么矛盾。
2. 每条结论须对应至少一条可核验的公开依据；在正文中用 Markdown 链接写出来源标题与 URL。禁止编造链接、禁止虚构域名。
3. 区分「可验证事实」与「观点/预测/价值判断」；后者标注为无法做真假判定，不强行给支持/反对。
4. 输出简洁 Markdown（小标题 + 有序/无序列表），总字数控制在 800 字内。`;

async function verifyCiteWithSearch(
  apiKey: string,
  model: string,
  arg: { claimText: string; quoteText: string; startLabel: string; endLabel: string }
): Promise<string> {
  const quoteBlock = arg.quoteText
    ? `稿内原话（对照参考，时段 ${arg.startLabel} — ${arg.endLabel}）：
"""
${arg.quoteText}
"""`
    : `（未提供稿内原话。时段：${arg.startLabel} — ${arg.endLabel}）`;

  const userText = `【查证任务】你必须调用 Google 搜索，检索与下述「总结待核要点」相关的公开报道、官网、统计或权威二手信息；确认检索结果后再写结论。不得在未完成有效检索的情况下输出「已核实」「属实」等措辞。

总结待核要点：
"""
${arg.claimText}
"""

${quoteBlock}

请按系统硬性规则输出事实核对报告。`;

  const withSearch: Record<string, unknown> = {
    systemInstruction: { parts: [{ text: VERIFY_CITE_SYSTEM }] },
    contents: [{ role: "user", parts: [{ text: userText }] }],
    tools: [{ google_search: {} }],
    generationConfig: { temperature: 0.2, maxOutputTokens: 2048 },
  };

  try {
    return await generateContentSync(apiKey, withSearch, model, 120_000);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(
      `联网查证必须使用 Google 搜索引擎（google_search），当前请求失败且已禁用「仅模型记忆」降级：\n${msg.slice(0, 1200)}\n请确认所用模型支持 Google Search，或稍后重试。`
    );
  }
}

ipcMain.handle(
  "bbchat:verify-cite",
  async (
    _,
    arg: { claimText?: string; quoteText?: string; startLabel?: string; endLabel?: string }
  ) => {
    const claimText = typeof arg?.claimText === "string" ? arg.claimText.trim() : "";
    const quoteText = typeof arg?.quoteText === "string" ? arg.quoteText.trim() : "";
    const startLabel = typeof arg?.startLabel === "string" ? arg.startLabel.trim() : "";
    const endLabel = typeof arg?.endLabel === "string" ? arg.endLabel.trim() : "";
    if (!claimText && !quoteText) return { ok: false as const, error: "查证内容为空" };

    const key = resolveGeminiApiKey();
    if (!key) {
      return {
        ok: false as const,
        error: GEMINI_KEY_MISSING_MSG,
      };
    }
    const model = DEFAULT_MODEL;
    try {
      const report = await verifyCiteWithSearch(key, model, {
        claimText: claimText || quoteText,
        quoteText,
        startLabel,
        endLabel,
      });
      return { ok: true as const, report };
    } catch (e) {
      return {
        ok: false as const,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  }
);
