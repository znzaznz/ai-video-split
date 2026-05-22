import type { VerifyCitePayload } from "@/lib/verifyCite";
import { verifyCiteClaim } from "@/lib/verifyCite";

export type CiteVerifyState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; report: string }
  | { status: "error"; error: string };

const stateByKey = new Map<string, CiteVerifyState>();
const inflightByKey = new Map<string, Promise<CiteVerifyState>>();

export function getCiteVerifyState(key: string): CiteVerifyState | undefined {
  return stateByKey.get(key);
}

export function setCiteVerifyState(key: string, state: CiteVerifyState): void {
  stateByKey.set(key, state);
}

export function getCiteVerifyInflight(key: string): Promise<CiteVerifyState> | undefined {
  return inflightByKey.get(key);
}

export function resolveInitialCiteVerifyState(
  key: string,
  persistedReport: string | null | undefined
): CiteVerifyState {
  if (persistedReport) {
    const done: CiteVerifyState = { status: "done", report: persistedReport };
    stateByKey.set(key, done);
    return done;
  }
  const session = stateByKey.get(key);
  if (session) return session;
  return { status: "idle" };
}

export async function runCiteVerify(
  key: string,
  payload: VerifyCitePayload,
  opts?: { bypassCache?: boolean; onPersist?: (report: string) => void }
): Promise<CiteVerifyState> {
  const verifyTarget = payload.claimText.trim() || payload.quoteText.trim();
  if (!verifyTarget) {
    const err: CiteVerifyState = {
      status: "error",
      error: "无总结要点或稿内原文，无法查证。",
    };
    setCiteVerifyState(key, err);
    return err;
  }

  if (!opts?.bypassCache) {
    const cached = stateByKey.get(key);
    if (cached?.status === "done") return cached;
    const existing = inflightByKey.get(key);
    if (existing) return existing;
  } else {
    inflightByKey.delete(key);
  }

  const run = async (): Promise<CiteVerifyState> => {
    setCiteVerifyState(key, { status: "loading" });
    const res = await verifyCiteClaim(payload);
    if (res.ok) {
      const next: CiteVerifyState = { status: "done", report: res.report };
      setCiteVerifyState(key, next);
      opts?.onPersist?.(res.report);
      return next;
    }
    const err: CiteVerifyState = { status: "error", error: res.error };
    setCiteVerifyState(key, err);
    return err;
  };

  const promise = run().finally(() => {
    inflightByKey.delete(key);
  });
  inflightByKey.set(key, promise);
  return promise;
}
