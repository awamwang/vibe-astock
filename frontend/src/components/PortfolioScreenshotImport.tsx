import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Upload, X } from "lucide-react";
import { ApiError, api, type ScreenshotDraft, type ScreenshotHoldingRow, type TradeAccountFields } from "@/lib/api";
import { hasLlm, loadLlm } from "@/lib/llm";
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

/** 命名格式化摘要（与后端 format_account_summary 对齐） */
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

export function PortfolioScreenshotImport({
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
  const [draft, setDraft] = useState<ScreenshotDraft | null>(null);
  const [account, setAccount] = useState<Record<AccountFieldKey, string>>({ ...EMPTY_ACCOUNT });
  const [note, setNote] = useState("");
  const [rows, setRows] = useState<ScreenshotHoldingRow[]>([]);
  const [replace, setReplace] = useState(true);

  function reset() {
    setErr("");
    setDraft(null);
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

  async function onPickFile(file: File | null) {
    if (!file) return;
    setErr("");
    if (!hasLlm()) {
      setErr("尚未接入 AI，请先在「接入 AI」配置支持识图的 API 模型");
      return;
    }
    const llm = loadLlm();
    if (!llm) {
      setErr("尚未接入 AI，请先在「接入 AI」配置支持识图的 API 模型");
      return;
    }
    if (llm.provider.startsWith("cli-")) {
      setErr("截图解析需要支持识图的 API 模型，当前为 CLI 订阅，请改用 API 接入");
      return;
    }
    if (!file.type.startsWith("image/")) {
      setErr("请上传图片文件（png / jpg / webp 等）");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setErr("图片请小于 8MB");
      return;
    }
    setBusy(true);
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("读取图片失败"));
        reader.readAsDataURL(file);
      });
      const r = await api.parseTradeScreenshot(dataUrl, llm);
      applyDraft(r.draft);
    } catch (e) {
      setErr(e instanceof ApiError || e instanceof Error ? e.message : "解析失败");
      setDraft(null);
    } finally {
      setBusy(false);
    }
  }

  const onPickFileRef = useRef(onPickFile);
  onPickFileRef.current = onPickFile;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const takeClipboardImage = useCallback((e: ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return null;
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.type.startsWith("image/")) {
        return it.getAsFile();
      }
    }
    return null;
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPaste = (e: ClipboardEvent) => {
      if (busyRef.current) return;
      const file = takeClipboardImage(e);
      if (!file) return;
      e.preventDefault();
      void onPickFileRef.current(file);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [open, takeClipboardImage]);

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

  async function confirmWrite() {
    if (!draft) return;
    const equity = parseNum(account.equity);
    if (equity == null) {
      setErr("请填写总权益（总资产）后再写入");
      return;
    }
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
      setErr(e instanceof Error ? e.message : "写入失败");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  const previewNote = draft ? buildNote(draft, account, note) : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onClick={close}>
      <div
        className={cn("glass w-full p-5", draft ? "max-w-5xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {draft ? "确认截图解析结果" : "上传持仓截图"}
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

        {!draft ? (
          <>
            <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
              上传券商持仓页截图，或直接 <kbd className="rounded border border-border bg-muted px-1">Ctrl+V</kbd> /
              <kbd className="mx-0.5 rounded border border-border bg-muted px-1">⌘V</kbd>
              粘贴剪贴板截图。用「接入 AI」里的识图模型解析后，先对照修改再写入。
            </p>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void onPickFile(e.target.files?.[0] || null)}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="inline-flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-10 text-sm text-primary hover:bg-primary/10 disabled:opacity-60"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              <span>{busy ? "AI 解析中…" : "选择图片，或直接粘贴截图"}</span>
            </button>
          </>
        ) : (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              栏位固定；请核对数字后再写入。勾选的持仓会
              {replace ? "整表覆盖" : "合并加入"}本地持仓；总权益与命名账户栏位写入日快照（同日可覆盖）。
              {draft.broker ? ` 识别来源：${draft.broker}` : ""}
              {" "}也可再粘贴截图重新解析。
            </p>

            <div className="mb-4 overflow-x-auto rounded-lg border border-border/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/60 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">账户字段</th>
                    <th className="px-3 py-2 font-medium">解析值（可改）</th>
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
                        未解析到持仓行
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
                onClick={() => { setDraft(null); setRows([]); setErr(""); }}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                重新选图
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmWrite()}
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
