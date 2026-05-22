import { useLayoutEffect, useState } from "react";
import { applyTheme, getStoredTheme, persistTheme, type Theme } from "@/lib/theme";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme());

  useLayoutEffect(() => {
    applyTheme(theme);
    persistTheme(theme);
  }, [theme]);

  const setTheme = (t: Theme) => setThemeState(t);
  return [theme, setTheme];
}
