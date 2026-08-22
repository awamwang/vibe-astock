/** 经验记忆：开关偏好与 AI 归纳提示词 */

export const EXPERIENCE_USE_KEY = "va-use-experience-memory";

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
}

/** 从模型回复中抠出归纳 JSON。 */
export function parseOrganizeJson(text: string): OrganizeDraftFile[] {
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
    throw new Error("JSON 解析失败，请重试归纳");
  }
  if (!obj || typeof obj !== "object") throw new Error("JSON 格式不正确");
  const files = (obj as { files?: unknown }).files;
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("JSON 缺少 files 数组");
  }
  const out: OrganizeDraftFile[] = [];
  for (const item of files) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const title = String(row.title || "").trim();
    const content = String(row.content || "").trim();
    const summary = String(row.summary || "").trim();
    const filename = String(row.filename || "").trim();
    if (!title || !content) continue;
    out.push({
      title,
      summary: summary || title,
      content,
      ...(filename ? { filename } : {}),
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
  return [
    "你是 A 股短线交易经验整理助手。把用户新输入的经验，归纳进「有组织的主题记忆」。",
    "要求：",
    "1. 可合并进已有主题，也可新建主题；主题名用简洁中文。",
    "2. filename 用中文且以 .md 结尾，与 title 对应（如 情绪周期.md）。",
    "3. content 为完整 Markdown 正文（合并时保留旧要点并吸收新内容，去重、结构化）。",
    "4. summary 为一句话摘要（≤40字）。",
    "5. 只输出一个 JSON 对象，不要解释、不要代码围栏。骨架：",
    '{"files":[{"filename":"主题.md","title":"主题","summary":"一句话","content":"markdown全文"}]}',
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
