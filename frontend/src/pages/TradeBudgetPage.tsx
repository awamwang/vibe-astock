import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Loader2, Plus, Trash2, Upload, Wallet } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { TradeBudgetCard } from "@/components/TradeBudgetCard";
import { PortfolioJsonImport } from "@/components/PortfolioJsonImport";
import { api, type PortfolioData, type TradeAccount, type TradeGuard, type TradePhaseRow, type TradeSizeResult } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DOWN_TEXT, UP_TEXT } from "@/lib/colors";

function pct(v?: number | null, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function money(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function money2(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

export function TradeBudgetPage() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") || "";
  const [guard, setGuard] = useState<TradeGuard | null>(null);
  const [account, setAccount] = useState<TradeAccount | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [phases, setPhases] = useState<TradePhaseRow[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [equityInput, setEquityInput] = useState("");
  const [equityNote, setEquityNote] = useState("");
  const [overridePhase, setOverridePhase] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [stopPct, setStopPct] = useState("5");
  const [boards, setBoards] = useState("1");
  const [size, setSize] = useState<TradeSizeResult | null>(null);
  const [addCode, setAddCode] = useState("");
  const [addShares, setAddShares] = useState("");
  const [addCost, setAddCost] = useState("");
  const [jsonOpen, setJsonOpen] = useState(false);

  const load = useCallback(async (d?: string) => {
    setBusy(true);
    setErr("");
    try {
      const [g, a, p, ph] = await Promise.all([
        api.tradeGuard(d || undefined),
        api.tradeAccount(),
        api.portfolio(),
        api.tradePhases(),
      ]);
      setGuard(g);
      setAccount(a);
      setPortfolio(p);
      setPhases(ph.phases || []);
      if (a.equity != null) setEquityInput(String(a.equity));
      setEquityNote(a.equity_note || "");
      if (g.date && g.date !== date) {
        setParams((prev) => {
          const n = new URLSearchParams(prev);
          n.set("date", g.date);
          return n;
        }, { replace: true });
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [date, setParams]);

  useEffect(() => { void load(date || undefined); }, [date]); // eslint-disable-line react-hooks/exhaustive-deps

  const budget = guard?.budget;

  async function saveEquity() {
    const n = Number(equityInput);
    if (!Number.isFinite(n) || n < 0) { setErr("权益须为非负数字"); return; }
    setBusy(true);
    try {
      const a = await api.setTradeEquity(n, equityNote);
      setAccount(a);
      await load(date || undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "保存权益失败");
    } finally {
      setBusy(false);
    }
  }

  async function refreshBudget() {
    setBusy(true);
    try {
      await api.tradeBudgetRefresh(date || undefined);
      await load(date || undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "刷新预算失败");
    } finally {
      setBusy(false);
    }
  }

  async function applyOverride() {
    if (!date) return;
    setBusy(true);
    try {
      await api.tradeOverride(date, overridePhase || null, overrideReason);
      setOverridePhase("");
      setOverrideReason("");
      await load(date);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "覆盖失败");
    } finally {
      setBusy(false);
    }
  }

  async function clearOverride() {
    if (!date) return;
    setBusy(true);
    try {
      await api.tradeOverride(date, null, "");
      await load(date);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "清除覆盖失败");
    } finally {
      setBusy(false);
    }
  }

  async function snap() {
    if (!date) return;
    const fields = account?.account_fields || {};
    const mv = portfolio?.totals?.market_value
      ?? fields.stock_market_value
      ?? 0;
    setBusy(true);
    try {
      await api.tradeSnapshot(date, mv, {
        account_fields: fields,
        note: equityNote || undefined,
      });
      await load(date);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "快照失败");
    } finally {
      setBusy(false);
    }
  }

  const snapRows = useMemo(() => {
    const snaps = account?.snapshots || {};
    return Object.entries(snaps)
      .map(([d, s]) => ({ date: d, ...s }))
      .sort((a, b) => (a.date < b.date ? 1 : -1));
  }, [account]);

  async function calcSize() {
    const sp = Number(stopPct) / 100;
    if (!Number.isFinite(sp) || sp <= 0) { setErr("止损幅度须 > 0"); return; }
    setBusy(true);
    try {
      const r = await api.tradeSize({
        date: date || undefined,
        stop_pct: sp,
        boards: boards ? Number(boards) : null,
      });
      setSize(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "计算失败");
    } finally {
      setBusy(false);
    }
  }

  async function addHolding() {
    const code = addCode.trim();
    const shares = Number(addShares);
    const cost = Number(addCost);
    if (!/^\d{6}$/.test(code) || !(shares > 0) || !(cost > 0)) {
      setErr("持仓：代码 6 位、数量与成本须 > 0");
      return;
    }
    setBusy(true);
    try {
      const p = await api.addHolding(code, shares, cost);
      setPortfolio(p);
      setAddCode(""); setAddShares(""); setAddCost("");
      await load(date || undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加仓失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeHolding(code: string) {
    setBusy(true);
    try {
      const p = await api.removeHolding(code);
      setPortfolio(p);
      await load(date || undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  const blocks = useMemo(() => guard?.block_new_long_reasons || [], [guard]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      <PageHeader
        title="持仓与预算"
        subtitle="本地权益与仓位上限对照；不荐股、不下单。预算与 AI 复盘隔离。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setJsonOpen(true)} disabled={busy}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">
              <Upload className="h-4 w-4" />
              导入 JSON
            </button>
            <button onClick={() => void refreshBudget()} disabled={busy}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              重算今日预算
            </button>
          </div>
        }
      />

      {err && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">{err}</div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <TradeBudgetCard b={budget} date={date || budget?.date} />

        <div className="glass space-y-3 rounded-2xl p-5">
          <div className="flex items-center gap-1.5">
            <Wallet className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold">账户权益</h3>
          </div>
          <p className="text-[11px] text-muted-foreground">
            总权益可手改；JSON 导入的账户名/资金余额/可用/市值/当日盈亏等会命名写入日快照，同日覆盖。v1 不自动清仓。
          </p>
          <div className="flex flex-wrap gap-2">
            <input value={equityInput} onChange={(e) => setEquityInput(e.target.value)}
              placeholder="总权益（元）"
              className="w-40 rounded-lg border border-border bg-card px-3 py-2 text-sm tabular-nums" />
            <input value={equityNote} onChange={(e) => setEquityNote(e.target.value)}
              placeholder="备注（可选）"
              className="min-w-[10rem] flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm" />
            <button onClick={() => void saveEquity()} disabled={busy}
              className="rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary">保存</button>
            <button onClick={() => void snap()} disabled={busy || !date}
              className="rounded-lg border border-border px-3 py-2 text-sm">写入日快照</button>
          </div>
          {account?.account_fields && Object.keys(account.account_fields).length > 0 && (
            <div className="text-[11px] leading-relaxed text-muted-foreground">
              {[
                account.account_fields.account_name && `账户名 ${account.account_fields.account_name}`,
                account.account_fields.cash_balance != null && `资金余额 ${account.account_fields.cash_balance}`,
                account.account_fields.account_display && `右下角 ${account.account_fields.account_display}`,
                account.account_fields.broker && `来源 ${account.account_fields.broker}`,
                account.account_fields.available != null && `可用 ${account.account_fields.available}`,
                account.account_fields.stock_market_value != null && `市值 ${account.account_fields.stock_market_value}`,
                account.account_fields.daily_pnl != null && `当日盈亏 ${account.account_fields.daily_pnl}`,
                account.account_fields.daily_pnl_pct != null && `当日盈亏比 ${account.account_fields.daily_pnl_pct}%`,
              ].filter(Boolean).join(" · ")}
            </div>
          )}
          {account?.constants && (
            <div className="text-[11px] text-muted-foreground">
              单笔风险 {pct(account.constants.risk_per_trade, 1)} ·
              日亏损限 {pct(account.constants.daily_loss_limit, 0)} ·
              软/硬回撤 {pct(account.constants.max_dd_soft, 0)}/{pct(account.constants.max_dd_hard, 0)}
              （周末再调，盘中不改）
            </div>
          )}
        </div>
      </div>

      {snapRows.length > 0 && (
        <div className="glass rounded-2xl p-5">
          <h3 className="mb-2 text-sm font-bold">日快照（按日覆盖）</h3>
          <p className="mb-3 text-[11px] text-muted-foreground">
            同一交易日再次写入会整行覆盖；含账户名、资金余额、可用、市值、当日盈亏等命名栏位。
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[48rem] text-left text-[12px]">
              <thead className="text-[11px] text-muted-foreground">
                <tr>
                  <th className="py-1 pr-2">日期</th>
                  <th className="pr-2">权益</th>
                  <th className="pr-2">市值</th>
                  <th className="pr-2">可用</th>
                  <th className="pr-2">资金余额</th>
                  <th className="pr-2">当日盈亏</th>
                  <th className="pr-2">盈亏比</th>
                  <th className="pr-2">账户</th>
                  <th>摘要</th>
                </tr>
              </thead>
              <tbody>
                {snapRows.map((s) => (
                  <tr key={s.date} className={cn("border-t border-border/50", s.date === date && "bg-primary/5")}>
                    <td className="py-1.5 pr-2 font-mono tabular-nums">{s.date}</td>
                    <td className="pr-2 tabular-nums">{money(s.equity)}</td>
                    <td className="pr-2 tabular-nums">{money(s.market_value ?? s.stock_market_value)}</td>
                    <td className="pr-2 tabular-nums">{s.available != null ? money2(s.available) : "—"}</td>
                    <td className="pr-2 tabular-nums">{s.cash_balance != null ? money2(s.cash_balance) : "—"}</td>
                    <td className={cn("pr-2 tabular-nums", (s.daily_pnl ?? 0) < 0 ? DOWN_TEXT : (s.daily_pnl ?? 0) > 0 ? UP_TEXT : "")}>
                      {s.daily_pnl != null ? money2(s.daily_pnl) : "—"}
                    </td>
                    <td className={cn("pr-2 tabular-nums", (s.daily_pnl_pct ?? 0) < 0 ? DOWN_TEXT : (s.daily_pnl_pct ?? 0) > 0 ? UP_TEXT : "")}>
                      {s.daily_pnl_pct != null ? `${s.daily_pnl_pct}%` : "—"}
                    </td>
                    <td className="pr-2 max-w-[8rem] truncate" title={s.account_name || s.account_display || ""}>
                      {s.account_display || s.account_name || "—"}
                    </td>
                    <td className="max-w-[16rem] truncate text-muted-foreground" title={s.summary || ""}>
                      {s.summary || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 手拨档位 */}
      <div className="glass rounded-2xl p-5">
        <h3 className="mb-2 text-sm font-bold">人手覆盖档位</h3>
        <p className="mb-3 text-[11px] text-muted-foreground">
          规则档与覆盖档并排；覆盖只改 Cap，不改账户常量。清空覆盖即回到硬规则结果。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select value={overridePhase} onChange={(e) => setOverridePhase(e.target.value)}
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
            <option value="">选择覆盖档…</option>
            {phases.map((p) => (
              <option key={p.phase} value={p.phase}>
                {p.phase}（总仓 {Math.round(p.cap_total * 100)}% / 单票 {Math.round(p.cap_single * 100)}%）
              </option>
            ))}
          </select>
          <input value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="覆盖原因（必填建议）"
            className="min-w-[12rem] flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm" />
          <button onClick={() => void applyOverride()} disabled={busy || !overridePhase}
            className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
            应用覆盖
          </button>
          <button onClick={() => void clearOverride()} disabled={busy || !budget?.override_phase}
            className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
            清除覆盖
          </button>
        </div>
        {budget?.classify_reasons?.length ? (
          <ul className="mt-3 list-inside list-disc text-[11px] text-muted-foreground">
            {budget.classify_reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        ) : null}
      </div>

      {/* 闸门 + 现仓 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="glass rounded-2xl p-5">
          <h3 className="mb-2 text-sm font-bold">开仓闸（只读提示）</h3>
          {blocks.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">当前无拦截项（仍须自担风险）。</p>
          ) : (
            <ul className="list-inside list-disc text-[13px] text-danger">
              {blocks.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {guard?.daily_loss && (
            <p className={cn("mt-2 text-[12px]", guard.daily_loss.hit ? "text-danger" : "text-muted-foreground")}>
              相对 {guard.daily_loss.prev_date} 快照权益：
              {(guard.daily_loss.pnl_pct * 100).toFixed(2)}%
              （限额 -{(guard.daily_loss.limit * 100).toFixed(0)}%）
            </p>
          )}
          {guard?.position && (
            <div className="mt-3 border-t border-dashed border-border pt-3 text-[13px]">
              <div>现仓市值 {money(guard.position.market_value)} ·
                占总权益 {pct(guard.position.total_pct, 1)} ·
                剩余额度 {money(guard.position.remain_total)}
              </div>
              {guard.position.breaches.map((b) => (
                <div key={b} className="text-danger">{b}</div>
              ))}
            </div>
          )}
        </div>

        <div className="glass rounded-2xl p-5">
          <h3 className="mb-2 text-sm font-bold">单笔金额计算器</h3>
          <div className="flex flex-wrap gap-2">
            <label className="text-[12px] text-muted-foreground">
              止损 %
              <input value={stopPct} onChange={(e) => setStopPct(e.target.value)}
                className="ml-1 w-16 rounded border border-border bg-card px-2 py-1 tabular-nums" />
            </label>
            <label className="text-[12px] text-muted-foreground">
              板位
              <select value={boards} onChange={(e) => setBoards(e.target.value)}
                className="ml-1 rounded border border-border bg-card px-2 py-1">
                <option value="1">首板</option>
                <option value="2">二板</option>
                <option value="3">三板+</option>
              </select>
            </label>
            <button onClick={() => void calcSize()} disabled={busy}
              className="rounded-lg bg-primary/15 px-3 py-1.5 text-sm text-primary">计算</button>
          </div>
          {size && (
            <div className="mt-3 text-[13px]">
              {size.ok ? (
                <>
                  <div className="text-2xl font-extrabold tabular-nums">{money(size.amount)} 元</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    单票上限 {money(size.components?.by_single_cap)} ·
                    风险倒推 {money(size.components?.by_risk)} ·
                    剩余总仓 {money(size.components?.remain_total)} ·
                    板位折扣 {size.components?.board_discount}
                  </div>
                </>
              ) : (
                <div className="text-warning">{size.reason}</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 减仓顺序 */}
      {(guard?.reduce_order || []).length > 0 && (
        <div className="glass rounded-2xl p-5">
          <h3 className="mb-2 text-sm font-bold">降档减仓顺序（浮盈从差到好）</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-[11px] text-muted-foreground">
                <tr>
                  <th className="py-1">代码</th><th>名称</th><th>市值</th><th>浮盈</th><th>动作</th>
                </tr>
              </thead>
              <tbody>
                {guard!.reduce_order.map((r) => (
                  <tr key={r.code} className="border-t border-border/50">
                    <td className="py-1.5 font-mono">{r.code}</td>
                    <td>{r.name}</td>
                    <td className="tabular-nums">{money(r.market_value)}</td>
                    <td className={cn("tabular-nums", (r.pnl ?? 0) >= 0 ? UP_TEXT : DOWN_TEXT)}>
                      {money(r.pnl)}
                    </td>
                    <td>
                      {r.action}
                      {r.suggest_cut ? ` ${money(r.suggest_cut)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <PortfolioJsonImport
        open={jsonOpen}
        onClose={() => setJsonOpen(false)}
        onApplied={() => load(date || undefined)}
      />

      {/* 持仓录入 */}
      <div className="glass rounded-2xl p-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-bold">本地持仓</h3>
          <button type="button" onClick={() => setJsonOpen(true)} disabled={busy}
            className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-[12px] text-muted-foreground hover:bg-muted hover:text-foreground">
            <Upload className="h-3.5 w-3.5" />
            导入 JSON
          </button>
        </div>
        <p className="mb-3 text-[11px] text-muted-foreground">
          数据在 ~/.vibe-research/portfolio.json，不上传、不进复盘 JSON。也可导入 ScreenshotDraft / 单条持仓 JSON。
        </p>
        <div className="mb-3 flex flex-wrap gap-2">
          <input value={addCode} onChange={(e) => setAddCode(e.target.value)} placeholder="代码"
            className="w-24 rounded-lg border border-border bg-card px-2 py-1.5 font-mono text-sm" />
          <input value={addShares} onChange={(e) => setAddShares(e.target.value)} placeholder="股数"
            className="w-24 rounded-lg border border-border bg-card px-2 py-1.5 text-sm tabular-nums" />
          <input value={addCost} onChange={(e) => setAddCost(e.target.value)} placeholder="成本"
            className="w-24 rounded-lg border border-border bg-card px-2 py-1.5 text-sm tabular-nums" />
          <button onClick={() => void addHolding()} disabled={busy}
            className="flex items-center gap-1 rounded-lg bg-primary/15 px-3 py-1.5 text-sm text-primary">
            <Plus className="h-3.5 w-3.5" /> 加入
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-[11px] text-muted-foreground">
              <tr>
                <th className="py-1">代码</th><th>名称</th><th>市值</th><th>浮盈</th><th>占权益</th><th />
              </tr>
            </thead>
            <tbody>
              {(portfolio?.holdings || []).map((h) => {
                const over = guard?.position?.per_name?.find((x) => x.code === h.code)?.over_single;
                const pe = guard?.equity && guard.equity > 0
                  ? h.market_value / guard.equity : null;
                return (
                  <tr key={h.code} className="border-t border-border/50">
                    <td className="py-1.5 font-mono">{h.code}</td>
                    <td>{h.name}</td>
                    <td className="tabular-nums">{money(h.market_value)}</td>
                    <td className={cn("tabular-nums", h.pnl >= 0 ? UP_TEXT : DOWN_TEXT)}>
                      {money(h.pnl)}（{h.pnl_pct.toFixed(1)}%）
                    </td>
                    <td className={cn("tabular-nums", over && "text-danger")}>{pct(pe, 1)}</td>
                    <td>
                      <button onClick={() => void removeHolding(h.code)} title="删除"
                        className="rounded p-1 text-muted-foreground hover:text-danger">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
              {(portfolio?.holdings || []).length === 0 && (
                <tr><td colSpan={6} className="py-4 text-center text-muted-foreground">暂无持仓</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
