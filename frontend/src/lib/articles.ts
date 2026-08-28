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

/** 从模型回复中抠出文章整理 JSON。 */
export function parseArticleJson(text: string, original: string): ArticleDraftFile[] {
  const raw = (text || "").trim();
  if (!raw) throw new Error("模型未返回内容");
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const blob = fence ? fence[1].trim() : raw;
  const start = blob.indexOf("{");
  const end = blob.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("回复中未找到 JSON 对象");
  let obj: unknown;
  try {
    obj = JSON.parse(blob.slice(start, end + 1));
  } catch {
    throw new Error("JSON 解析失败，请重试整理");
  }
  if (!obj || typeof obj !== "object") throw new Error("JSON 格式不正确");
  const files = (obj as { files?: unknown }).files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("JSON 缺少 files 数组");
  }
  const today = new Date();
  const ymd = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
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

export function buildArticlePrompt(
  note: string,
  articles: { filename: string; title: string; summary: string }[],
): string {
  const indexBlock = articles.length
    ? articles.map((t) => `- ${t.title} | ${t.filename} — ${t.summary || "（无摘要）"}`).join("\n")
    : "（尚无文章）";
  const today = new Date();
  const ymd = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
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
