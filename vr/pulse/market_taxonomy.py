"""多源概率总览的共享模块分类。"""
from __future__ import annotations

CORE_MODULES: list[str] = ["货币政策", "宏观经济", "地缘政治", "政治选举", "股指大宗", "AI科技"]
REFERENCE_MODULES: list[str] = ["加密", "体育", "娱乐", "其他"]
MODULES: list[str] = CORE_MODULES + REFERENCE_MODULES
CORE_SET: frozenset[str] = frozenset(CORE_MODULES)

MODULE_CAPS: dict[str, int] = {
    "货币政策": 8,
    "宏观经济": 8,
    "地缘政治": 12,
    "政治选举": 8,
    "股指大宗": 8,
    "AI科技": 8,
    "加密": 6,
    "体育": 6,
    "娱乐": 5,
    "其他": 6,
}

_GEO = [
    "china", "taiwan", "tariff", "trade war", "xi jinping", "hormuz", "iran", "venezuela",
    "russia", "ukraine", "blockade", "north korea", "israel", "gaza", "hezbollah", "lebanon",
    "syria", "middle east", " nato", "nuclear", "missile", "ceasefire", "invade", "war ",
    "military", "peace deal", "strike on",
]
_MONETARY = ["fed ", "fed decision", "fed funds", "federal reserve", "interest rate", "rate cut",
             "rate hike", "fomc", "powell", "basis point", "rate after"]
_MACRO = ["recession", " gdp", "inflation", " cpi", "unemployment", "jobs report", "jobs numbers",
          "payroll", "nonfarm", "jobless", " ppi", " pce", "gas price"]
_AI = ["nvidia", "openai", " agi", "semiconductor", "tsmc", " chip", "anthropic", "gpt", "chatgpt",
       "llm", "grok", "gemini", "claude", "deepmind", "artificial intelligence", "best ai",
       "humanoid robot", "deepseek"]
_INDEX_CMDTY = ["s&p", "nasdaq", "dow ", " stock", "earnings", " ipo", "market cap", "crude oil",
                "wti", "brent", "oil price", "gold price", "gold hit", "gold above", " xau",
                "commodit", " spy ", "valuation"]
_ELECTION = ["election", "president", " senate", "congress", "nominee", "potus", "white house",
             "governor", " mayor", "parliament", "prime minister", "referendum", "trump", "newsom",
             " vance", "midterm", "impeach", "attorney general", "reconciliation", "election winner"]
_CRYPTO = ["bitcoin", " btc", "ethereum", "crypto", "microstrategy", " mstr", "solana", "dogecoin",
           "coinbase", "stablecoin", "ripple", " xrp"]
_SPORTS = ["nba", "nfl", " mlb", "world series", "super bowl", "stanley cup", "tennis", " atp", " wta",
           "wimbledon", "us open", "french open", "australian open", "ufc", "boxing", "premier league",
           "la liga", "champions league", "grand prix", " pga ", "esports", " lol ", "cs2", "valorant",
           "dota", " vs.", " vs ", "world cup", "fifa", "golf", "tournament", "playoff", "champion",
           "basketball finals", "memorial tournament", " fc ", "afc ", "epl-"]
_ENT = ["movie", "oscar", "grammy", "box office", "taylor swift", "tweet", "person of the year",
        "rotten tomatoes", "billboard", "spotify", "netflix", "love island", "celebrity", "album",
        " song ", "emmy", "what will"]

_KALSHI_CAT_MAP: dict[str, str] = {
    "Economics": "宏观经济",
    "Financials": "股指大宗",
    "Commodities": "股指大宗",
    "Companies": "股指大宗",
    "Elections": "政治选举",
    "Politics": "政治选举",
    "World": "地缘政治",
    "Science and Technology": "其他",
    "Crypto": "加密",
    "Sports": "体育",
    "Entertainment": "娱乐",
    "Climate and Weather": "其他",
    "Health": "其他",
    "Social": "其他",
    "Transportation": "其他",
    "Mentions": "其他",
}


def _has(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def classify(question: str | None, kalshi_category: str | None = None) -> str:
    """把市场标题映射到模块；世界杯/FIFA 优先体育。"""
    t = " " + (question or "").lower() + " "
    if "world cup" in t or "fifa" in t:
        return "体育"
    if _has(t, _SPORTS):
        return "体育"
    if _has(t, _GEO):
        return "地缘政治"
    if _has(t, _MONETARY):
        return "货币政策"
    if _has(t, _MACRO):
        return "宏观经济"
    if _has(t, _AI):
        return "AI科技"
    if _has(t, _CRYPTO):
        return "加密"
    if _has(t, _INDEX_CMDTY):
        return "股指大宗"
    if _has(t, _ELECTION):
        return "政治选举"
    if _has(t, _ENT):
        return "娱乐"
    if kalshi_category:
        return _KALSHI_CAT_MAP.get(kalshi_category, "其他")
    return "其他"
