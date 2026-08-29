import { toast } from "sonner";

/** 构建带 basename 的站内绝对 URL */
export function appUrl(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${window.location.origin}${prefix}${p}`;
}

const DEFAULT_FEATURES = [
  "popup=yes",
  "width=520",
  "height=720",
  "left=80",
  "top=80",
  "resizable=yes",
  "scrollbars=yes",
].join(",");

/** 打开独立路由弹窗；同名窗口已打开则导航并聚焦 */
export function openSectionPopup(
  path: string,
  windowName: string,
  features?: string,
): Window | null {
  const w = window.open(appUrl(path), windowName, features || DEFAULT_FEATURES);
  if (!w) {
    toast.error("浏览器拦截了弹窗，请允许本站弹出窗口后重试", {
      position: "top-center",
      duration: 5000,
    });
    return null;
  }
  w.focus();
  return w;
}
