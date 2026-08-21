import { useRef, useState } from "react";
import { Loader2, Upload, X } from "lucide-react";
import { ApiError, api, type ScreenshotDraft, type ScreenshotHoldingRow, type TradeAccountFields } from "@/lib/api";
import { cn } from "@/lib/utils";

type AccountFieldKey =
  | "account_name"
  | "account_display"
  | "equity"
  | "cash_balance"
  | "available"
  | "withdrawable"
  | "frozen"
  | "stock_market_value"
  | "position_pnl"
  | "daily_pnl"
  | "daily_pnl_pct";

const ACCOUNT_FIELDS: { key: AccountFieldKey; label: string }[] = [
  { key: "account_name", label: "账户名" },
  { key: "account_display", label: "右下角显示" },
  { key: "equity", label: "总权益/总资产" },
  { key: "cash_balance", label: "资金余额" },
  { key: "available", label: "可用金额" },
  { key: "withdrawable", label: "可取金额" },
  { key: "frozen", label: "冻结金额" },
  { key: "stock_market_value", label: "股票市值" },
  { key: "position_pnl", label: "持仓盈亏" },
  { key: "daily_pnl", label: "当日盈亏" },
  { key: "daily_pnl_pct", label: "当日盈亏比%" },
];

const EMPTY_ACCOUNT: Record<AccountFieldKey, string> = {
  account_name: "",
  account_display: "",
  equity: "",
  cash_balance: "",
  available: "",
  withdrawable: "",
  frozen: "",
  stock_market_value: "",
  position_pnl: "",
  daily_pnl: "",
  daily_pnl_pct: "",
};

const EXAMPLE_DRAFT = `{
  "broker": "示例券商",
  "equity": 100000,
  "cash_balance": 20000,
  "available": 10000,
  "stock_market_value": 80000,
  "holdings": [
    { "code": "600000", "name": "浦发银行", "shares": 1000, "cost": 10.5 }
  ]
}`;

const EXAMPLE_ROW = `{
  "code": "600000",
  "name": "浦发银行",
  "shares": 1000,
  "cost": 10.5
}`;

function numStr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "";
  return String(v);
}

