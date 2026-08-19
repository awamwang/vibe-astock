import { Shield } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Caliber } from "@/components/ui/Caliber";
import type { TradeBudget } from "@/lib/api";

function pct(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

/** 复盘看板硬指标区：仓位预算卡（与 AI 五档并列展示，但不进 prompt） */
export function TradeBudgetCard({ b, date }: { b?: TradeBudget | null; date?: string }) {
  if (!b) {
    return (
      <div className="glass rounded-2xl p-5">
        <div className="mb-1 flex items-center gap-1.5">
          <Shield className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-bold">仓位预算</h3>
        </div>
        <p className="text-[13px] text-muted-foreground">
          尚未计算。跑完复盘会自动写入，也可在
          <Link to="/trade" className="mx-1 text-primary underline-offset-2 hover:underline">持仓与预算</Link>
          页手动刷新。
        </p>
      </div>
    );
  }

  const phase = b.override_phase || b.phase;
  const rule = b.rule_phase;

  return (
    <div className="glass rounded-2xl p-5">
      <div className="mb-1 flex items-center gap-1.5">
        <Shield className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold">仓位预算</h3>
        <Caliber text={"硬规则六档驱动总仓/单票上限，与上方 AI「情绪档位」不是同一套词典。\n" +
          "缺关键读数（赚钱效应/晋级/炸板）整日不可用，不给假上限。\n" +
          "修复确认不会自动升档，只给代理提示；需要时在「持仓与预算」手拨。"} />
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground/70">
        情绪定「最多几成仓」；不算买卖点。
        {date && (
          <Link to={`/trade?date=${date}`} className="ml-2 text-primary underline-offset-2 hover:underline">
            打开持仓对照 →
          </Link>
        )}
      </p>

      {!b.available ? (
        <p className="text-[13px] text-warning">
          今日预算不可用{b.reason ? `：${b.reason}` : ""}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <div className="text-2xl font-extrabold tabular-nums text-foreground">{phase}</div>
              <div className="text-[11px] text-muted-foreground">
                生效档
                {b.override_phase && rule && (
                  <span className="ml-1 text-warning">（手拨；规则档 {rule}）</span>
                )}
                {!b.override_phase && b.demoted && (
                  <span className="ml-1 text-warning">（宽度背离已降档）</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-2xl font-extrabold tabular-nums">{pct(b.cap_total)}</div>
              <div className="text-[11px] text-muted-foreground">总仓上限</div>
            </div>
            <div>
              <div className="text-2xl font-extrabold tabular-nums">{pct(b.cap_single)}</div>
              <div className="text-[11px] text-muted-foreground">单票上限</div>
            </div>
          </div>

          <div className="mt-3 grid gap-2 border-t border-dashed border-border pt-2 text-[12px] md:grid-cols-2">
            <div>
              <span className="text-muted-foreground">允许：</span>
              {(b.allow || []).join("、") || "—"}
            </div>
            <div>
              <span className="text-muted-foreground">禁止：</span>
              <span className="text-danger">{(b.forbid || []).join("、") || "—"}</span>
            </div>
          </div>

          {b.repair_proxy && (
            <div className={cn(
              "mt-2 rounded-lg px-2.5 py-1.5 text-[11px]",
              b.repair_proxy.met ? "bg-primary/10 text-primary" : "bg-muted/40 text-muted-foreground",
            )}>
              修复代理{b.repair_proxy.met ? "已满足" : "未满足"}
              （不自动升档
              {b.prev_rule_phase === "冰点观察" || b.rule_phase === "冰点观察"
                ? "；若确认拐点可手拨「修复确认」"
                : ""}
              ）
            </div>
          )}

          {(b.block_new_long_reasons || []).length > 0 && (
            <ul className="mt-2 list-inside list-disc text-[11px] text-danger">
              {b.block_new_long_reasons!.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
