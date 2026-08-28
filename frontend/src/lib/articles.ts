/** 研报文章：AI 摘要/标题/标的抽取提示词 */

export interface ArticleDraftFile {
  filename?: string;
  title: string;
  summary: string;
  date?: string;
  /** 用户原文（落盘时保留） */
  original: string;
  stocks: { code?: string | null; name?: string | null }[];
  sectors: { name: string }[];
}

/** 消息分析录入：整篇研报提取后的结构化结果 */
export interface ArticleIngestExtract {
  title: string;
  summary: string;
  date: string;
  keywords: string[];
  impact_level: "critical" | "high" | "medium" | "low" | "noise";
  freshness: "new" | "follow_up" | "duplicate" | "rumor";
  effect_status:
    | "not_erupted"
    | "pending_verify"
    | "ongoing_hype"
    | "already_hyped"
    | "invalid";
  targets: { kind: string; code?: string | null; name: string }[];
  stocks: { code?: string | null; name?: string | null }[];
  sectors: { name: string }[];
  original: string;
}

function todayYmd(): string {
  const today = new Date();
  return [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
}

function parseJsonObject(text: string): Record<string, unknown> {
  const raw = (text || "").trim();
  if (!raw) throw new Error("模型未返回内容");
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const blob = fence ? fence[1].trim() : raw;
  const start = blob.indexOf("{");
  const end = blob.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("回复中未找到 JSON 对象");
  try {
    const obj = JSON.parse(blob.slice(start, end + 1));
    if (!obj || typeof obj !== "object") throw new Error("JSON 格式不正确");
    return obj as Record<string, unknown>;
  } catch (e) {
    if (e instanceof Error && (e.message.includes("JSON") || e.message.includes("未找到"))) throw e;
    throw new Error("JSON 解析失败，请重试");
  }
}

/** 从模型回复中抠出文章整理 JSON。 */
export function parseArticleJson(text: string, original: string): ArticleDraftFile[] {
  const obj = parseJsonObject(text);
  const files = obj.files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("JSON 缺少 files 数组");
  }
  const ymd = todayYmd();
  const out: ArticleDraftFile[] = [];
  for (const item of files) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    let title = String(row.title || "").trim();
    const summary = String(row.summary || "").trim();
    const filename = String(row.filename || "").trim();
    let date = String(row.date || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) date = ymd;
    if (!title) title = "未命名文章";
    const stocks: ArticleDraftFile["stocks"] = [];
    if (Array.isArray(row.stocks)) {
      for (const s of row.stocks) {
        if (!s || typeof s !== "object") continue;
        const sr = s as Record<string, unknown>;
        const code = String(sr.code || "").trim() || null;
        const name = String(sr.name || "").trim() || null;
        if (!code && !name) continue;
        stocks.push({ code, name });
      }
    }
    const sectors: ArticleDraftFile["sectors"] = [];
    if (Array.isArray(row.sectors)) {
      for (const s of row.sectors) {
        if (typeof s === "string" && s.trim()) {
          sectors.push({ name: s.trim() });
          continue;
        }
        if (!s || typeof s !== "object") continue;
        const name = String((s as Record<string, unknown>).name || "").trim();
        if (name) sectors.push({ name });
      }
    }
    out.push({
      title,
      summary: summary || title,
      date,
      original: original.trim(),
      stocks,
      sectors,
      ...(filename ? { filename } : {}),
    });
  }
  if (!out.length) throw new Error("files 中没有有效文章");
  return out;
}

const IMPACT = new Set(["critical", "high", "medium", "low", "noise"]);
const FRESHNESS = new Set(["new", "follow_up", "duplicate", "rumor"]);
const EFFECT = new Set([
  "not_erupted", "pending_verify", "ongoing_hype", "already_hyped", "invalid",
]);
const TARGET_KIND = new Set(["market", "sector", "theme", "stock", "other"]);

