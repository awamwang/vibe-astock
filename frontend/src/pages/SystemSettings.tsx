import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronRight, Globe2, Loader2, Network, Save, ShieldOff } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api, type ProxyConfig, type ProxyTestResult } from "@/lib/api";
import { parseSystemSection, systemSettingsTo, type SystemSectionId } from "@/lib/settingsNav";

const SYSTEM_SECTIONS: {
  id: SystemSectionId;
  label: string;
  icon: typeof Network;
  hint: string;
}[] = [
  { id: "proxy", label: "代理设置", icon: Network, hint: "出境拉取 / GlobalPercent" },
];

export function SystemSettings() {
  const [searchParams] = useSearchParams();
  const activeSection = parseSystemSection(searchParams.get("section"));

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [url, setUrl] = useState("");
  const [meta, setMeta] = useState<ProxyConfig | null>(null);
  const [testResult, setTestResult] = useState<ProxyTestResult | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const cfg = await api.proxyConfig();
      setMeta(cfg);
      setEnabled(Boolean(cfg.enabled));
      setUrl(cfg.url || "");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "读取代理配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      const cfg = await api.saveProxyConfig({ enabled, url: url.trim() });
      setMeta(cfg);
      setEnabled(Boolean(cfg.enabled));
      setUrl(cfg.url || "");
      toast.success(cfg.enabled ? "代理已启用并保存" : "已保存（代理关闭）");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      const cfg = await api.saveProxyConfig({ enabled: false, url: "" });
      setMeta(cfg);
      setEnabled(false);
      setUrl("");
      toast.success("已清除代理配置");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "清除失败");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testProxyConfig({ enabled, url: url.trim() });
      setTestResult(r);
      if (r.ok) toast.success("至少一侧源站可达");
      else toast.error("两侧源站均不可达，请检查代理或网络");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "连通性测试失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="系统设置"
        subtitle="网络代理等本机运行时选项；影响需访问境外站点的功能（如全球事件概率）"
      />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <nav className="glass shrink-0 rounded-2xl p-2 lg:w-52">
          <p className="px-3 py-2 text-[11px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            设置项
          </p>
          <ul className="space-y-0.5">
            {SYSTEM_SECTIONS.map((section) => {
              const Icon = section.icon;
              const active = activeSection === section.id;
              return (
                <li key={section.id}>
                  <Link
                    to={systemSettingsTo(section.id)}
                    replace
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
                  </Link>
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
          {activeSection === "proxy" && (
            <GlassCard className="mb-0">
              <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
                <Globe2 className="h-4 w-4 text-primary" /> 代理设置
              </h3>
              <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                全球事件概率需访问 Polymarket / Kalshi 公开接口。若本机直连失败，可配置 HTTP 或 SOCKS5 代理。
                环境变量 <code className="rounded bg-muted/50 px-1">VR_PULSE_PROXY</code> 优先级高于本页落盘配置。
              </p>

              {loading ? (
                <p className="text-xs text-muted-foreground">正在读取代理配置…</p>
              ) : (
                <>
                  <label className="mb-3 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      className="h-4 w-4 rounded border-border"
                    />
                    启用代理
                  </label>

                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    代理地址
                  </label>
                  <input
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="socks5://127.0.0.1:7881"
                    disabled={saving}
                    className="mb-2 w-full rounded-lg border border-border bg-black/20 px-3 py-2 font-mono text-sm outline-none focus:border-primary/50 disabled:opacity-50"
                  />
                  <p className="mb-4 text-[11px] leading-relaxed text-muted-foreground/80">
                    示例：<code className="rounded bg-muted/40 px-1">socks5://127.0.0.1:7881</code>
                    {" · "}
                    <code className="rounded bg-muted/40 px-1">http://127.0.0.1:7890</code>
                    。DNS 需走代理时可改用 <code className="rounded bg-muted/40 px-1">socks5h://</code>。
                  </p>

                  {meta?.env_override && (
                    <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
                      当前进程已设置环境变量 <code className="px-0.5">VR_PULSE_PROXY</code>
                      ，实际生效为环境变量，修改本页后需去掉该变量或重启进程才能以落盘配置为准。
                    </p>
                  )}

                  {meta?.effective_url && (
                    <p className="mb-3 text-[11px] text-muted-foreground">
                      当前生效：
                      <code className="ml-1 rounded bg-muted/40 px-1 font-mono">{meta.effective_url}</code>
                      {meta.effective_source ? `（来源 ${meta.effective_source}）` : null}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void save()}
                      disabled={saving || testing}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
                    >
                      {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={() => void test()}
                      disabled={saving || testing}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground hover:bg-muted/40 disabled:opacity-50"
                    >
                      {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Network className="h-3.5 w-3.5" />}
                      测试连通性
                    </button>
                    <button
                      type="button"
                      onClick={() => void clear()}
                      disabled={saving || testing}
                      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
                    >
                      <ShieldOff className="h-3.5 w-3.5" />
                      清除
                    </button>
                  </div>

                  {testResult && (
                    <div className="mt-4 space-y-1.5 rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5 text-[11px]">
                      <p className={testResult.ok ? "text-emerald-600 dark:text-emerald-400" : "text-danger"}>
                        {testResult.ok ? "测试通过（至少一侧可达）" : "测试未通过"}
                        {testResult.proxy ? ` · 使用 ${testResult.proxy}` : " · 直连"}
                      </p>
                      <p className="text-muted-foreground">
                        Polymarket：{testResult.polymarket?.ok
                          ? `OK (${testResult.polymarket.status})`
                          : testResult.polymarket?.error || `失败 (${testResult.polymarket?.status ?? "—"})`}
                      </p>
                      <p className="text-muted-foreground">
                        Kalshi：{testResult.kalshi?.ok
                          ? `OK (${testResult.kalshi.status})`
                          : testResult.kalshi?.error || `失败 (${testResult.kalshi?.status ?? "—"})`}
                      </p>
                    </div>
                  )}
                </>
              )}
            </GlassCard>
          )}
        </div>
      </div>
    </div>
  );
}
