import type { Theme } from "@/lib/theme";

type Props = {
  theme: Theme;
  onToggle: () => void;
};

function IconSun() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function IconMoon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

/** 深色模式时显示太阳（点一下切浅色）；浅色模式时显示月亮（点一下切深色） */
export function ThemeToggle({ theme, onToggle }: Props) {
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      title={isDark ? "切换为浅色" : "切换为深色"}
      aria-label={isDark ? "切换为浅色模式" : "切换为深色模式"}
      onClick={onToggle}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 40,
        height: 36,
        padding: 0,
        borderRadius: 8,
        border: "1px solid var(--border)",
        background: "var(--panel)",
        color: "var(--text)",
      }}
    >
      {isDark ? <IconSun /> : <IconMoon />}
    </button>
  );
}
