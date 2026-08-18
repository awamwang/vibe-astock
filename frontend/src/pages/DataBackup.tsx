import { useEffect, useRef, useState } from "react";
import {
  Archive, Download, FolderInput, FolderOpen, FolderOutput, HardDrive, Loader2, Upload,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api, downloadBackup, type BackupStatus,
} from "@/lib/api";

const DEST_KEY = "va-backup-dest";
const SRC_KEY = "va-backup-src";

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
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [destDir, setDestDir] = useState(() => readLocal(DEST_KEY));
  const [srcPath, setSrcPath] = useState(() => readLocal(SRC_KEY));
  const [exporting, setExporting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [opening, setOpening] = useState<"root" | "cache" | null>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  const reload = () =>
    api.backupStatus().then(setStatus).catch(() => setStatus(null)).finally(() => setLoaded(true));

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const busy = exporting || downloading || importing || opening !== null;

  const openDir = async (kind: "root" | "cache") => {
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

  return (
    <div>
      <PageHeader
        title="数据管理"
        subtitle="查看本机数据目录，打包导出已落盘的请求缓存与生成结果，也可从压缩包或文件夹导入"
      />

      <GlassCard className="mb-4">
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

      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <FolderOutput className="h-4 w-4 text-primary" /> 导出
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          填写本机目录，会在该目录生成 <code className="rounded bg-muted/50 px-1">duanxian-agents-日期时间.zip</code>。
          也可以直接下载到浏览器默认下载位置。
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

      <GlassCard>
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
    </div>
  );
}
