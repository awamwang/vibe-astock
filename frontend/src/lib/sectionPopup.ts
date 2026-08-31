import { toast } from "sonner";

/** 构建带 basename 的站内绝对 URL */
export function appUrl(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${window.location.origin}${prefix}${p}`;
}

export type PopupGeometry = {
  width: number;
  height: number;
  left?: number;
  top?: number;
};

const GEOM_KEY_PREFIX = "va-popup-geom:";

const DEFAULT_GEOMETRY: PopupGeometry = {
  width: 520,
  height: 720,
  left: 80,
  top: 80,
};

function clampGeom(g: PopupGeometry): PopupGeometry {
  const width = Math.min(Math.max(Math.round(g.width), 280), screen.availWidth || 1920);
  const height = Math.min(Math.max(Math.round(g.height), 200), screen.availHeight || 1080);
  const left = g.left != null ? Math.round(g.left) : undefined;
  const top = g.top != null ? Math.round(g.top) : undefined;
  return { width, height, left, top };
}

/** 读取上次保存的弹窗大小与位置 */
export function loadPopupGeometry(windowName: string): PopupGeometry | null {
  if (!windowName) return null;
  try {
    const raw = localStorage.getItem(GEOM_KEY_PREFIX + windowName);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PopupGeometry>;
    if (typeof parsed.width !== "number" || typeof parsed.height !== "number") return null;
    return clampGeom({
      width: parsed.width,
      height: parsed.height,
      left: typeof parsed.left === "number" ? parsed.left : undefined,
      top: typeof parsed.top === "number" ? parsed.top : undefined,
    });
  } catch {
    return null;
  }
}

/** 保存弹窗大小与位置（按 windowName） */
export function savePopupGeometry(windowName: string, geometry: PopupGeometry): void {
  if (!windowName) return;
  try {
    localStorage.setItem(GEOM_KEY_PREFIX + windowName, JSON.stringify(clampGeom(geometry)));
  } catch {
    /* quota / private mode */
  }
}

/** 把当前窗口外框写入 localStorage（依赖 window.open 传入的 window.name） */
export function persistCurrentPopupGeometry(): void {
  const name = window.name;
  if (!name) return;
  savePopupGeometry(name, {
    width: window.outerWidth,
    height: window.outerHeight,
    left: window.screenX,
    top: window.screenY,
  });
}

/** 在弹窗页挂载：拖动/缩放后记住大小位置 */
export function attachPopupGeometryPersistence(): () => void {
  if (!window.name) return () => {};

  let timer = 0;
  const schedule = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => persistCurrentPopupGeometry(), 200);
  };
  const flush = () => persistCurrentPopupGeometry();

  window.addEventListener("resize", schedule);
  window.addEventListener("pagehide", flush);
  window.addEventListener("beforeunload", flush);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });

  return () => {
    window.clearTimeout(timer);
    flush();
    window.removeEventListener("resize", schedule);
    window.removeEventListener("pagehide", flush);
    window.removeEventListener("beforeunload", flush);
  };
}

function parseFeatures(features: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of features.split(",")) {
    const i = part.indexOf("=");
    if (i <= 0) continue;
    out[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim();
  }
  return out;
}

function geometryFromFeatures(features: string): PopupGeometry {
  const f = parseFeatures(features);
  const num = (k: string, fallback: number) => {
    const v = Number(f[k]);
    return Number.isFinite(v) ? v : fallback;
  };
  return {
    width: num("width", DEFAULT_GEOMETRY.width),
    height: num("height", DEFAULT_GEOMETRY.height),
    left: f.left != null ? num("left", DEFAULT_GEOMETRY.left!) : DEFAULT_GEOMETRY.left,
    top: f.top != null ? num("top", DEFAULT_GEOMETRY.top!) : DEFAULT_GEOMETRY.top,
  };
}

function featuresFromGeometry(g: PopupGeometry, baseFeatures?: string): string {
  const f = baseFeatures ? parseFeatures(baseFeatures) : { popup: "yes", resizable: "yes", scrollbars: "yes" };
  f.popup = f.popup || "yes";
  f.resizable = f.resizable || "yes";
  f.scrollbars = f.scrollbars || "yes";
  f.width = String(g.width);
  f.height = String(g.height);
  if (g.left != null) f.left = String(g.left);
  if (g.top != null) f.top = String(g.top);
  return Object.entries(f).map(([k, v]) => `${k}=${v}`).join(",");
}

const DEFAULT_FEATURES = featuresFromGeometry(DEFAULT_GEOMETRY);

/** 打开独立路由弹窗；同名窗口已打开则导航并聚焦；优先使用上次保存的大小位置 */
export function openSectionPopup(
  path: string,
  windowName: string,
  features?: string,
): Window | null {
  const base = features || DEFAULT_FEATURES;
  const saved = loadPopupGeometry(windowName);
  const geom = saved || geometryFromFeatures(base);
  const resolved = featuresFromGeometry(geom, base);
  const w = window.open(appUrl(path), windowName, resolved);
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
