import { useEffect, useRef, useState } from "react";
import {
  Archive, ChevronRight, Database, Download, FolderInput, FolderOpen, FolderOutput, HardDrive, Loader2, Upload,
  RefreshCw, ListOrdered,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import {
  api, downloadBackup, type BackupStatus, type StockUniverseStatus,
} from "@/lib/api";

type DataSectionId = "stock-universe" | "data-dirs" | "series" | "import-export";

const DATA_SECTIONS: {
  id: DataSectionId;
  label: string;
  icon: typeof ListOrdered;
  hint: string;
}[] = [
  { id: "stock-universe", label: "A 股股票列表", icon: ListOrdered, hint: "本地缓存与网络刷新" },
  { id: "data-dirs", label: "数据目录", icon: HardDrive, hint: "根目录、缓存与统计" },
  { id: "series", label: "长序列", icon: Database, hint: "SQLite 增长型序列" },
  { id: "import-export", label: "导入导出", icon: FolderOutput, hint: "全量备份与恢复" },
];

const DEST_KEY = "va-backup-dest";
const SERIES_DEST_KEY = "va-series-export-dest";
const SRC_KEY = "va-backup-src";

const SERIES_LABELS: Record<string, string> = {
  margin_sse: "两融余额",
  sh000001: "上证日线",
  market_amount: "两市成交额",
  sentiment_s: "情绪分位序列",
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function readLocal(key: string): string {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeLocal(key: string, value: string) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "");
      resolve(text.includes(",") ? text.split(",")[1] : text);
    };
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

function DirRow({
  label, path, opening, disabled, onOpen,
}: {
  label: string;
  path?: string;
  opening: boolean;
  disabled: boolean;
  onOpen: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <button
          type="button"
          title={path ? `打开 ${path}` : undefined}
          disabled={!path || disabled}
          onClick={onOpen}
          className="mt-0.5 break-all text-left text-sm font-medium text-primary underline-offset-2 hover:underline disabled:text-muted-foreground disabled:no-underline"
        >
          {path || "正在读取…"}
        </button>
      </div>
      <button
        type="button"
        disabled={!path || disabled}
        onClick={onOpen}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
      >
        {opening ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderOpen className="h-3.5 w-3.5" />}
        打开
      </button>
    </div>
  );
}

export function DataBackup() {
  const [activeSection, setActiveSection] = useState<DataSectionId>("stock-universe");
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [stockUni, setStockUni] = useState<StockUniverseStatus | null>(null);
  const [stockRefreshing, setStockRefreshing] = useState(false);
  const [destDir, setDestDir] = useState(() => readLocal(DEST_KEY));
  const [seriesDestDir, setSeriesDestDir] = useState(() => readLocal(SERIES_DEST_KEY) || readLocal(DEST_KEY));
  const [srcPath, setSrcPath] = useState(() => readLocal(SRC_KEY));
  const [exporting, setExporting] = useState(false);
  const [exportingSeries, setExportingSeries] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [opening, setOpening] = useState<"root" | "cache" | "series" | null>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  const reload = () =>
    api.backupStatus().then(setStatus).catch(() => setStatus(null)).finally(() => setLoaded(true));

  const reloadStockUni = () =>
    api.stockUniverseStatus().then(setStockUni).catch(() => setStockUni(null));

  useEffect(() => {
    reload();
    void reloadStockUni();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!stockRefreshing && !stockUni?.refreshing) return;
    const timer = window.setInterval(() => {
      void reloadStockUni().then((s) => {
        if (!s.refreshing) setStockRefreshing(false);
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [stockRefreshing, stockUni?.refreshing]);

  const doRefreshStockUni = async () => {
    setStockRefreshing(true);
    try {
      const r = await api.refreshStockUniverse();
      setStockUni(r);
      if (r.started === false) {
        toast.info("股票列表正在刷新中…");
      } else {
        toast.success("已开始从网络刷新股票列表");
      }
    } catch (e) {
      setStockRefreshing(false);
      toast.error(e instanceof Error ? e.message : "刷新失败");
    }
  };

  const busy = exporting || exportingSeries || downloading || importing || opening !== null
    || stockRefreshing || Boolean(stockUni?.refreshing);

  const openDir = async (kind: "root" | "cache" | "series") => {
    setOpening(kind);
    try {
      const r = await api.backupOpen(kind);
      toast.success(`已打开 ${r.path}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "打开目录失败");
    } finally {
      setOpening(null);
    }
  };

  const doExport = async () => {
    const dest = destDir.trim();
    if (!dest) {
      toast.error("请填写导出目录");
      return;
    }
    writeLocal(DEST_KEY, dest);
    setExporting(true);
    try {
      const r = await api.backupExport(dest);
      toast.success(`已导出 ${r.file_count} 个文件（${fmtBytes(r.byte_count)}）→ ${r.path}`);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  const doExportSeries = async () => {
    const dest = seriesDestDir.trim() || destDir.trim();
    if (!dest) {
      toast.error("请填写长序列导出目录");
      return;
    }
    writeLocal(SERIES_DEST_KEY, dest);
    setExportingSeries(true);
    try {
      const r = await api.backupExportSeries(dest);
      toast.success(`已导出长序列 ${r.row_count} 行 → ${r.path}`);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出长序列失败");
    } finally {
      setExportingSeries(false);
    }
  };

  const doDownload = async () => {
    setDownloading(true);
    try {
      const name = await downloadBackup();
      toast.success(`已开始下载 ${name}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "下载失败");
    } finally {
      setDownloading(false);
    }
  };

  const doImportPath = async () => {
    const src = srcPath.trim();
    if (!src) {
      toast.error("请填写压缩包或文件夹路径");
      return;
    }
    if (!window.confirm("导入会覆盖同路径的已有文件，本地多出来的文件会保留。继续？")) return;
    writeLocal(SRC_KEY, src);
    setImporting(true);
    try {
      const r = await api.backupImportPath(src);
      toast.success(`已导入 ${r.imported} 个文件（${fmtBytes(r.byte_count)}）`);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const doImportZip = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      toast.error("请选择 .zip 压缩包");
      return;
    }
    if (!window.confirm(`导入「${file.name}」会覆盖同路径的已有文件，本地多出来的文件会保留。继续？`)) return;
    setImporting(true);
    try {
      const b64 = await fileToBase64(file);
      const r = await api.backupImportZip(b64);
      toast.success(`已导入 ${r.imported} 个文件（${fmtBytes(r.byte_count)}）`);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    } finally {
      setImporting(false);
      if (zipRef.current) zipRef.current.value = "";
    }
  };

  const series = status?.series;

  return (
    <div>
      <PageHeader
        title="数据管理"
        subtitle="查看本机数据目录，打包导出已落盘的请求缓存与生成结果，也可从压缩包或文件夹导入"
      />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <nav className="glass shrink-0 rounded-2xl p-2 lg:w-52">
          <p className="px-3 py-2 text-[11px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            数据项
          </p>
          <ul className="space-y-0.5">
            {DATA_SECTIONS.map((section) => {
              const Icon = section.icon;
              const active = activeSection === section.id;
              return (
                <li key={section.id}>
                  <button
                    type="button"
                    onClick={() => setActiveSection(section.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                      active
                        ? "bg-primary/15 font-semibold text-primary"
                        : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{section.label}</span>
                    <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 opacity-60", active && "opacity-100")} />
                  </button>
                  {active && (
                    <p className="px-3 pb-1 text-[11px] leading-relaxed text-muted-foreground lg:hidden">
                      {section.hint}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="min-w-0 flex-1">
      {activeSection === "stock-universe" && (
      <GlassCard className="mb-0">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
              <ListOrdered className="h-4 w-4 text-primary" /> A 股股票列表
            </h3>
            <p className="text-xs text-muted-foreground">
              启动时只读本地缓存；点「刷新列表」才按下方顺序从网络拉取并落盘。
              网络顺序由环境变量 <code className="rounded bg-muted/50 px-1">STOCK_LIST_SOURCES</code> 控制（默认东财 → AkShare）。
            </p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void doRefreshStockUni()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            {(stockRefreshing || stockUni?.refreshing) ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {(stockRefreshing || stockUni?.refreshing) ? "刷新中…" : "刷新列表"}
          </button>
        </div>

        <div className="mb-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
          <div className="text-[11px] font-medium text-muted-foreground">读取 / 刷新顺序</div>
          <ol className="mt-1.5 space-y-1 text-sm">
            {(stockUni?.read_order || [
              { id: "cache", label: "本地缓存" },
              { id: "eastmoney", label: "东财" },
              { id: "akshare", label: "AkShare" },
            ]).map((src, idx) => (
              <li key={src.id} className="flex items-center gap-2">
                <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary">
                  {idx + 1}
                </span>
                <span>{src.label}</span>
                {src.id === "cache" && (
                  <span className="text-[11px] text-muted-foreground">（启动时）</span>
                )}
                {src.id !== "cache" && idx === 1 && (
                  <span className="text-[11px] text-muted-foreground">（刷新时首选）</span>
                )}
              </li>
            ))}
          </ol>
        </div>

        {stockUni ? (
          <div className="space-y-1 text-sm">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{stockUni.loaded ? `已载入 ${stockUni.count} 只` : "尚未载入"}</span>
              {stockUni.updated_at && <span>更新 {stockUni.updated_at}</span>}
              {stockUni.source && (
                <span>
                  来源 {stockUni.from_cache ? "本地缓存" : stockUni.source === "eastmoney" ? "东财" : stockUni.source === "akshare" ? "AkShare" : stockUni.source}
                </span>
              )}
            </div>
            <div className="break-all text-[11px] text-muted-foreground">
              缓存文件：{stockUni.cache_path}
              {!stockUni.cache_exists && !stockUni.loaded && (
                <span className="ml-2 text-amber-700 dark:text-amber-300">尚无缓存，请先刷新</span>
              )}
            </div>
            {!stockUni.loaded && stockUni.error && (
              <p className="text-xs text-amber-700 dark:text-amber-300">{stockUni.error}</p>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 正在读取状态…
          </div>
        )}
      </GlassCard>
      )}

      {activeSection === "data-dirs" && (
      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <HardDrive className="h-4 w-4 text-primary" /> 数据目录
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          请求缓存和复盘产物都落在这个目录里。点击路径或「打开」会用资源管理器打开（后端需跑在本机）。
        </p>
        <div className="space-y-2">
          <DirRow
            label="数据根目录"
            path={status?.root}
            opening={opening === "root"}
            disabled={busy && opening !== "root"}
            onOpen={() => void openDir("root")}
          />
          <DirRow
            label="cache 缓存"
            path={status?.cache_dir}
            opening={opening === "cache"}
            disabled={busy && opening !== "cache"}
            onOpen={() => void openDir("cache")}
          />
          <DirRow
            label="长序列库（series.db）"
            path={series?.db_path}
            opening={opening === "series"}
            disabled={busy && opening !== "series"}
            onOpen={() => void openDir("series")}
          />
        </div>
        {!loaded ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 正在统计…
          </div>
        ) : (
          <div className="mt-3 space-y-3 text-sm">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{status?.file_count ?? 0} 个文件</span>
              <span>{fmtBytes(status?.byte_count ?? 0)}</span>
              {(status?.skipped_logs ?? 0) > 0 && <span>已跳过 {status?.skipped_logs} 个日志/临时文件</span>}
            </div>
            {status?.folders?.length ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {status.folders.map((f) => (
                  <div key={f.name} className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
                    <div className="font-medium">{f.name === "cache" ? "cache（请求缓存）" : f.name}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {f.files} 个文件 · {fmtBytes(f.bytes)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">还没有可备份的数据。</p>
            )}
          </div>
        )}
      </GlassCard>
      )}

      {activeSection === "series" && (
      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Database className="h-4 w-4 text-primary" /> 长序列（SQLite）
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          两融、上证、成交额、情绪分位等增长型序列存在
          <code className="mx-0.5 rounded bg-muted/50 px-1">cache/series.db</code>
          。完整备份已含该库；下面可单独导出为可读 JSON，方便查阅或迁移。
        </p>
        {series && (series.total_days ?? 0) > 0 ? (
          <div className="mb-3 grid gap-2 sm:grid-cols-2">
            {series.series.map((s) => (
              <div key={s.name} className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
                <div className="font-medium">{SERIES_LABELS[s.name] || s.name}</div>
                <div className="text-[11px] text-muted-foreground">
                  {s.days} 日
                  {s.first && s.last ? ` · ${s.first} → ${s.last}` : ""}
                  {s.updated_at ? ` · 更新 ${s.updated_at}` : ""}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mb-3 text-sm text-muted-foreground">尚无长序列数据（刷新分位或市场序列后会出现）。</p>
        )}
        <div className="mb-2 text-xs text-muted-foreground">
          库体积 {fmtBytes(series?.byte_count ?? 0)} · 合计 {series?.total_days ?? 0} 行
        </div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">长序列导出目录</label>
        <input
          value={seriesDestDir}
          onChange={(e) => setSeriesDestDir(e.target.value)}
          placeholder="例如 D:\备份 或留空则用上方导出目录"
          className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <button
          disabled={busy}
          onClick={doExportSeries}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
        >
          {exportingSeries ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOutput className="h-4 w-4" />}
          {exportingSeries ? "正在导出…" : "导出长序列 JSON"}
        </button>
      </GlassCard>
      )}

      {activeSection === "import-export" && (
      <>
      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <FolderOutput className="h-4 w-4 text-primary" /> 导出全量备份
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          填写本机目录，会在该目录生成 <code className="rounded bg-muted/50 px-1">duanxian-agents-日期时间.zip</code>
          （含 series.db 与按日 JSON）。也可以直接下载到浏览器默认下载位置。
        </p>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">导出目录</label>
        <input
          value={destDir}
          onChange={(e) => setDestDir(e.target.value)}
          placeholder="例如 D:\备份 或 C:\Users\你的用户名\Desktop"
          className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            disabled={busy}
            onClick={doExport}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Archive className="h-4 w-4" />}
            {exporting ? "正在打包…" : "打包到目录"}
          </button>
          <button
            disabled={busy}
            onClick={doDownload}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {downloading ? "正在打包…" : "下载压缩包"}
          </button>
        </div>
      </GlassCard>

      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <FolderInput className="h-4 w-4 text-primary" /> 导入
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          可以导入本功能打出来的 zip，也可以导入已经解压的文件夹（或原始
          <code className="mx-0.5 rounded bg-muted/50 px-1">duanxian-agents</code>
          数据目录）。同路径文件会被覆盖，日志仍会跳过。体积较大时请填本机路径。
        </p>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">压缩包或文件夹路径</label>
        <input
          value={srcPath}
          onChange={(e) => setSrcPath(e.target.value)}
          placeholder="例如 D:\备份\duanxian-agents-20260818-220000.zip"
          className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            disabled={busy}
            onClick={doImportPath}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderInput className="h-4 w-4" />}
            {importing ? "正在导入…" : "从路径导入"}
          </button>
          <button
            disabled={busy}
            onClick={() => zipRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <Upload className="h-4 w-4" /> 选择压缩包
          </button>
          <input
            ref={zipRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void doImportZip(file);
            }}
          />
        </div>
      </GlassCard>
      </>
      )}
        </div>
      </div>
    </div>
  );
}
