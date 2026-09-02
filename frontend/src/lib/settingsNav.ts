export const KEYWORDS_SECTION_IDS = [
  "zt-keywords",
  "message-follow",
  "theme-aliases",
  "sentiment-s",
  "trade-thresholds",
  "trade-phases",
] as const;

export type KeywordsSectionId = (typeof KEYWORDS_SECTION_IDS)[number];

export const DATA_SECTION_IDS = [
  "stock-universe",
  "data-dirs",
  "series",
  "import-export",
] as const;

export type DataSectionId = (typeof DATA_SECTION_IDS)[number];

export const SYSTEM_SECTION_IDS = [
  "proxy",
] as const;

export type SystemSectionId = (typeof SYSTEM_SECTION_IDS)[number];

const KEYWORDS_SET = new Set<string>(KEYWORDS_SECTION_IDS);
const DATA_SET = new Set<string>(DATA_SECTION_IDS);
const SYSTEM_SET = new Set<string>(SYSTEM_SECTION_IDS);

export function parseKeywordsSection(raw: string | null | undefined): KeywordsSectionId {
  if (raw && KEYWORDS_SET.has(raw)) return raw as KeywordsSectionId;
  return "zt-keywords";
}

export function parseDataSection(raw: string | null | undefined): DataSectionId {
  if (raw && DATA_SET.has(raw)) return raw as DataSectionId;
  return "stock-universe";
}

export function parseSystemSection(raw: string | null | undefined): SystemSectionId {
  if (raw && SYSTEM_SET.has(raw)) return raw as SystemSectionId;
  return "proxy";
}

export function keywordsSettingsTo(section: KeywordsSectionId): string {
  return `/settings/keywords?section=${section}`;
}

export function dataSettingsTo(section: DataSectionId): string {
  return `/settings/data?section=${section}`;
}

export function systemSettingsTo(section: SystemSectionId): string {
  return `/settings/system?section=${section}`;
}
