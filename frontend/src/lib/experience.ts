/** 经验记忆：开关偏好与 AI 整理提示词 */

export const EXPERIENCE_USE_KEY = "va-use-experience-memory";

export const EXPERIENCE_CATEGORIES = [
  "踩坑",
  "操作指引",
  "方法论",
  "盘感复盘",
  "仓位纪律",
] as const;

export type ExperienceCategory = (typeof EXPERIENCE_CATEGORIES)[number];

const CATEGORY_SET = new Set<string>(EXPERIENCE_CATEGORIES);
const CATEGORY_ALIASES: [string, ExperienceCategory][] = [
  ["踩坑", "踩坑"],
  ["教训", "踩坑"],
  ["错误", "踩坑"],
  ["操作指引", "操作指引"],
  ["指引", "操作指引"],
  ["打法", "操作指引"],
  ["方法论", "方法论"],
  ["框架", "方法论"],
  ["盘感复盘", "盘感复盘"],
  ["盘感", "盘感复盘"],
  ["复盘", "盘感复盘"],
  ["仓位纪律", "仓位纪律"],
  ["仓位", "仓位纪律"],
  ["纪律", "仓位纪律"],
  ["风控", "仓位纪律"],
];

export function loadUseExperienceMemory(): boolean {
  try {
    const v = localStorage.getItem(EXPERIENCE_USE_KEY);
    if (v === null) return true;
    return v !== "0" && v !== "false";
  } catch {
    return true;
  }
}

export function saveUseExperienceMemory(on: boolean) {
  try {
    localStorage.setItem(EXPERIENCE_USE_KEY, on ? "1" : "0");
  } catch {
    /* 隐私模式等 */
  }
}

export interface OrganizeDraftFile {
  filename?: string;
  title: string;
  summary: string;
  content: string;
  date: string;
  category: ExperienceCategory;
  stocks: { code?: string | null; name?: string | null }[];
  sectors: { name: string }[];
}

function todayYmd(): string {
  const today = new Date();
  return [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
}

export function suffixTitleDate(title: string, date: string): string {
  const raw = (title || "").trim().replace(/\.md$/i, "") || "未命名主题";
  const base = raw.replace(/-\d{4}-\d{2}-\d{2}$/, "").trim() || "未命名主题";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return base;
  return `${base}-${date}`;
}

export function normalizeExperienceCategory(raw: string): ExperienceCategory {
  const s = (raw || "").trim();
  if (CATEGORY_SET.has(s)) return s as ExperienceCategory;
  for (const [key, cat] of CATEGORY_ALIASES) {
    if (key && s.includes(key)) return cat;
  }
  return "方法论";
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
    throw new Error("JSON 解析失败，请重试整理");
  }
}

/** 从模型回复中抠出整理 JSON。 */
export function parseOrganizeJson(text: string): OrganizeDraftFile[] {
  const obj = parseJsonObject(text);
  const files = obj.files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("JSON 缺少 files 数组");
  }
  const ymd = todayYmd();
  const out: OrganizeDraftFile[] = [];
  for (const item of files) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    let title = String(row.title || "").trim();
    const content = String(row.content || "").trim();
    const summary = String(row.summary || "").trim();
    const filename = String(row.filename || "").trim();
    let date = String(row.date || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) date = ymd;
    if (!title || !content) continue;
    title = suffixTitleDate(title, date);
    const stocks: OrganizeDraftFile["stocks"] = [];
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
    const sectors: OrganizeDraftFile["sectors"] = [];
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
      content,
      date,
      category: normalizeExperienceCategory(String(row.category || "")),
      stocks,
      sectors,
      filename: filename || `${title}.md`,
    });
  }
  if (!out.length) throw new Error("files 中没有有效主题");
  return out;
}

export function buildOrganizePrompt(
  note: string,
  topics: { filename: string; title: string; summary: string }[],
  existingBodies: { filename: string; title: string; content: string }[],
): string {
  const indexBlock = topics.length
    ? topics.map((t) => `- ${t.title} | ${t.filename} — ${t.summary || "（无摘要）"}`).join("\n")
    : "（尚无主题）";
  const bodyBlock = existingBodies.length
    ? existingBodies.map((t) => `### ${t.title}（${t.filename}）\n${t.content.slice(0, 4000)}`).join("\n\n")
    : "（无正文）";
  const ymd = todayYmd();
  const cats = EXPERIENCE_CATEGORIES.join(" / ");
  return [
    "你是 A 股短线交易经验整理助手。把用户新输入的经验，整理成可检索的主题记忆。",
    "要求：",
    "1. 通常一次输入对应 1 条经验（files 长度 1）；仅当与某已有主题高度同主题时可合并进该文件（保留其 filename）。",
    "2. 主题名用简洁中文，概括这条经验的核心，禁止口号式标题。",
    "3. date 优先用文中明确日期（YYYY-MM-DD）；否则用 " + ymd + "。标题不要手写日期，系统会自动把日期后缀到标题。",
    "4. filename 为「标题-YYYY-MM-DD.md」（中文可）；合并已有主题时沿用其 filename。",
    "5. category 必须是以下之一：" + cats + "。",
    "   - 踩坑：做错了什么、为何亏、下次避免",
    "   - 操作指引：某情景下怎么做（节奏、仓位、等待）",
    "   - 方法论：可复用的框架/原则",
    "   - 盘感复盘：对某场/某段盘面的体感总结",
    "   - 仓位纪律：仓位、止损、不满仓等风控",
    "6. stocks：文中提及的 A 股个股，每项 {\"code\":\"6位或null\",\"name\":\"名称\"}；没有则 []。写入时还会按消息分析口径扫描正文，增量补全。",
    "7. sectors：文中提及的板块/题材/行业，每项 {\"name\":\"名称\"}；没有则 []。写入时同样扫描正文并匹配。",
    "8. content 为整理后的 Markdown 正文（合并时保留旧要点并吸收新内容，去重、结构化）。不要再写标题、日期、分类、个股、板块元数据行，那些由系统写入。",
    "9. summary 为一句话摘要（≤40字）。",
    "10. 只输出一个 JSON 对象，不要解释、不要代码围栏。骨架：",
    '{"files":[{"filename":"连板掉下来宁可等二波-' + ymd + '.md","title":"连板掉下来宁可等二波","date":"' + ymd + '","category":"踩坑","summary":"一句话","content":"markdown正文","stocks":[{"code":"000001","name":"平安银行"}],"sectors":[{"name":"连板"}]}]}',
    "",
    "【现有主题索引】",
    indexBlock,
    "",
    "【相关主题正文】",
    bodyBlock,
    "",
    "【用户新输入】",
    note.trim(),
  ].join("\n");
}