function parseNum(s: string): number | null {
  const t = s.trim().replace(/,/g, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function toFloat(v: unknown): number | null {
  if (v == null || v === "") return null;
  if (typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const s = String(v).trim().replace(/,/g, "").replace(/，/g, "").replace(/%/g, "").replace(/元/g, "");
  if (!s || s === "—" || s === "-" || s === "null") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function normCode(v: unknown): string | null {
  if (v == null) return null;
  let s = String(v).replace(/\D/g, "");
  if (s.length > 6) s = s.slice(-6);
  if (s.length < 6) s = s.padStart(6, "0");
  return /^\d{6}$/.test(s) ? s : null;
}

function buildNote(
  draft: ScreenshotDraft,
  account: Record<AccountFieldKey, string>,
  note: string,
): string {
  const head: string[] = [];
  const name = account.account_name.trim();
  if (name) head.push(`账户名${name}`);
  const cash = parseNum(account.cash_balance) ?? parseNum(account.withdrawable);
  if (cash != null) head.push(`资金余额${cash}`);
  const disp = account.account_display.trim();
  if (disp) head.push(`右下角显示${disp}`);

  const tail: string[] = [];
  const broker = (draft.broker || "").trim();
  if (broker) tail.push(`来源:${broker}`);
  const av = parseNum(account.available);
  if (av != null) tail.push(`可用${av}`);
  const mv = parseNum(account.stock_market_value);
  if (mv != null) tail.push(`市值${Number.isInteger(mv) ? mv : mv}`);
  const dp = parseNum(account.daily_pnl);
  if (dp != null) tail.push(`当日盈亏${dp}`);
  const dpp = parseNum(account.daily_pnl_pct);
  if (dpp != null) tail.push(`当日盈亏比${dpp}%`);

  let auto = "";
  if (head.length && tail.length) auto = `${head.join("，")}｜${tail.join(" · ")}`;
  else if (head.length) auto = head.join("，");
  else if (tail.length) auto = tail.join(" · ");

  const manual = note.trim();
  if (manual && auto) {
    if (manual === auto || manual.includes(auto)) return manual;
    return manual.includes("｜") ? `${manual} · ${auto}` : `${manual}｜${auto}`;
  }
  return manual || auto;
}

function collectFields(
  draft: ScreenshotDraft,
  account: Record<AccountFieldKey, string>,
): TradeAccountFields {
  const out: TradeAccountFields = {};
  const name = account.account_name.trim();
  if (name) out.account_name = name;
  const disp = account.account_display.trim();
  if (disp) out.account_display = disp;
  if (draft.broker?.trim()) out.broker = draft.broker.trim();

  const nums: { key: keyof TradeAccountFields; src: AccountFieldKey }[] = [
    { key: "cash_balance", src: "cash_balance" },
    { key: "available", src: "available" },
    { key: "withdrawable", src: "withdrawable" },
    { key: "frozen", src: "frozen" },
    { key: "stock_market_value", src: "stock_market_value" },
    { key: "position_pnl", src: "position_pnl" },
    { key: "daily_pnl", src: "daily_pnl" },
    { key: "daily_pnl_pct", src: "daily_pnl_pct" },
  ];
  for (const { key, src } of nums) {
    const n = parseNum(account[src]);
    if (n != null) out[key] = n;
  }
  if (out.cash_balance == null && out.withdrawable != null) out.cash_balance = out.withdrawable;
  if (out.withdrawable == null && out.cash_balance != null) out.withdrawable = out.cash_balance;
  return out;
}

function normalizeHoldingRow(raw: Record<string, unknown>): ScreenshotHoldingRow {
  const code = normCode(raw.code);
  if (!code) throw new Error("持仓代码须为 6 位数字");
  const shares = toFloat(raw.shares);
  if (shares == null) throw new Error("持仓股数无效");
  const cost = toFloat(raw.cost);
  const include = shares > 0 && cost != null && cost > 0;
  return {
    code,
    name: raw.name != null && String(raw.name).trim() ? String(raw.name).trim() : null,
    shares: Math.round(shares * 10000) / 10000,
    available_shares: toFloat(raw.available_shares),
    cost: cost == null ? null : Math.round(cost * 10000) / 10000,
    price: toFloat(raw.price),
    pnl: toFloat(raw.pnl),
    market_value: toFloat(raw.market_value),
    include,
  };
}

function normalizeDraft(raw: Record<string, unknown>): ScreenshotDraft {
  const holdingsIn = Array.isArray(raw.holdings) ? raw.holdings : [];
  const holdings: ScreenshotHoldingRow[] = [];
  const seen = new Set<string>();
  for (const row of holdingsIn) {
    if (!row || typeof row !== "object") continue;
    try {
      const h = normalizeHoldingRow(row as Record<string, unknown>);
      if (seen.has(h.code)) continue;
      seen.add(h.code);
      holdings.push(h);
    } catch {
      // 跳过无法规范化的行
    }
  }
  const equity = toFloat(raw.equity);
  const cash = toFloat(raw.cash_balance);
  const withdrawable = toFloat(raw.withdrawable);
  const asText = (k: string): string | null => {
    const v = raw[k];
    if (v == null || v === "") return null;
    const s = String(v).trim();
    return s || null;
  };
  return {
    broker: asText("broker"),
    account_name: asText("account_name"),
    account_display: asText("account_display"),
    equity: equity == null ? null : Math.round(equity * 100) / 100,
    cash_balance: cash ?? withdrawable,
    available: toFloat(raw.available),
    withdrawable: withdrawable ?? cash,
    frozen: toFloat(raw.frozen),
    stock_market_value: toFloat(raw.stock_market_value),
    position_pnl: toFloat(raw.position_pnl),
    daily_pnl: toFloat(raw.daily_pnl),
    daily_pnl_pct: toFloat(raw.daily_pnl_pct),
    note: asText("note"),
    holdings,
  };
}

function parseImportJson(text: string): { kind: "draft"; draft: ScreenshotDraft } | { kind: "row"; row: ScreenshotHoldingRow } {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error("JSON 解析失败，请检查语法");
  }
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("须为 JSON 对象：整体 ScreenshotDraft，或单条 ScreenshotHoldingRow");
  }
  const obj = raw as Record<string, unknown>;
  if ("holdings" in obj) {
    return { kind: "draft", draft: normalizeDraft(obj) };
  }
  if ("code" in obj) {
    return { kind: "row", row: normalizeHoldingRow(obj) };
  }
  throw new Error("无法识别：整体导入需含 holdings；单条导入需含 code");
}

export function PortfolioJsonImport({
  open,
  onClose,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  onApplied: () => void | Promise<void>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [mode, setMode] = useState<"idle" | "draft" | "row">("idle");
  const [draft, setDraft] = useState<ScreenshotDraft | null>(null);
  const [row, setRow] = useState<ScreenshotHoldingRow | null>(null);
  const [rowExists, setRowExists] = useState(false);
  const [account, setAccount] = useState<Record<AccountFieldKey, string>>({ ...EMPTY_ACCOUNT });
  const [note, setNote] = useState("");
  const [rows, setRows] = useState<ScreenshotHoldingRow[]>([]);
  const [replace, setReplace] = useState(true);

  function reset() {
    setErr("");
    setJsonText("");
    setMode("idle");
    setDraft(null);
    setRow(null);
    setRowExists(false);
    setRows([]);
    setNote("");
    setReplace(true);
    setAccount({ ...EMPTY_ACCOUNT });
    if (fileRef.current) fileRef.current.value = "";
  }

  function close() {
    if (busy) return;
    reset();
    onClose();
  }

  function applyDraft(d: ScreenshotDraft) {
    setDraft(d);
    setMode("draft");
    const cash = d.cash_balance ?? d.withdrawable;
    setAccount({
      account_name: d.account_name || "",
      account_display: d.account_display || "",
      equity: numStr(d.equity),
      cash_balance: numStr(cash),
      available: numStr(d.available),
      withdrawable: numStr(d.withdrawable ?? cash),
      frozen: numStr(d.frozen),
      stock_market_value: numStr(d.stock_market_value),
      position_pnl: numStr(d.position_pnl),
      daily_pnl: numStr(d.daily_pnl),
      daily_pnl_pct: numStr(d.daily_pnl_pct),
    });
    setNote(d.note || "");
    setRows((d.holdings || []).map((h) => ({ ...h })));
  }

  async function applyParsed(text: string) {
    setErr("");
    const parsed = parseImportJson(text);
    if (parsed.kind === "draft") {
      applyDraft(parsed.draft);
      return;
    }
    setMode("row");
    setRow(parsed.row);
    setDraft(null);
    try {
      const p = await api.portfolio();
      setRowExists((p.holdings || []).some((h) => h.code === parsed.row.code));
    } catch {
      setRowExists(false);
    }
  }

  async function onParseClick() {
    if (!jsonText.trim()) {
      setErr("请粘贴 JSON，或上传 .json 文件");
      return;
    }
    setBusy(true);
    try {
      await applyParsed(jsonText);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "解析失败");
      setMode("idle");
      setDraft(null);
      setRow(null);
    } finally {
      setBusy(false);
    }
  }

  async function onPickFile(file: File | null) {
    if (!file) return;
    setErr("");
    if (!file.name.toLowerCase().endsWith(".json") && file.type && !file.type.includes("json") && !file.type.startsWith("text/")) {
      setErr("请上传 .json 文件");
      return;
    }
    setBusy(true);
    try {
      const text = await file.text();
      setJsonText(text);
      await applyParsed(text);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "读取失败");
      setMode("idle");
    } finally {
      setBusy(false);
    }
  }

  function patchRow(i: number, patch: Partial<ScreenshotHoldingRow>) {
    setRows((prev) => prev.map((r, idx) => {
      if (idx !== i) return r;
      const next = { ...r, ...patch };
      const shares = Number(next.shares);
      const cost = Number(next.cost);
      if (patch.include === undefined && shares > 0 && cost > 0 && next.include === false) {
        next.include = true;
      }
      return next;
    }));
  }

  async function confirmDraftWrite() {
    if (!draft) return;
    const equity = parseNum(account.equity);
    const holdings = rows
      .filter((r) => r.include !== false)
      .map((r) => ({
        code: String(r.code || "").trim(),
        shares: Number(r.shares),
        cost: Number(r.cost),
        include: true as const,
      }));
    for (const h of holdings) {
      if (!/^\d{6}$/.test(h.code) || !(h.shares > 0) || !(h.cost > 0)) {
        setErr(`持仓 ${h.code || "?"}：代码须 6 位，股数与成本须 > 0（或不勾选写入）`);
        return;
      }
    }
    setBusy(true);
    setErr("");
    try {
      const account_fields = collectFields(draft, account);
      await api.applyTradeScreenshot({
        equity,
        note: buildNote(draft, account, note),
        account_fields,
        holdings,
        replace,
      });
      reset();
      onClose();
      await onApplied();
    } catch (e) {
      setErr(e instanceof ApiError || e instanceof Error ? e.message : "写入失败");
    } finally {
      setBusy(false);
    }
  }

  async function confirmRowWrite() {
    if (!row) return;
    const code = String(row.code || "").trim();
    const shares = Number(row.shares);
    const cost = Number(row.cost);
    if (!/^\d{6}$/.test(code) || !(shares > 0) || !(cost > 0)) {
      setErr("代码须 6 位，股数与成本须 > 0");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await api.setHolding(code, shares, cost);
      reset();
      onClose();
      await onApplied();
    } catch (e) {
      setErr(e instanceof ApiError || e instanceof Error ? e.message : "写入失败");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  const previewNote = draft ? buildNote(draft, account, note) : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onClick={close}>
      <div
        className={cn("glass w-full p-5", mode === "draft" ? "max-w-5xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {mode === "draft" ? "确认整体导入" : mode === "row" ? "确认单条持仓" : "导入 JSON"}
          </h2>
          <button
            type="button"
            disabled={busy}
            onClick={close}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {err && (
          <div className="mb-3 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {err}
          </div>
        )}

        {mode === "idle" && (
          <>
            <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
              粘贴或上传 JSON。含 <code className="rounded bg-muted px-1">holdings</code> 的对象按整体
              ScreenshotDraft 导入；仅含 <code className="rounded bg-muted px-1">code</code> 的对象按单条
              ScreenshotHoldingRow 写入（同代码覆盖，否则新增）。
            </p>
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              placeholder={`整体示例：\n${EXAMPLE_DRAFT}\n\n单条示例：\n${EXAMPLE_ROW}`}
              rows={12}
              className="mb-3 w-full rounded-xl border border-border bg-card px-3 py-2 font-mono text-[11px] leading-relaxed outline-none focus:border-primary/50"
            />
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json,text/json"
              className="hidden"
              onChange={(e) => void onPickFile(e.target.files?.[0] || null)}
            />
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                上传文件
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onParseClick()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {busy ? "解析中…" : "解析预览"}
              </button>
            </div>
          </>
        )}

        {mode === "row" && row && (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              将按代码 <span className="font-mono text-foreground">{row.code}</span>
              {rowExists ? " 覆盖更新" : " 新增"}本地持仓（股数与成本直接写入，不加权合并）。
            </p>
            <div className="mb-4 overflow-x-auto rounded-lg border border-border/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/60 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">代码</th>
                    <th className="px-3 py-2">名称</th>
                    <th className="px-3 py-2">股数</th>
                    <th className="px-3 py-2">成本</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-t border-border/40">
                    <td className="px-3 py-2 font-mono">{row.code}</td>
                    <td className="px-3 py-2">{row.name || "—"}</td>
                    <td className="px-3 py-2 tabular-nums">{row.shares}</td>
                    <td className="px-3 py-2 tabular-nums">{row.cost ?? "—"}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => { setMode("idle"); setRow(null); setErr(""); }}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                返回编辑
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmRowWrite()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {busy ? "写入中…" : rowExists ? "确认更新" : "确认新增"}
              </button>
            </div>
          </>
        )}

        {mode === "draft" && draft && (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              栏位固定；请核对数字后再写入。勾选的持仓会
              {replace ? "整表覆盖" : "合并加入"}本地持仓；总权益与命名账户栏位写入日快照（同日可覆盖）。
              {draft.broker ? ` 来源：${draft.broker}` : ""}
            </p>

            <div className="mb-4 overflow-x-auto rounded-lg border border-border/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/60 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">账户字段</th>
                    <th className="px-3 py-2 font-medium">值（可改）</th>
                  </tr>
                </thead>
                <tbody>
                  {ACCOUNT_FIELDS.map((f) => (
                    <tr key={f.key} className="border-t border-border/40">
                      <td className="px-3 py-1.5 text-muted-foreground">{f.label}</td>
                      <td className="px-3 py-1.5">
                        <input
                          value={account[f.key]}
                          onChange={(e) => setAccount((a) => ({ ...a, [f.key]: e.target.value }))}
                          className="w-full rounded border border-border bg-card px-2 py-1 tabular-nums outline-none focus:border-primary/50"
                        />
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-border/40">
                    <td className="px-3 py-1.5 text-muted-foreground">备注</td>
                    <td className="px-3 py-1.5">
                      <input
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="可选；空则用下方自动摘要"
                        className="w-full rounded border border-border bg-card px-2 py-1 outline-none focus:border-primary/50"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {previewNote && (
              <p className="mb-3 rounded-lg border border-border/50 bg-muted/30 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                格式化写入：{previewNote}
              </p>
            )}

            <div className="mb-3 max-h-[40vh] overflow-auto rounded-lg border border-border/60">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 z-10 bg-muted/80 text-muted-foreground backdrop-blur">
                  <tr>
                    <th className="px-2 py-2">写入</th>
                    <th className="px-2 py-2">代码</th>
                    <th className="px-2 py-2">名称</th>
                    <th className="px-2 py-2">股数</th>
                    <th className="px-2 py-2">可用</th>
                    <th className="px-2 py-2">成本</th>
                    <th className="px-2 py-2">现价</th>
                    <th className="px-2 py-2">盈亏</th>
                    <th className="px-2 py-2">市值</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={`${r.code}-${i}`} className="border-t border-border/40">
                      <td className="px-2 py-1">
                        <input
                          type="checkbox"
                          checked={r.include !== false}
                          onChange={(e) => patchRow(i, { include: e.target.checked })}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={r.code}
                          onChange={(e) => patchRow(i, { code: e.target.value })}
                          className="w-[4.5rem] rounded border border-border bg-card px-1 py-0.5 font-mono"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={r.name || ""}
                          onChange={(e) => patchRow(i, { name: e.target.value || null })}
                          className="w-24 rounded border border-border bg-card px-1 py-0.5"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={numStr(r.shares)}
                          onChange={(e) => patchRow(i, { shares: parseNum(e.target.value) ?? 0 })}
                          className="w-16 rounded border border-border bg-card px-1 py-0.5 tabular-nums"
                        />
                      </td>
                      <td className="px-2 py-1 tabular-nums text-muted-foreground">
                        {r.available_shares ?? "—"}
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={numStr(r.cost)}
                          onChange={(e) => patchRow(i, { cost: parseNum(e.target.value) })}
                          className="w-20 rounded border border-border bg-card px-1 py-0.5 tabular-nums"
                        />
                      </td>
                      <td className="px-2 py-1 tabular-nums text-muted-foreground">{r.price ?? "—"}</td>
                      <td className="px-2 py-1 tabular-nums text-muted-foreground">{r.pnl ?? "—"}</td>
                      <td className="px-2 py-1 tabular-nums text-muted-foreground">{r.market_value ?? "—"}</td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                        无持仓行
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <label className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              覆盖现有本地持仓（取消则按代码合并加仓）
            </label>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => { setMode("idle"); setDraft(null); setRows([]); setErr(""); }}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                返回编辑
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmDraftWrite()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {busy ? "写入中…" : "确认写入"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