/** 消息分析「录入研报文章」：解析 AI 提取的结构化字段。 */
export function parseArticleIngestExtract(text: string, original: string): ArticleIngestExtract {
  const obj = parseJsonObject(text);
  const ymd = todayYmd();
  let title = String(obj.title || "").trim();
  if (!title) {
    const first = original.trim().split("\n")[0]?.trim() || "";
    title = first.slice(0, 80) || "未命名文章";
  }
  let summary = String(obj.summary || "").trim();
  if (summary.length > 120) summary = summary.slice(0, 117) + "…";
  if (!summary) summary = title;
  let date = String(obj.date || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) date = ymd;

  const keywords: string[] = [];
  if (Array.isArray(obj.keywords)) {
    for (const k of obj.keywords) {
      const s = String(k || "").trim();
      if (s && !keywords.includes(s)) keywords.push(s);
    }
  }

  let impact = String(obj.impact_level || "medium");
  if (!IMPACT.has(impact)) impact = "medium";
  let freshness = String(obj.freshness || "new");
  if (!FRESHNESS.has(freshness)) freshness = "new";
  let effect = String(obj.effect_status || "not_erupted");
  if (!EFFECT.has(effect)) effect = "not_erupted";

  const targets: ArticleIngestExtract["targets"] = [];
  const stocks: ArticleIngestExtract["stocks"] = [];
  const sectors: ArticleIngestExtract["sectors"] = [];
  const seenTarget = new Set<string>();
  const seenStock = new Set<string>();
  const seenSector = new Set<string>();

  if (Array.isArray(obj.targets)) {
    for (const t of obj.targets) {
      if (!t || typeof t !== "object") continue;
      const tr = t as Record<string, unknown>;
      let kind = String(tr.kind || "other").trim();
      if (!TARGET_KIND.has(kind)) kind = "other";
      const code = String(tr.code || "").trim() || null;
      const name = String(tr.name || code || "").trim();
      if (!name && !code) continue;
      const key = `${kind}|${code || ""}|${name}`;
      if (seenTarget.has(key)) continue;
      seenTarget.add(key);
      targets.push({ kind, code, name: name || code || "" });
      if (kind === "stock") {
        const sk = `${code || ""}|${name}`;
        if (!seenStock.has(sk)) {
          seenStock.add(sk);
          stocks.push({ code, name: name || null });
        }
      }
      if ((kind === "sector" || kind === "theme") && name && !seenSector.has(name)) {
        seenSector.add(name);
        sectors.push({ name });
      }
    }
  }
  if (Array.isArray(obj.stocks)) {
    for (const s of obj.stocks) {
      if (!s || typeof s !== "object") continue;
      const sr = s as Record<string, unknown>;
      const code = String(sr.code || "").trim() || null;
      const name = String(sr.name || "").trim() || null;
      if (!code && !name) continue;
      const sk = `${code || ""}|${name || ""}`;
      if (seenStock.has(sk)) continue;
      seenStock.add(sk);
      stocks.push({ code, name });
      const tk = `stock|${code || ""}|${name || code || ""}`;
      if (!seenTarget.has(tk)) {
        seenTarget.add(tk);
        targets.push({ kind: "stock", code, name: name || code || "" });
      }
    }
  }
  if (Array.isArray(obj.sectors)) {
    for (const s of obj.sectors) {
      let name = "";
      if (typeof s === "string") name = s.trim();
      else if (s && typeof s === "object") name = String((s as Record<string, unknown>).name || "").trim();
      if (!name || seenSector.has(name)) continue;
      seenSector.add(name);
      sectors.push({ name });
      const tk = `sector||${name}`;
      if (!seenTarget.has(tk)) {
        seenTarget.add(tk);
        targets.push({ kind: "sector", code: null, name });
      }
    }
  }

  return {
    title,
    summary,
    date,
    keywords,
    impact_level: impact as ArticleIngestExtract["impact_level"],
    freshness: freshness as ArticleIngestExtract["freshness"],
    effect_status: effect as ArticleIngestExtract["effect_status"],
    targets,
    stocks,
    sectors,
    original: original.trim(),
  };
}

export function buildArticleIngestPrompt(note: string): string {
  const ymd = todayYmd();
  return [
    "你是 A 股研报/文章结构化整理助手。用户粘贴的是一整篇研报或深度文章，请分析全文并提取字段。",
    "硬性规则：",
    "1. 只做信息整理与客观标注；不推荐买卖、不预测涨跌、不给目标价。",
    "2. 保留整篇原文语义，不要改写正文；original 字段原样回传用户输入。",
    "3. 若原文无明显标题，生成简洁中文标题；有则提取。",
    "4. summary 为一句话摘要（≤120字）。",
    "5. date 优先用文中明确日期（YYYY-MM-DD）；否则用 " + ymd + "。",
    "6. keywords：3～8 个关键词（题材/行业/事件）。",
    "7. targets：关联标的，kind 为 stock|sector|theme|market|other；个股尽量给 6 位 code。",
    "8. stocks / sectors：分别列出文中个股与板块/题材（可与 targets 对应）。",
    "9. impact_level / freshness / effect_status 按消息分析口径标注。",
    "10. 只输出一个 JSON 对象，不要解释、不要代码围栏。骨架：",
    '{"title":"标题","date":"' + ymd + '","summary":"一句话","original":"原文","keywords":["词"],"impact_level":"medium","freshness":"new","effect_status":"not_erupted","targets":[{"kind":"stock","code":"600519","name":"贵州茅台"}],"stocks":[{"code":"600519","name":"贵州茅台"}],"sectors":[{"name":"白酒"}]}',
    "",
    "【用户粘贴的整篇原文】",
    note.trim(),
  ].join("\n");
}

export function buildArticlePrompt(
  note: string,
  articles: { filename: string; title: string; summary: string }[],
): string {
  const indexBlock = articles.length
    ? articles.map((t) => `- ${t.title} | ${t.filename} — ${t.summary || "（无摘要）"}`).join("\n")
    : "（尚无文章）";
  const ymd = todayYmd();
  return [
    "你是 A 股研报/文章整理助手。用户粘贴的是文字版研报或资讯文章。",
    "要求：",
    "1. 保留原文，不要改写、不要删减正文；original 字段原样回传用户输入。",
    "2. 若原文无明显标题，生成简洁中文标题；有则提取。",
    "3. summary 为一句话摘要（≤80字），客观陈述，不给买卖建议。",
    "4. date 优先用文中明确日期（YYYY-MM-DD）；否则用 " + ymd + "。",
    "5. filename 建议为「标题-YYYY-MM-DD.md」（中文可）。",
    "6. stocks：文中提及的 A 股个股，每项 {\"code\":\"6位或null\",\"name\":\"名称\"}。",
    "7. sectors：文中提及的板块/题材/行业，每项 {\"name\":\"名称\"}。",
    "8. 通常一次输入对应 1 篇文章（files 长度 1）；不要把多篇无关内容硬拆。",
    "9. 只输出一个 JSON 对象，不要解释、不要代码围栏。骨架：",
    '{"files":[{"filename":"标题-2026-08-28.md","title":"标题","date":"2026-08-28","summary":"一句话","original":"原文","stocks":[{"code":"600519","name":"贵州茅台"}],"sectors":[{"name":"白酒"}]}]}',
    "",
    "【现有文章索引】（避免标题严重重复时可微调命名）",
    indexBlock,
    "",
    "【用户粘贴的原文】",
    note.trim(),
  ].join("\n");
}
