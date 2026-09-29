import { useCallback, useState } from "react"

export type Theme = "dark" | "light"

const STORAGE_KEY = "opsyn-theme"

function currentTheme(): Theme {
  if (typeof document !== "undefined") {
    const saved = document.documentElement.dataset.theme
    if (saved === "light" || saved === "dark") return saved
  }
  try {
    if (localStorage.getItem(STORAGE_KEY) === "light") return "light"
  } catch {
    /* storage unavailable — fall through */
  }
  return "dark"
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    /* storage unavailable — theme still applies for the session */
  }
}

/** Apply the persisted theme before first paint; call once at startup. */
export function initTheme() {
  applyTheme(currentTheme())
}

/** Theme state for the header toggle. Exactly one header mounts at a time. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof document !== "undefined" &&
    document.documentElement.dataset.theme === "light"
      ? "light"
      : currentTheme(),
  )
  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark"
      applyTheme(next)
      return next
    })
  }, [])
  return { theme, toggle }
}
