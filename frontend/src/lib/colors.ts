

/** 涨（正向、强）用的文字色 */
export const UP_TEXT = "text-danger";
/** 跌（负向、弱）用的文字色 */
export const DOWN_TEXT = "text-success";
/** 平/无值 */
export const FLAT_TEXT = "text-muted-foreground";

export function pctColor(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return FLAT_TEXT;
  return v > 0 ? UP_TEXT : v < 0 ? DOWN_TEXT : FLAT_TEXT;
}

/**
 * 涨停/跌停**家数**这类计数的颜色。方向是写死的，不看数值正负
 * （跌停 30 家，30 是正数，但它表达的是"跌"）。
 *
 * @param direction "up" = 涨停/晋级/收红一类；"down" = 跌停/跌超/大面一类
 */
export function countColor(direction: "up" | "down"): string {
  return direction === "up" ? UP_TEXT : DOWN_TEXT;
}

/**
 * 强弱类指标（走强/转弱、没炸过、延续率高低）的颜色。
 *
 * 严格说这不是"涨跌"，但中文语境里**强=红、弱=绿**是同一套色觉习惯，
 * 跟涨跌配色分开会让同一屏出现两种语义的红绿，更容易看错。
 */
export function strengthColor(strong: boolean | null | undefined): string {
  if (strong == null) return FLAT_TEXT;
  return strong ? UP_TEXT : DOWN_TEXT;
}
