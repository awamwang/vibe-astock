"""钩子系统内置 JSON Schema 标识（$id + schema_version）。"""

from __future__ import annotations

SCHEMA_BASE = "https://vibe-astock.dev/schemas/hook"
ENGINE_VERSION = "0.1.4"

ENVELOPE = f"{SCHEMA_BASE}/envelope/1.0.0"
METRICS_SNAPSHOT = f"{SCHEMA_BASE}/metrics-snapshot/1.0.0"
LIVE_SNAPSHOT = f"{SCHEMA_BASE}/live-snapshot/1.0.0"
BUDGET_SNAPSHOT = f"{SCHEMA_BASE}/budget-snapshot/1.0.0"
VERIFICATION_SNAPSHOT = f"{SCHEMA_BASE}/verification-snapshot/1.0.0"
REVIEW_SAVED = f"{SCHEMA_BASE}/review-saved/1.0.0"
PORTFOLIO_IMPORT = f"{SCHEMA_BASE}/portfolio-import/1.0.0"
ACCOUNT_IMPORT = f"{SCHEMA_BASE}/account-import/1.0.0"
WATCHLIST_IMPORT = f"{SCHEMA_BASE}/watchlist-import/1.0.0"
WATCHLIST_ADD = f"{SCHEMA_BASE}/watchlist-add/1.0.0"
WATCHLIST_CHANGE = f"{SCHEMA_BASE}/watchlist-change/1.0.0"
MESSAGE_PUSH = f"{SCHEMA_BASE}/message-push/1.0.0"
MESSAGE_ANALYZED = f"{SCHEMA_BASE}/message-analyzed/1.0.0"
EXPERIENCE_IMPORT = f"{SCHEMA_BASE}/experience-import/1.0.0"
ARTICLE_PUSH = f"{SCHEMA_BASE}/article-push/1.0.0"

SCHEMA_VERSION = "1.0.0"
