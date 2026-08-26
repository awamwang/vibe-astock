import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";

export const IMPACT_LABEL: Record<string, string> = {
  critical: "重大",
  high: "高",
  medium: "中",
  low: "低",
  noise: "噪声",
};

export const FRESHNESS_LABEL: Record<string, string> = {
  new: "全新",
  follow_up: "续报",
  duplicate: "重复",
  rumor: "传闻",
};

export const EFFECT_LABEL: Record<string, string> = {
  not_erupted: "未爆发",
  early_hype: "刚开始炒",
  ongoing_hype: "持续炒作",
  already_hyped: "已炒过",
  faded: "退潮",
  invalid: "证伪/过期",
};

export const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  archived: "归档",
};

export function targetTitle(t: { kind: string; name: string; code?: string | null }) {
  return t.name || t.code || t.kind;
}
