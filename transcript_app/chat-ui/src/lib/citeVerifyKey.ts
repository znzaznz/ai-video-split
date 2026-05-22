/** 与 CitePopoverPanel 一致：用于 localStorage / 磁盘持久化的键 */
export function citeVerifyCacheKey(
  startLabel: string,
  endLabel: string,
  claimText: string,
  quoteText: string
): string {
  const claim = claimText.trim();
  const quote = quoteText.trim();
  const verifyTarget = claim || quote;
  return `${startLabel}|${endLabel}|${verifyTarget}`;
}
