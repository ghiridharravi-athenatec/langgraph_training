import { useTheme } from "../context/ThemeContext";

export default function ThemeToggle({ floating = false }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className={floating ? "theme-toggle-btn theme-toggle-floating" : "theme-toggle-btn"}
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? "☀" : "☾"}
    </button>
  );
}
