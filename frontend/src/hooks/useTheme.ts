import { useEffect, useState } from "react";

export type Theme = "emerald" | "violet" | "ocean" | "rose" | "slate" | "light";

const STORAGE_KEY = "pa-theme";

function applyTheme(t: Theme) {
  if (t === "emerald") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", t);
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    return saved ?? "emerald";
  });

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  return { theme, setTheme };
}
