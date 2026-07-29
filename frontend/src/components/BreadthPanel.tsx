import { Gauge, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";
import { countColor, pctColor } from "@/lib/colors";
import { finite, plain } from "@/lib/agent";
import { Caliber } from "@/components/ui/Caliber";
import type { Breadth } from "@/lib/agent";

export function BreadthPanel({ b, limitDown }: { b?: Breadth; limitDown?: number | null }) {
  if (!b) return null;

  if (!b.available) {
    return (
      <section className="glass rounded-2xl border-l-4 border-l-muted p-4">
        <div className="flex items-center gap-1.5 text-sm font-bold">
          <Gauge className="h-4 w-4 text-muted-foreground" /> 今天好不好做
        </div>
        {}
        {}
        <p className="mt-1 text-[13px] text-muted-foreground">暂不可用：{plain(b.reason || "未知")}</p>
      </section>
    );
  }

  const upN = finite(b.up), downN = finite(b.down), flatN = finite(b.flat);
  const countsOk = upN != null && downN != null && flatN != null;
  const up = upN ?? 0, down = downN ?? 0, flat = flatN ?? 0;
  const tot = countsOk ? up + down + flat : 0;
  const upRatio = countsOk && tot ? up / tot : null;
  const dist = b.dist_available;
  const down5 = finite(b.deep_down_5);
  const up5 = finite(b.deep_up_5_incl) ?? finite(b.deep_up_5);

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
        <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">今天好不好做 · Breadth</span>
        <span className="text-[11px] text-muted-foreground">
          下面所有涨停池的数字，都要拿这一行当分母来读
        </span>
        <Caliber text={
          `涨/跌/平家数取自沪深两市指数的成分统计（${b.up_down_scope}），一次请求。\n` +
          `涨幅≥5% / 跌超5% 取自${b.dist_scope}共 ${b.universe} 只按涨跌幅排序后的边界定位。\n` +
          "⚠️ **不给「全市场涨跌中位数」**：数据源把无数据的票排在列表中间（实测中位数附近\n" +
          "每页 100 行只有 24-35 行有数值），按行号算的排名会把没交易的票数进去，\n" +
          "中位数会稳稳落进那堆 0.00% 里 —— 看着合理其实是假的。两头的边界不受影响。\n" +
          "成交额 = 沪深两市合计。\n" +
          "🔴 拉的是**实时（延时）行情**，所以只有「最近一个已收盘交易日 + 当前已收盘」时才算数；\n" +
          "盘中跑会如实标不可用，绝不拿盘中价冒充收盘。"
        } />
      </div>

      <div className="glass rounded-2xl p-5">
        {!countsOk && (
          <p className="mb-2 rounded-lg bg-muted/50 px-2.5 py-1.5 text-[12px] text-muted-foreground">
            ⚠️ 涨跌家数没取全，宽度条与上涨占比本次不给 —— <b>缺的项不是 0</b>
          </p>
        )}
        {/* 一条涨跌宽度带：比三个数字直观得多 */}
        {countsOk && <div className="flex h-7 overflow-hidden rounded-lg text-[11px] font-bold text-white">
          {[
            { n: up, cls: "bg-danger", label: `${up} 涨` },
            { n: flat, cls: "bg-muted-foreground/40", label: flat ? `${flat} 平` : "" },
            { n: down, cls: "bg-success", label: `${down} 跌` },
          ].map((seg, i) => (
            <div key={i} className={cn("flex items-center justify-center", seg.cls)}
              style={{ width: `${tot ? (seg.n / tot) * 100 : 0}%` }}>
              {seg.label && (seg.n / (tot || 1)) > 0.08 ? seg.label : ""}
            </div>
          ))}
        </div>}
        <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13px]">
          <span>
            上涨占比{" "}
            <b className={cn("text-base tabular-nums", upRatio == null ? "" : pctColor(upRatio - 0.5))}>
              {upRatio == null ? "—" : `${Math.round(upRatio * 100)}%`}
            </b>
          </span>
          <span className="text-muted-foreground">
            <span className={countColor("up")}>{upN ?? "—"}</span> 涨 /{" "}
            <span className={countColor("down")}>{downN ?? "—"}</span> 跌 / {flatN ?? "—"} 平
            <span className="ml-1 text-[11px] text-muted-foreground/60">（{b.up_down_scope}）</span>
          </span>
          {}
          {finite(limitDown) != null && (
            <span className="text-muted-foreground">
              跌停 <b className={countColor("down")}>{finite(limitDown)}</b> 家
            </span>
          )}
        </div>

        <div className="mt-3 grid gap-4 border-t border-dashed border-border pt-3 sm:grid-cols-3">
          <div>
            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Wallet className="h-3 w-3" /> 两市成交额
            </div>
            <div className="text-xl font-extrabold tabular-nums">
              {finite(b.amount_yi) == null ? "—" : `${Math.round(b.amount_yi!).toLocaleString()} 亿`}
            </div>
          </div>
          {}
          <div>
            <div className="text-[11px] text-muted-foreground">跌超 5%</div>
            <div className={cn("text-xl font-extrabold tabular-nums", down5 != null ? countColor("down") : "text-muted-foreground/40")}>
              {down5 != null ? `${down5} 家` : "—"}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">涨幅 ≥5%</div>
            <div className={cn("text-xl font-extrabold tabular-nums", up5 != null ? countColor("up") : "text-muted-foreground/40")}>
              {up5 != null ? `${up5} 家` : "—"}
            </div>
          </div>
        </div>
        {dist ? (
          <p className="mt-2 text-[11px] text-muted-foreground">
            对照 {b.dist_scope} 共 {b.universe} 只
            {b.dist_partial && (
              <span className="ml-1 text-muted-foreground/70">
                ⚠️ 有项目本次取数失败，<b>未取到 ≠ 为 0</b>
              </span>
            )}
          </p>
        ) : (
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            ⚠️ 涨跌分布取数失败，本次不给 —— <b>别据此认为分布正常</b>
          </p>
        )}
      </div>
    </section>
  );
}
