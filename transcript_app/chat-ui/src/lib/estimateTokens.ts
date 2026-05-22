/** 粗略估算输入 token（中英混排），仅作 UI 提示，非官方计费口径 */
export function roughTokenEstimate(text: string): number {
  if (!text) return 0;
  let latin = 0;
  let other = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (/[a-zA-Z0-9\s]/.test(c)) latin++;
    else other++;
  }
  return Math.max(1, Math.ceil(latin / 4 + other / 1.85));
}
