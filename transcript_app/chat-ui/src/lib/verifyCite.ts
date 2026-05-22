export type VerifyCitePayload = {
  claimText: string;
  quoteText: string;
  startLabel: string;
  endLabel: string;
};

export async function verifyCiteClaim(
  payload: VerifyCitePayload
): Promise<{ ok: true; report: string } | { ok: false; error: string }> {
  if (!window.bbChat?.verifyCite) {
    return {
      ok: false,
      error: "查证需在 Electron 窗口使用，并先在设置中填写 Gemini API Key。",
    };
  }
  return window.bbChat.verifyCite(payload);
}
