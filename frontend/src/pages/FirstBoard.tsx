import { Fragment, useEffect, useState } from "react";
import { Flame, Loader2, Sparkles, AlertCircle, X, Upload } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useDeepDive, DeepDivePanel, RunAllButton, parseDiveMeta, type DiveItem } from "@/components/ui/DeepDive";
import { api, type FirstBoardData, type FirstBoardStock, type ZtReasonPreview } from "@/lib/api";
import { DEFAULT_ZT_KEYWORDS, setZtKeywordsCache } from "@/lib/zt-keywords";
import { StockLabel } from "@/components/stock/StockLabel";

const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`); // 元 → 亿

const dateLabel = (d: string) =>
  d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d;

export function FirstBoard() {
  const [data, setData] = useState<FirstBoardData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState<ZtReasonPreview | null>(null);
  const [ztKeywords, setZtKeywords] = useState<string[]>([...DEFAULT_ZT_KEYWORDS]);
  const dd = useDeepDive("firstboard", data?.date || "");

  const reload = () =>
    api.firstBoard().then(setData).catch(() => {}).finally(() => setLoaded(true));

  useEffect(() => {
    reload();
  }, []);

  useEffect(() => {
    api.ztKeywords()
      .then((cfg) => {
        const kw = setZtKeywordsCache(cfg.keywords || []);
        setZtKeywords(kw);
      })
      .catch(() => {});
  }, []);

  const closeImport = () => {
    if (importing) return;
    setImportOpen(false);
    setPreview(null);
  };

  const submitParse = async () => {
    if (!importText.trim()) {
      toast.error("请粘贴同花顺导出的文本");
      return;
    }
    setImporting(true);
    try {
      const r = await api.parseZtReasons(importText);
      setPreview(r);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "解析失败");
    } finally {
      setImporting(false);
    }
  };

  const submitImport = async () => {
    if (!importText.trim()) {
      toast.error("请粘贴同花顺导出的文本");
      return;
    }
    setImporting(true);
    try {
      const r = await api.importZtReasons(importText);
      toast.success(`已导入 ${r.imported} 只涨停原因（${r.date}）`);
      setImportOpen(false);
      setImportText("");
      setPreview(null);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const buildPrompt = (s: FirstBoardStock) => {
    const tagList = ztKeywords.join("、");
    return (
      `今天（${dateLabel(data?.date || "")}）A 股首板涨停股「${s.name}（${s.code}）」的客观数据：\n` +
      `现价 ${s.price} 元，涨停 +${s.pct}%，首次封板时间 ${s.seal_time || "未知"}，` +
      `炸板 ${s.break_count} 次，成交额 ${yi(s.amount)}，流通市值 ${yi(s.float_cap)}，` +
      `所属行业 ${s.industry || "未知"}，涨停原因题材：${s.reason || "（暂缺，需要自查）"}。\n\n` +
      "请深入分析这只股票今天涨停的原因。输出必须先三行固定摘要，再写正文：\n" +
      "【涨停关键字】xxx\n" +
      "【持续性】xxx\n" +
      "【题材新旧】xxx\n" +
      `涨停关键字：必须从下列标签中**精确选一个并原样抄写**（不要自造、不要组合）：${tagList}。` +
      "看不出明显原因选「无原因」；都不属于选「其他」。\n" +
      "持续性：仅就该原因/题材本身的发酵时长作极简判断（不超过 10 个汉字），例如日内、短期、到利好出尽——" +
      "不要据此推断个股涨跌。\n" +
      "题材新旧：必须从「新题材、旧题材、不明」中**精确选一个并原样抄写**。" +
      "依据是该涨停对应题材近期在市场里有没有被炒作过：近几周未见明显炒作选「新题材」；" +
      "明显被炒过/回流再起选「旧题材」；证据不足选「不明」——只判题材层面，不推断个股。\n" +
      "正文要求：\n" +
      "1. 先调用工具查询这只股票的近期新闻与研报，结合上面的题材串，说清今天涨停最可能的驱动因素（消息面 / 题材面 / 资金面）；\n" +
      "2. 就**这个题材板块整体**说清它的强度与所处阶段（情绪性的一日游 / 有产业逻辑或业绩支撑），" +
      "并给出依据 —— 只讲题材板块层面，不要由此推断这只个股接下来会怎样；\n" +
      "3. 单独说明：该题材近期在市场中有没有被炒作过（有无相似高潮、回流再起、还是相对新鲜），" +
      "并与上方「题材新旧」标签对应，给出简要依据；\n" +
      "4. 客观列出值得注意的点（炸板情况、封板时间早晚、流通盘大小、题材扩散位置）。\n" +
      "个股层面只陈述已经发生的客观数据与事实，方向与强弱判断做到题材板块层面为止：" +
      "不预测个股涨跌、不给个股参与倾向、不推荐任何标的、不构成投资建议。" +
      "输出用纯 Markdown（不要在表格或正文里使用 <br> 等 HTML 标签）。"
    );
  };

  const ctx = (s: FirstBoardStock) => `首板股 ${s.name}(${s.code}) 涨停原因深入分析`;
  const diveItem = (s: FirstBoardStock): DiveItem => ({ key: s.code, prompt: buildPrompt(s), context: ctx(s) });

  const stocks = data?.stocks ?? [];
  const nameByCode = Object.fromEntries(stocks.map((s) => [s.code, s.name]));

  return (
    <div>
      <PageHeader
        title="首板分析"
        subtitle="今日首板涨停股（连板数=1）· 涨停原因题材 · 每只可让 AI 深入分析"
        actions={
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
          >
            <Upload className="h-3.5 w-3.5" /> 导入涨停原因
          </button>
        }
      />

      {data && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          {[
            { label: "交易日", value: dateLabel(data.date) },
            { label: "今日涨停", value: `${data.total_zt} 家` },
            { label: "其中首板", value: `${data.first_count} 家` },
          ].map((c) => (
            <GlassCard key={c.label} className="py-3 text-center">
              <div className="text-xs text-muted-foreground">{c.label}</div>
              <div className="mt-1 font-mono text-lg font-bold text-primary">{c.value}</div>
            </GlassCard>
          ))}
        </div>
      )}

      {data?.reason_note && (
        <p className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
          <AlertCircle className="h-3.5 w-3.5" /> 涨停原因：{data.reason_note}
        </p>
      )}

      <GlassCard>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold">
          <Flame className="h-4 w-4 text-primary" /> 首板名单
          <Caliber text={
            "「炸板」是当天开板过几次，0 就是全天没开过板 —— 这张表里的票**最终都封住了涨停**，\n" +
            "所以炸板次数说的是过程有多难看，不是最后有没有封住。\n" +
            "名单按首次封板时间从早到晚排。\n" +
            "「行业」经常只有四个字（像「互联网电」「自动化设」）——是上游把名字截到四字，\n" +
            "不是这里显示不全；怕猜错所以不替它补全称。"
          } />
          <span className="text-xs font-normal text-muted-foreground">
            按首次封板时间排序（早封在前）· 客观公开榜单，非推荐 / 非预测
          </span>
          <span className="ml-auto font-normal">
            <RunAllButton dd={dd} items={stocks.map(diveItem)} nameOf={(k) => nameByCode[k] || k} />
          </span>
        </div>
        {!loaded ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : stocks.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">暂无数据（数据源异常或非交易日）</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "首封", "炸板", "现价", "流通市值", "涨停原因", "关键字", "题材新旧", "持续性", "行业", ""].map((h) => (
                    <th key={h || "action"} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stocks.map((s) => {
                  const diveMeta = parseDiveMeta(dd.analysis[s.code] || "", ztKeywords);
                  return (
                  <Fragment key={s.code}>
                    <tr className="border-b border-border/30">
                      <td className="whitespace-nowrap px-2 py-2">
                        <StockLabel code={s.code} name={s.name} />
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{s.seal_time || "—"}</td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono">
                        {s.break_count > 0 ? <span className="text-primary">{s.break_count} 次</span> : <span className="text-muted-foreground/50">0</span>}
                      </td>
                      <td className="px-2 py-2 font-mono">{s.price}</td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
                      <td className="max-w-56 px-2 py-2 text-xs">
                        {s.reason ? <span className="text-foreground">{s.reason}</span> : <span className="text-muted-foreground/50">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs">
                        {diveMeta.keyword
                          ? <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 font-medium text-primary">{diveMeta.keyword}</span>
                          : <span className="text-muted-foreground/50">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs">
                        {diveMeta.themeFreshness ? (
                          <span className={`rounded border px-1.5 py-0.5 font-medium ${
                            diveMeta.themeFreshness === "新题材"
                              ? "border-success/30 bg-success/10 text-success"
                              : diveMeta.themeFreshness === "旧题材"
                                ? "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                                : "border-border/50 bg-muted/30 text-muted-foreground"
                          }`}>{diveMeta.themeFreshness}</span>
                        ) : (
                          <span className="text-muted-foreground/50">—</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs">
                        {diveMeta.duration
                          ? <span className="rounded border border-border/50 bg-muted/30 px-1.5 py-0.5 font-medium text-foreground">{diveMeta.duration}</span>
                          : <span className="text-muted-foreground/50">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                      <td className="whitespace-nowrap px-2 py-2 text-right">
                        <button
                          onClick={() => dd.toggle(diveItem(s))}
                          className="inline-flex items-center gap-1 rounded-lg border border-primary/50 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
                        >
                          {dd.running === s.code ? <Loader2 className="h-3 w-3 animate-spin" /> : dd.open === s.code ? <X className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
                          {dd.open === s.code ? "收起" : dd.analysis[s.code] ? "展开" : "深入分析"}
                        </button>
                      </td>
                    </tr>
                    {dd.open === s.code && (
                      <DeepDivePanel
                        dd={dd}
                        stockKey={s.code}
                        colSpan={11}
                        noteTitle={`首板深析 · ${s.name}`}
                        onRerun={() => dd.rerun(diveItem(s))}
                      />
                    )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      <Disclaimer />

      {importOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
          onClick={closeImport}
        >
          <div
            className={`glass w-full p-5 ${preview ? "max-w-4xl" : "max-w-2xl"}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold">
                {preview ? "确认涨停原因" : "导入涨停原因"}
              </h2>
              <button
                type="button"
                disabled={importing}
                onClick={closeImport}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {!preview ? (
              <>
                <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                  粘贴同花顺涨停池导出的 txt（含表头）。没有涨停原因的行会自动跳过；
                  点确定后先预览解析结果，再确认写入。
                </p>
                <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder="粘贴同花顺导出的全部文本…"
                  className="h-64 w-full resize-y rounded-lg border border-border bg-background/60 px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-primary/60"
                  spellCheck={false}
                />
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    type="button"
                    disabled={importing}
                    onClick={closeImport}
                    className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    disabled={importing}
                    onClick={() => void submitParse()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
                  >
                    {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                    {importing ? "解析中…" : "确定"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="mb-3 text-xs text-muted-foreground">
                  {preview.date} 解析到 <b className="text-foreground">{preview.count}</b> 只涨停原因
                  {preview.skipped > 0 ? `，已忽略 ${preview.skipped} 行（无涨停原因）` : ""}。
                  左栏股票，右栏题材串。确认无误后再写入。
                </p>
                <div className="max-h-[55vh] overflow-auto rounded-lg border border-border/60">
                  <div className="grid grid-cols-2 sticky top-0 z-10 border-b border-border bg-muted/80 px-3 py-2 text-xs font-medium text-muted-foreground backdrop-blur">
                    <div>股票</div>
                    <div>涨停原因</div>
                  </div>
                  {preview.rows.map((r) => (
                    <div key={r.code} className="grid grid-cols-2 gap-2 border-b border-border/40 px-3 py-1.5 text-xs last:border-b-0">
                      <div className="min-w-0">
                        <StockLabel code={r.code} name={r.name} />
                      </div>
                      <div className="min-w-0 leading-relaxed text-foreground">{r.reason}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    type="button"
                    disabled={importing}
                    onClick={() => setPreview(null)}
                    className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                  >
                    返回修改
                  </button>
                  <button
                    type="button"
                    disabled={importing}
                    onClick={() => void submitImport()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
                  >
                    {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                    {importing ? "写入中…" : "确认导入"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
