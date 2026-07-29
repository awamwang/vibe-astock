import { useEffect, useState } from "react";

// 默认浅色；用户可切暗色，选择存 localStorage。
// 机制：亮色时给 <html> 加 .light（暗色为无类名的默认态）。
export function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("vr-theme");
    if (saved) return saved === "dark";
    return false; // 默认浅色
  });

  useEffect(() => {
    document.documentElement.classList.toggle("light", !dark);
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("vr-theme", dark ? "dark" : "light");
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}
