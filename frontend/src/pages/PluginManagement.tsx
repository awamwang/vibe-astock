import { useEffect, useState } from "react";
import {
  AlertTriangle, FolderOpen, Loader2, Plug, Power, PowerOff, Trash2, Upload,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type PluginRecord } from "@/lib/api";

const PATH_KEY = "va-plugin-install-path";

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

function StatusBadge({ enabled, fileExists }: { enabled: boolean; fileExists: boolean }) {
  if (!fileExists) {
    return (
      <span className="rounded bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger">
        文件缺失
      </span>
    );
  }
  if (enabled) {
    return (
      <span className="rounded bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success">
        启用
      </span>
    );
  }
  return (
    <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
      停用
    </span>
  );
}

function PluginRow({
  row, busy, onEnable, onDisable, onUninstall, onOpenDir,
}: {
  row: PluginRecord;
  busy: boolean;
  onEnable: () => void;
  onDisable: () => void;
  onUninstall: () => void;
  onOpenDir: () => void;
}) {
  return (
    <li className="rounded-lg border border-border bg-muted/10 px-3 py-3">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{row.name}</span>
            <span className="text-xs text-muted-foreground">v{row.version || "—"}</span>
            <StatusBadge enabled={row.enabled} fileExists={row.file_exists} />
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            ID <code className="rounded bg-muted/40 px-1">{row.id}</code>
            {row.registered_at && <span className="ml-2">注册于 {row.registered_at}</span>}
          </div>
          <p className="mt-1.5 break-all text-xs text-muted-foreground/90">{row.path}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <button
            type="button"
            disabled={busy}
            onClick={onOpenDir}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
          >
            <FolderOpen className="h-3.5 w-3.5" /> 打开目录
          </button>
          {row.enabled ? (
            <button
              type="button"
              disabled={busy}
              onClick={onDisable}
              className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
            >
              <PowerOff className="h-3.5 w-3.5" /> 停用
            </button>
          ) : (
            <button
              type="button"
              disabled={busy || !row.file_exists}
              onClick={onEnable}
              className="inline-flex items-center gap-1 rounded-lg bg-primary/15 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
            >
              <Power className="h-3.5 w-3.5" /> 启用
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={onUninstall}
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 hover:text-destructive disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" /> 卸载
          </button>
        </div>
      </div>
    </li>
  );
}

export function PluginManagement() {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [registryFile, setRegistryFile] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [installPath, setInstallPath] = useState(() => readLocal(PATH_KEY));
  const [installing, setInstalling] = useState(false);
  const [picking, setPicking] = useState(false);
  const [actingId, setActingId] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  const reload = () =>
    api.pluginsList()
      .then((r) => {
        setPlugins(r.plugins);
        setRegistryFile(r.registry_file);
      })
      .catch(() => {
        setPlugins([]);
        setRegistryFile("");
      })
      .finally(() => setLoaded(true));

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const busy = installing || picking || actingId !== null || openingId !== null;

  const doInstall = async (path?: string) => {
    const p = (path ?? installPath).trim();
    if (!p) {
      toast.error("请填写或选择插件 .py 路径");
      return;
    }
    writeLocal(PATH_KEY, p);
    setInstalling(true);
    try {
      const rec = await api.pluginsRegister(p);
      toast.success(`已安装并启用 ${rec.name}`);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "安装失败");
    } finally {
      setInstalling(false);
    }
  };

  const pickAndInstall = async () => {
    setPicking(true);
    try {
      const initial = installPath.trim();
      const parent = initial.replace(/[/\\][^/\\]+$/, "");
      const r = await api.pluginsPick(parent || undefined);
      if (r.cancelled) return;
      if (!r.path) {
        toast.error("未选择文件");
        return;
      }
      setInstallPath(r.path);
      writeLocal(PATH_KEY, r.path);
      setPicking(false);
      setInstalling(true);
      try {
        const rec = await api.pluginsRegister(r.path);
        toast.success(`已安装并启用 ${rec.name}`);
        await reload();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "安装失败");
      } finally {
        setInstalling(false);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "选择文件失败");
    } finally {
      setPicking(false);
    }
  };

  const act = async (id: string, kind: "enable" | "disable" | "uninstall") => {
    const row = plugins.find((p) => p.id === id);
    if (!row) return;
    if (kind === "uninstall") {
      if (!window.confirm(`从注册表移除「${row.name}」？插件文件不会被删除。`)) return;
    }
    setActingId(id);
    try {
      if (kind === "enable") {
        await api.pluginsEnable(id);
        toast.success(`已启用 ${row.name}`);
      } else if (kind === "disable") {
        await api.pluginsDisable(id);
        toast.success(`已停用 ${row.name}`);
      } else {
        await api.pluginsUninstall(id);
        toast.success(`已卸载 ${row.name}`);
      }
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setActingId(null);
    }
  };

  const openDir = async (id: string) => {
    const row = plugins.find((p) => p.id === id);
    if (!row) return;
    setOpeningId(id);
    try {
      const r = await api.pluginsOpenDir(id);
      toast.success(`已打开 ${r.path}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "打开目录失败");
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="插件管理"
        subtitle="管理钩子插件：选择 .py 入口安装、启用/停用、从注册表卸载。变更后需重启 server 才会加载新插件。"
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <span>
          插件须为导出 <code className="rounded bg-muted/40 px-1">PACK</code> 的 Python 文件。
          注册只写入用户目录注册表，不复制文件；卸载不删除 .py。
          安装默认<b className="text-foreground">启用</b>，需在本机运行后端才能弹出文件选择框。
        </span>
      </div>

      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Upload className="h-4 w-4 text-primary" /> 安装插件
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          点击「选择文件并安装」弹出系统文件管理器选取 .py 入口；也可手动填写路径后安装。
        </p>
        <div className="space-y-3">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              插件入口路径
            </label>
            <input
              value={installPath}
              onChange={(e) => setInstallPath(e.target.value)}
              placeholder="例如 G:\Projects\Stock\vibe-astock\plugins\vibe-ths-linker\plugin.py"
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => pickAndInstall()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
            >
              {picking ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
              选择文件并安装
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => doInstall()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
            >
              {installing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}
              安装
            </button>
          </div>
        </div>
      </GlassCard>

      <GlassCard>
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Plug className="h-4 w-4 text-primary" /> 已注册插件
        </h3>
        {registryFile && (
          <p className="mb-3 text-[11px] text-muted-foreground">
            注册表：<span className="break-all">{registryFile}</span>
          </p>
        )}
        {!loaded ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : plugins.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无已注册插件。</p>
        ) : (
          <ul className="space-y-2">
            {plugins.map((row) => (
              <PluginRow
                key={row.id}
                row={row}
                busy={busy}
                onEnable={() => act(row.id, "enable")}
                onDisable={() => act(row.id, "disable")}
                onUninstall={() => act(row.id, "uninstall")}
                onOpenDir={() => openDir(row.id)}
              />
            ))}
          </ul>
        )}
      </GlassCard>
    </div>
  );
}
