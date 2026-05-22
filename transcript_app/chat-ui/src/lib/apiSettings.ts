export type ApiSettingsStatus = {
  hasGeminiKey: boolean;
  geminiMasked?: string;
};

export async function getApiSettings(): Promise<ApiSettingsStatus> {
  if (!window.bbChat?.getApiSettings) {
    return { hasGeminiKey: false };
  }
  const r = await window.bbChat.getApiSettings();
  if (!r.ok) return { hasGeminiKey: false };
  return {
    hasGeminiKey: r.hasGeminiKey,
    geminiMasked: r.geminiMasked,
  };
}

export async function saveGeminiApiKey(
  geminiApiKey: string
): Promise<{ ok: true; status: ApiSettingsStatus } | { ok: false; error: string }> {
  if (!window.bbChat?.saveApiSettings) {
    return { ok: false, error: "保存 API Key 仅支持 Electron 桌面版。" };
  }
  const r = await window.bbChat.saveApiSettings({ geminiApiKey: geminiApiKey.trim() });
  if (!r.ok) return { ok: false, error: r.error || "保存失败" };
  return {
    ok: true,
    status: { hasGeminiKey: r.hasGeminiKey, geminiMasked: r.geminiMasked },
  };
}
