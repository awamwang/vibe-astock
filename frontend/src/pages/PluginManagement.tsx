import { useEffect, useState } from "react";
import {
  AlertTriangle, ChevronDown, ChevronRight, Eye, EyeOff, FolderOpen, Loader2,
  Plug, Plus, Power, PowerOff, Save, Trash2, Upload,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type PluginEnvField, type PluginRecord, type PluginRuntimeStatus } from "@/lib/api";

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

function RuntimeStatusPanel({ status }: { status: PluginRuntimeStatus }) {
  const levelStyles: Record<PluginRuntimeStatus["level"], string> = {
    ok: "border-success/30 bg-success/10 text-success",
    info: "border-primary/30 bg-primary/10 text-primary",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
    error: "border-danger/30 bg-danger/10 text-danger",
    off: "border-border bg-muted/20 text-muted-foreground",
  };
  const levelLabel: Record<PluginRuntimeStatus["level"], string> = {
    ok: "正常",
    info: "提示",
    warn: "警告",
    error: "错误",
    off: "停用",
  };

  return (
    <div className={`mt-2 rounded-lg border px-2.5 py-2 text-xs ${levelStyles[status.level]}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className="font-medium">{levelLabel[status.level]}</span>
        <span className="text-foreground/90">{status.message}</span>
        {status.updated_at && (
          <span className="text-[10px] opacity-70">{status.updated_at}</span>
        )}
      </div>
      {status.detail && (
        <pre className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all text-[10px] text-foreground/80 opacity-90">
          {status.detail}
        </pre>
      )}
    </div>
  );
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

type EnvRow = {
  key: string;
  value: string;
  secret: boolean;
  label: string;
  hint: string;
  locked: boolean;
  defaultValue: string;
};

function rowsFromEnv(fields: PluginEnvField[], env: Record<string, string>): EnvRow[] {
  const known = new Set(fields.map((f) => f.key));
  const rows: EnvRow[] = fields.map((f) => ({
    key: f.key,
    value: env[f.key] ?? "",
    secret: f.secret,
    label: f.label,
    hint: f.hint,
    locked: true,
    defaultValue: f.default || "",
  }));
  Object.entries(env).forEach(([key, value]) => {
    if (known.has(key)) return;
    rows.push({
      key,
      value,
      secret: false,
      label: "",
      hint: "",
      locked: false,
      defaultValue: "",
    });
  });
  return rows;
}

function PluginEnvPanel({
  pluginId, pluginName, disabled, onSaved,
}: {
  pluginId: string;
  pluginName: string;
  disabled: boolean;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [file, setFile] = useState("");
  const [error, setError] = useState("");
  const [rows, setRows] = useState<EnvRow[]>([]);
  const [shown, setShown] = useState<Record<string, boolean>>({});

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.pluginsEnv(pluginId);
      setFile(data.file || "");
      setError(data.error || "");
      setRows(rowsFromEnv(data.fields || [], data.env || {}));
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取配置失败");
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) void load();
  };

  const update = (index: number, patch: Partial<EnvRow>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const save = async () => {
    const env: Record<string, string> = {};
    for (const row of rows) {
      const key = row.key.trim();
      if (!key && !row.value) continue;
      if (!key) {
        toast.error("有配置项未填写键名");
        return;
      }
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
        toast.error(`配置键无效：${key}`);
        return;
      }
      if (key in env) {
        toast.error(`配置键重复：${key}`);
        return;
      }
      env[key] = row.value;
    }
    setSaving(true);
    try {
      const r = await api.pluginsSaveEnv(pluginId, env);
      setFile(r.file || file);
      if (r.reload_error) {
        toast.error(r.reload_error);
      } else if (r.reloaded) {
        toast.success(`已保存 ${pluginName} 的配置，并重新加载插件`);
      } else {
        toast.success(`已保存 ${pluginName} 的配置，启用后生效`);
      }
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full rounded-lg border border-border bg-black/20 px-2.5 py-1.5 text-xs outline-none focus:border-primary/50 disabled:opacity-50";

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        配置
      </button>
      {open && (
        <div className="mt-2 rounded-lg border border-border bg-black/10 px-3 py-3">
          <p className="text-[11px] text-muted-foreground">
            键值写在用户目录，与插件注册表一起保存
            {file ? <>：<span className="break-all">{file}</span></> : "（plugins.plugin-env）"}
            。已填写的项优先于插件目录 .env；留空则回落。已启用的插件保存后会重新加载。
          </p>
          {loading ? (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> 读取配置…
            </div>
          ) : (
            <>
              {error && (
                <p className="mt-2 text-[11px] text-amber-600 dark:text-amber-400">
                  未能读取插件声明的配置项，仍可手工填写键值。{error}
                </p>
              )}
              <div className="mt-2 space-y-2">
                {rows.length === 0 && (
                  <p className="text-xs text-muted-foreground">暂无配置项，可添加键值。</p>
                )}
                {rows.map((row, index) => (
                  <div key={`${row.locked ? "d" : "c"}-${index}`} className="space-y-1">
                    {row.label && (
                      <div className="text-[11px] text-muted-foreground">{row.label}</div>
                    )}
                    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
                      <input
                        value={row.key}
                        readOnly={row.locked}
                        disabled={disabled || saving}
                        onChange={(e) => update(index, { key: e.target.value })}
                        placeholder="KEY"
                        spellCheck={false}
                        className={`${inputCls} sm:w-56 ${row.locked ? "text-muted-foreground" : ""}`}
                      />
                      <div className="flex min-w-0 flex-1 gap-1.5">
                        <input
                          value={row.value}
                          disabled={disabled || saving}
                          type={row.secret && !shown[row.key] ? "password" : "text"}
                          onChange={(e) => update(index, { value: e.target.value })}
                          placeholder={row.defaultValue || "VALUE"}
                          autoComplete="off"
                          spellCheck={false}
                          className={inputCls}
                        />
                        {row.secret && (
                          <button
                            type="button"
                            disabled={disabled || saving}
                            onClick={() => setShown((s) => ({ ...s, [row.key]: !s[row.key] }))}
                            className="inline-flex shrink-0 items-center rounded-lg border border-border px-2 text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                            title={shown[row.key] ? "隐藏" : "显示"}
                          >
                            {shown[row.key] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                          </button>
                        )}
                        {!row.locked && (
                          <button
                            type="button"
                            disabled={disabled || saving}
                            onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}
                            className="inline-flex shrink-0 items-center rounded-lg px-2 text-muted-foreground hover:bg-muted/40 hover:text-destructive disabled:opacity-50"
                            title="删除"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                    {row.hint && (
                      <p className="text-[10px] text-muted-foreground/80">{row.hint}</p>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={disabled || saving}
                  onClick={() => setRows((prev) => [...prev, {
                    key: "", value: "", secret: false, label: "", hint: "", locked: false, defaultValue: "",
                  }])}
                  className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                >
                  <Plus className="h-3.5 w-3.5" /> 添加一项
                </button>
                <button
                  type="button"
                  disabled={disabled || saving}
                  onClick={() => void save()}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary/15 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  保存
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PluginRow({
  row, busy, onEnable, onDisable, onUninstall, onOpenDir, onEnvSaved,
}: {
  row: PluginRecord;
  busy: boolean;
  onEnable: () => void;
  onDisable: () => void;
  onUninstall: () => void;
  onOpenDir: () => void;
  onEnvSaved: () => void;
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
          <RuntimeStatusPanel status={row.runtime_status} />
          <PluginEnvPanel
            pluginId={row.id}
            pluginName={row.name}
            disabled={busy}
            onSaved={onEnvSaved}
          />
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
  const [envFile, setEnvFile] = useState("");
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
        setEnvFile(r.env_file || "");
      })
      .catch(() => {
        setPlugins([]);
        setRegistryFile("");
        setEnvFile("");
      })
      .finally(() => setLoaded(true));

  const needsStatusPoll = plugins.some((p) => {
    const lv = p.runtime_status?.level;
    const msg = p.runtime_status?.message || "";
    return lv === "info" || lv === "warn" || lv === "error"
      || msg.includes("加载中") || msg.includes("自动重启");
  });

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 启动/重启占位或异常态时轮询，便于加载完毕后看到恢复后的状态
  useEffect(() => {
    if (!needsStatusPoll) return;
    const t = window.setInterval(() => {
      void reload();
    }, 2000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsStatusPoll]);

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
        subtitle="管理钩子插件：选择 .py 入口安装、启用/停用、从注册表卸载。每条插件可展开键值配置，与注册表一起写到用户目录。"
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
          <p className="mb-1 text-[11px] text-muted-foreground">
            注册表：<span className="break-all">{registryFile}</span>
          </p>
        )}
        {envFile && (
          <p className="mb-3 text-[11px] text-muted-foreground">
            键值配置：<span className="break-all">{envFile}</span>
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
                onEnvSaved={() => { void reload(); }}
              />
            ))}
          </ul>
        )}
      </GlassCard>
    </div>
  );
}
