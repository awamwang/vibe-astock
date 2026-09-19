"""板块管理 —— 同花顺 / 开盘啦按类型融合。

概念 / 行业 / 地域：跨来源按「完全同名 + 板块别名族」并入同一页签（字段并集）；
自定义 / 热点主题：同花顺页签，并与全部开盘啦板块（概念/行业/地域/人气）同名匹配补字段；
每日动态仅同花顺；人气仅开盘啦。
风格指数：短线风格目录为主，按名称/别名匹配同花顺；成分走公开源，点开再取，匹配到同花顺时可补位。
合并后保留 ``kpl_name``（开盘啦原始名称）。
开盘啦侧经 ``kpl_blocks.ensure`` 初始化，自动日更最多一次。
"""

from __future__ import annotations

from typing import Any

from . import block_dialect as dialect
from . import kpl_blocks

# 跨源融合页签：key 与同花顺 kind 对齐
FUSED_KIND_KEYS = (
    ("conception", "conception", "concept", "概念"),
    ("industry", "industry", "industry", "行业"),
    ("region", "region", "region", "地域"),
)
# 同花顺独有
THS_ONLY_KEYS = (
    ("custom", "custom", "自定义"),
    ("daily", "daily", "每日动态"),
    ("theme", "theme", "热点主题"),
)
# 开盘啦独有
KPL_ONLY_KEYS = (
    ("hot", "hot", "人气"),
)
# 短线风格指数目录（公开源成分 + 按名称匹配同花顺）
STYLE_KIND = "style"
STYLE_KIND_LABEL = "风格指数"
STYLE_ROOT_ID = "__style_root__"

def _ths_snapshot() -> dict[str, Any]:
    try:
        from ths_block.service import get_snapshot  # noqa: PLC0415

        return get_snapshot()
    except Exception:  # noqa: BLE001
        return {
            "updated_at": None,
            "ths_dir": None,
            "kinds": {},
            "errors": [],
            "empty": True,
        }


def _blank_unified(*, name: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "origin": "",  # ths | kpl | style —— 行所属原始来源类型体系
        "sources": [],
        "has_ths": False,
        "has_kpl": False,
        "kind": "",
        "kind_label": "",
        "ths_kind": "",
        "id": "",
        "code": "",
        "node_type": "flat",
        "tree_path": name,
        "depth": None,
        "parent_id": None,
        "tree_order": None,
        "custom_type": None,
        "dynamic_kind": None,
        "query_key": None,
        "hex_id": None,
        "stock_count": None,
        "theme_key": None,
        "root_id": None,
        "block_type": None,
        "color": None,
        "color_order": None,
        "color_priority": None,
        "kpl_code": "",
        "kpl_name": "",  # 开盘啦原始名称（合并后展示名可能已是同花顺/标准名）
        "kpl_kind": "",
        "kpl_kind_label": "",
        "kpl_power": None,
        "kpl_pct": None,
        "kpl_speed": None,
        "kpl_m_net": None,
        "kpl_sort": None,
    }


def _name_key(name: str, *, region: bool = False) -> str:
    return dialect.canonicalize_name(name, region=region)


def _equivalence_keys(name: str, *, region: bool = False) -> set[str]:
    """同名 + 板块别名族的全部匹配键。

    含：去空白原名、canonicalize 标准名、归一到同一标准名的其它别名；
    地域再含去行政后缀键。
    """
    raw = dialect.norm_name(name)
    if not raw:
        return set()
    canon = dialect.canonicalize_name(raw, region=region)
    keys = {raw, canon}
    if region:
        stripped = dialect.strip_region_suffix(raw)
        if stripped:
            keys.add(stripped)
            keys.add(dialect.canonicalize_name(stripped, region=True))
    try:
        from .theme_normalize import load_aliases  # noqa: PLC0415

        aliases = load_aliases()
    except Exception:  # noqa: BLE001
        aliases = {}
    for alias in aliases:
        a = dialect.norm_name(alias)
        if not a:
            continue
        if dialect.canonicalize_name(a, region=region) == canon:
            keys.add(a)
    if canon:
        keys.add(canon)
    return {k for k in keys if k}


def _apply_ths(row: dict[str, Any], ths: dict[str, Any], *, native: bool = False) -> None:
    """写入同花顺字段。native=True 表示该行以同花顺为主。"""
    row["has_ths"] = True
    if "ths" not in row["sources"]:
        row["sources"].append("ths")
    ths_kind = str(ths.get("kind") or "").strip()
    if ths_kind:
        row["ths_kind"] = ths_kind
    if native:
        for key in (
            "kind", "kind_label", "id", "code", "node_type", "tree_path",
            "depth", "parent_id", "tree_order", "custom_type", "dynamic_kind",
            "query_key", "hex_id", "stock_count", "theme_key", "root_id", "block_type",
            "color", "color_order", "color_priority",
        ):
            if key in ths and ths[key] is not None:
                row[key] = ths[key]
        if ths_kind:
            row["kind"] = ths_kind
    else:
        for key in (
            "id", "code", "custom_type", "dynamic_kind",
            "query_key", "hex_id", "stock_count", "theme_key", "root_id", "block_type",
            "color", "color_order", "color_priority",
        ):
            if key in ths and ths[key] is not None and row.get(key) in (None, ""):
                row[key] = ths[key]
    if not row.get("name"):
        row["name"] = str(ths.get("name") or ths.get("id") or "")


def _apply_kpl(row: dict[str, Any], kpl: dict[str, Any], *, native: bool = False) -> None:
    """写入开盘啦字段。native=True 表示该行以开盘啦为主。"""
    row["has_kpl"] = True
    if "kpl" not in row["sources"]:
        row["sources"].append("kpl")
    row["kpl_code"] = str(kpl.get("code") or row.get("kpl_code") or "")
    row["kpl_kind"] = str(kpl.get("kind") or row.get("kpl_kind") or "")
    row["kpl_kind_label"] = str(kpl.get("kind_label") or row.get("kpl_kind_label") or "")
    kpl_name = str(kpl.get("name") or "").strip()
    if kpl_name:
        row["kpl_name"] = kpl_name
    for src, dst in (
        ("power", "kpl_power"),
        ("pct", "kpl_pct"),
        ("speed", "kpl_speed"),
        ("m_net", "kpl_m_net"),
        ("sort", "kpl_sort"),
    ):
        if row.get(dst) is None and kpl.get(src) is not None:
            row[dst] = kpl[src]
    if not row.get("name"):
        row["name"] = kpl_name or str(kpl.get("code") or "")
    if native:
        row["node_type"] = "flat"
        if not row.get("tree_path"):
            row["tree_path"] = row["name"]


def _kpl_by_name_for_kind(
    kpl_snap: dict[str, Any],
    kpl_kind: str,
    *,
    region: bool = False,
) -> dict[str, dict]:
    """仅某一开盘啦原始类型的 名称键→行（含别名族键）。"""
    out: dict[str, dict] = {}
    entry = (kpl_snap.get("kinds") or {}).get(kpl_kind) or {}
    for row in entry.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for key in _equivalence_keys(str(row.get("name") or ""), region=region):
            if key not in out:
                out[key] = row
    return out


def _kpl_structural_by_name(kpl_snap: dict[str, Any]) -> dict[str, dict]:
    """开盘啦结构榜（概念/行业/地域）名称键→行；同名时先写入者优先。"""
    out: dict[str, dict] = {}
    for kind in ("concept", "industry", "region"):
        for key, row in _kpl_by_name_for_kind(
            kpl_snap, kind, region=(kind == "region"),
        ).items():
            if key not in out:
                out[key] = row
    return out


def _lookup_kpl(kpl_map: dict[str, dict], name: str, *, region: bool = False) -> dict | None:
    """按同名 / 别名族查找开盘啦行。"""
    for key in _equivalence_keys(name, region=region):
        hit = kpl_map.get(key)
        if hit:
            return hit
    return None


def _ths_leaf_by_name(
    ths_snap: dict[str, Any],
    ths_kind: str | None = None,
    *,
    region: bool = False,
) -> dict[str, dict]:
    """同花顺叶子 名称键→行（含别名族）；可限定类型。"""
    out: dict[str, dict] = {}
    kinds = (ths_kind,) if ths_kind else ("conception", "industry", "region", "custom", "daily", "theme")
    for kind in kinds:
        entry = (ths_snap.get("kinds") or {}).get(kind) or {}
        for ths in entry.get("rows") or []:
            if not isinstance(ths, dict):
                continue
            if str(ths.get("node_type") or "") == "branch":
                continue
            for key in _equivalence_keys(
                str(ths.get("name") or ""),
                region=region or kind == "region",
            ):
                if key not in out:
                    out[key] = ths
    return out


def _enrich_hot(row: dict[str, Any], hot: dict[str, Any] | None) -> None:
    """人气 PlateID 作点查码补全。"""
    if not hot:
        return
    code = str(hot.get("code") or "")
    if not code:
        return
    row["kpl_code"] = code
    row["has_kpl"] = True
    if "kpl" not in row["sources"]:
        row["sources"].append("kpl")
    hot_name = str(hot.get("name") or "").strip()
    if hot_name and not row.get("kpl_name"):
        row["kpl_name"] = hot_name
    if hot.get("power") is not None and row.get("kpl_power") is None:
        row["kpl_power"] = hot.get("power")
    if not row.get("kpl_kind"):
        row["kpl_kind"] = "hot"
        row["kpl_kind_label"] = str(hot.get("kind_label") or "人气")


def _attach_kpl_to_ths(
    row: dict[str, Any],
    *,
    name: str,
    kpl_map: dict[str, dict],
    hot_map: dict[str, dict],
    region: bool,
    matched_codes: set[str],
) -> None:
    """把开盘啦结构榜 / 人气榜并入同花顺行，按 code 去重。"""
    hit = _lookup_kpl(kpl_map, name, region=region)
    if hit:
        code = str(hit.get("code") or "").strip()
        if code and code in matched_codes:
            pass
        else:
            _apply_kpl(row, hit, native=False)
            if code:
                matched_codes.add(code)
    if not row.get("kpl_code"):
        hot = _lookup_kpl(hot_map, name, region=region)
        if hot:
            code = str(hot.get("code") or "").strip()
            if not (code and code in matched_codes):
                _enrich_hot(row, hot)
                if code:
                    matched_codes.add(code)


def _build_fused_kind(
    *,
    ths_kind: str,
    kpl_kind: str,
    kind_label: str,
    ths_rows: list[dict],
    kpl_snap: dict[str, Any],
) -> list[dict]:
    """概念/行业/地域：同花顺 + 开盘啦按同名/别名融合到同一页签。"""
    is_region = ths_kind == "region"
    kpl_map = _kpl_by_name_for_kind(kpl_snap, kpl_kind, region=is_region)
    hot_map = _kpl_by_name_for_kind(kpl_snap, "hot", region=is_region)
    matched_codes: set[str] = set()

    # 先收集同花顺行（保持原始顺序），匹配阶段叶子优先占用开盘啦 code
    ths_built: list[tuple[dict, dict]] = []  # (src, row)
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        name = str(ths.get("name") or ths.get("id") or "")
        row = _blank_unified(name=name)
        row["origin"] = "ths"
        _apply_ths(row, ths, native=True)
        row["kind"] = ths_kind
        row["kind_label"] = str(ths.get("kind_label") or kind_label)
        row["ths_kind"] = ths_kind
        ths_built.append((ths, row))

    def _is_branch(src: dict) -> bool:
        return str(src.get("node_type") or "") == "branch"

    for ths, row in ths_built:
        if _is_branch(ths):
            continue
        _attach_kpl_to_ths(
            row,
            name=str(row.get("name") or ""),
            kpl_map=kpl_map,
            hot_map=hot_map,
            region=is_region,
            matched_codes=matched_codes,
        )
    for ths, row in ths_built:
        if not _is_branch(ths) or row.get("kpl_code"):
            continue
        _attach_kpl_to_ths(
            row,
            name=str(row.get("name") or ""),
            kpl_map=kpl_map,
            hot_map=hot_map,
            region=is_region,
            matched_codes=matched_codes,
        )

    out: list[dict] = [row for _, row in ths_built]

    entry = (kpl_snap.get("kinds") or {}).get(kpl_kind) or {}
    for cand in entry.get("rows") or []:
        if not isinstance(cand, dict):
            continue
        code = str(cand.get("code") or "").strip()
        name = str(cand.get("name") or code)
        if code and code in matched_codes:
            continue
        # 同名/别名已并入同花顺行时不再追加（无 code 时用键兜底）
        if not code:
            hit_ths = False
            for _, row in ths_built:
                if _equivalence_keys(str(row.get("name") or ""), region=is_region) & _equivalence_keys(
                    name, region=is_region
                ):
                    if not row.get("kpl_code"):
                        _apply_kpl(row, cand, native=False)
                    hit_ths = True
                    break
            if hit_ths:
                continue
        row = _blank_unified(name=name)
        row["origin"] = "kpl"
        _apply_kpl(row, cand, native=True)
        row["kind"] = ths_kind
        row["kind_label"] = kind_label
        row["kpl_kind"] = kpl_kind
        row["kpl_kind_label"] = str(cand.get("kind_label") or kind_label)
        row["node_type"] = "flat"
        row["tree_path"] = f"{kind_label} › {name}"
        row["parent_id"] = f"__kpl_{kpl_kind}_root__"
        row["depth"] = 1
        if code:
            matched_codes.add(code)
        out.append(row)

    return out


def _build_ths_only(
    *,
    ths_kind: str,
    kind_label: str,
    ths_rows: list[dict],
) -> list[dict]:
    """同花顺独有类型页签。"""
    out: list[dict] = []
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        name = str(ths.get("name") or ths.get("id") or "")
        row = _blank_unified(name=name)
        row["origin"] = "ths"
        _apply_ths(row, ths, native=True)
        row["kind"] = ths_kind
        row["kind_label"] = str(ths.get("kind_label") or kind_label)
        row["ths_kind"] = ths_kind
        out.append(row)
    return out


def _build_ths_with_kpl_match(
    *,
    ths_kind: str,
    kind_label: str,
    ths_rows: list[dict],
    kpl_snap: dict[str, Any],
) -> list[dict]:
    """同花顺页签行，并与开盘啦结构榜/人气按同名/别名补字段（不并入开盘啦独有行）。"""
    kpl_map = _kpl_structural_by_name(kpl_snap)
    hot_map = _kpl_by_name_for_kind(kpl_snap, "hot")
    matched_codes: set[str] = set()

    ths_built: list[tuple[dict, dict]] = []
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        name = str(ths.get("name") or ths.get("id") or "")
        row = _blank_unified(name=name)
        row["origin"] = "ths"
        _apply_ths(row, ths, native=True)
        row["kind"] = ths_kind
        row["kind_label"] = str(ths.get("kind_label") or kind_label)
        row["ths_kind"] = ths_kind
        ths_built.append((ths, row))

    def _is_branch(src: dict) -> bool:
        return str(src.get("node_type") or "") == "branch"

    for ths, row in ths_built:
        if _is_branch(ths):
            continue
        _attach_kpl_to_ths(
            row,
            name=str(row.get("name") or ""),
            kpl_map=kpl_map,
            hot_map=hot_map,
            region=False,
            matched_codes=matched_codes,
        )
        # 热点主题：再用 theme_key 试一次开盘啦同名
        if ths_kind == "theme" and not row.get("kpl_code"):
            tk = str(row.get("theme_key") or "").strip()
            if tk and tk != str(row.get("name") or ""):
                _attach_kpl_to_ths(
                    row,
                    name=tk,
                    kpl_map=kpl_map,
                    hot_map=hot_map,
                    region=False,
                    matched_codes=matched_codes,
                )
    for ths, row in ths_built:
        if not _is_branch(ths) or row.get("kpl_code"):
            continue
        _attach_kpl_to_ths(
            row,
            name=str(row.get("name") or ""),
            kpl_map=kpl_map,
            hot_map=hot_map,
            region=False,
            matched_codes=matched_codes,
        )
        if ths_kind == "theme" and not row.get("kpl_code"):
            tk = str(row.get("theme_key") or "").strip()
            if tk and tk != str(row.get("name") or ""):
                _attach_kpl_to_ths(
                    row,
                    name=tk,
                    kpl_map=kpl_map,
                    hot_map=hot_map,
                    region=False,
                    matched_codes=matched_codes,
                )

    return [row for _, row in ths_built]


def _build_custom(
    *,
    ths_rows: list[dict],
    kpl_snap: dict[str, Any],
) -> list[dict]:
    """自定义页签：同花顺行，并与全部开盘啦板块同名/别名匹配补字段。

    不把开盘啦独有行并入本页签；结构榜优先，人气作点查码兜底。
    """
    return _build_ths_with_kpl_match(
        ths_kind="custom",
        kind_label="自定义",
        ths_rows=ths_rows,
        kpl_snap=kpl_snap,
    )


def _build_kpl_hot(
    *,
    kpl_rows: list[dict],
    ths_snap: dict[str, Any],
) -> list[dict]:
    """开盘啦人气页签；同名同花顺仅补字段。"""
    ths_map = _ths_leaf_by_name(ths_snap)
    out: list[dict] = []
    for cand in kpl_rows:
        if not isinstance(cand, dict):
            continue
        code = str(cand.get("code") or "")
        name = str(cand.get("name") or code)
        row = _blank_unified(name=name)
        row["origin"] = "kpl"
        _apply_kpl(row, cand, native=True)
        row["kind"] = "hot"
        row["kind_label"] = "人气"
        row["kpl_kind"] = "hot"
        row["kpl_kind_label"] = "人气"
        row["node_type"] = "flat"
        row["tree_path"] = f"人气 › {name}"
        row["parent_id"] = "__kpl_hot_root__"
        row["depth"] = 1
        ths_hit = None
        for k in _equivalence_keys(name):
            ths_hit = ths_map.get(k)
            if ths_hit:
                break
        if ths_hit:
            _apply_ths(row, ths_hit, native=False)
            row["kind"] = "hot"
            row["kind_label"] = "人气"
            row["origin"] = "kpl"
            row["node_type"] = "flat"
            row["tree_path"] = f"人气 › {name}"
            row["parent_id"] = "__kpl_hot_root__"
            row["depth"] = 1
        out.append(row)
    return out


def _lookup_ths_leaf(ths_map: dict[str, dict], name: str) -> dict | None:
    """按同名 / 别名族查找同花顺叶子。"""
    for key in _equivalence_keys(name):
        hit = ths_map.get(key)
        if hit:
            return hit
    return None


def _build_style(*, ths_snap: dict[str, Any]) -> list[dict]:
    """风格指数页签：目录叶子平铺，不造合成分组树。"""
    from . import style_cons, style_indices  # noqa: PLC0415

    ths_map = _ths_leaf_by_name(ths_snap)
    group_label_by_id = {gid: label for gid, label in style_indices.GROUPS}
    out: list[dict] = []

    def _append_leaf(
        *,
        key: str,
        name: str,
        group: str,
        group_label: str,
        code: str,
        spec: dict[str, Any],
    ) -> None:
        row = _blank_unified(name=name)
        row["origin"] = "style"
        row["sources"] = ["style"]
        row["kind"] = STYLE_KIND
        row["kind_label"] = STYLE_KIND_LABEL
        row["code"] = code
        row["style_key"] = key
        row["style_group"] = group
        row["style_group_label"] = group_label
        row["node_type"] = "leaf"
        row["tree_path"] = (
            f"{STYLE_KIND_LABEL} › {group_label} › {name}"
            if group_label else f"{STYLE_KIND_LABEL} › {name}"
        )
        row["parent_id"] = STYLE_ROOT_ID
        row["depth"] = 1
        row["cons_available"] = bool(spec.get("cons_available"))
        row["cons_source"] = spec.get("cons_source")
        row["cons_source_label"] = spec.get("cons_source_label")
        row["cons_reason"] = spec.get("cons_reason")
        row["cons_note"] = spec.get("cons_note")
        ths_hit = _lookup_ths_leaf(ths_map, name)
        if ths_hit:
            _apply_ths(row, ths_hit, native=False)
            row["kind"] = STYLE_KIND
            row["kind_label"] = STYLE_KIND_LABEL
            row["code"] = code
            row["origin"] = "style"
            if "style" not in row["sources"]:
                row["sources"].insert(0, "style")
            if not row.get("id"):
                row["id"] = str(ths_hit.get("id") or f"style:{key}")
        else:
            row["id"] = f"style:{key}"
        out.append(row)

    for item in style_indices.ITEMS:
        spec = style_cons.classify(item.key, code=item.code, group=item.group)
        _append_leaf(
            key=item.key,
            name=item.name,
            group=item.group,
            group_label=group_label_by_id.get(item.group) or item.group,
            code=item.code,
            spec=spec,
        )

    unavail_label = "未接入"
    for item in style_indices.UNAVAILABLE:
        key = str(item.get("key") or "")
        name = str(item.get("name") or key)
        spec = style_cons.classify(key, reason=str(item.get("reason") or ""))
        _append_leaf(
            key=key,
            name=name,
            group="unavailable",
            group_label=unavail_label,
            code="",
            spec=spec,
        )
    return out


def _ths_ref_for_style_key(key: str, *, ths_snap: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """风格目录名 / 别名命中的同花顺叶子 (kind, id)。"""
    from . import style_indices  # noqa: PLC0415

    name = ""
    item = next((it for it in style_indices.ITEMS if it.key == key), None)
    if item is not None:
        name = item.name
    else:
        unavail = next((u for u in style_indices.UNAVAILABLE if str(u.get("key")) == key), None)
        if unavail:
            name = str(unavail.get("name") or "")
    if not name:
        return None
    hit = _lookup_ths_leaf(_ths_leaf_by_name(ths_snap or _ths_snapshot()), name)
    if not hit:
        return None
    ths_kind = str(hit.get("kind") or "").strip()
    ths_id = str(hit.get("id") or "").strip()
    if not ths_kind or not ths_id or ths_id.startswith("style:") or ths_kind in {"hot", "style"}:
        return None
    return ths_kind, ths_id


def _map_ths_cons_stocks(raw: list[Any] | None) -> list[dict[str, str]]:
    from . import style_cons  # noqa: PLC0415

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        code = style_cons._stock_code(row.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        name = str(row.get("name") or "").strip()
        if name in {"nan", "None"}:
            name = ""
        out.append({"code": code, "name": name, "market": style_cons._market_of(code)})
    return out


def fetch_style_cons(key: str) -> dict[str, Any]:
    """点开风格成分：公开源优先，名单不可用时按同花顺同名/别名补位。"""
    from . import style_cons  # noqa: PLC0415

    k = str(key or "").strip()
    out = style_cons.fetch(k)
    if style_cons.public_cons_usable(out):
        return out
    ref = _ths_ref_for_style_key(k)
    if not ref:
        return out
    ths_kind, ths_id = ref
    try:
        from ths_block.service import get_block_stocks  # noqa: PLC0415

        detail = get_block_stocks(kind=ths_kind, block_id=ths_id)
    except Exception as exc:  # noqa: BLE001
        if out.get("available"):
            return out
        reason = out.get("reason") or "没有可用的公开股票成分请求。"
        return {**out, "reason": f"{reason} 同花顺同名补位未取到：{exc}"}
    stocks = _map_ths_cons_stocks(detail.get("stocks") if isinstance(detail, dict) else None)
    if not stocks:
        if out.get("available"):
            return out
        reason = out.get("reason") or "没有可用的公开股票成分请求。"
        return {**out, "reason": f"{reason} 已匹配同花顺板块，但本地成分股为空。"}
    note_bits = [str(x) for x in (out.get("note"),) if x]
    note_bits.append("公开源名单不可用，按同花顺同名/别名板块成分补位。")
    return {
        "key": out.get("key") or k,
        "name": out.get("name") or k,
        "code": out.get("code") or "",
        "group": out.get("group") or "",
        "available": True,
        "reason": None,
        "source": "ths",
        "source_label": "同花顺板块成分（名称/别名补位）",
        "note": " ".join(note_bits),
        "count": len(stocks),
        "stocks": stocks,
    }


def style_catalog_rows() -> list[dict]:
    """只构建风格指数页签（同花顺缓存 + 风格目录），不拉开盘啦。"""
    return _build_style(ths_snap=_ths_snapshot())


def build_merged(*, ths_snap: dict[str, Any], kpl_snap: dict[str, Any]) -> dict[str, list[dict]]:
    """产出融合页签：概念/行业/地域跨源合并；自定义可匹配全部开盘啦；每日/人气/风格分列。"""
    merged: dict[str, list[dict]] = {}
    ths_kinds = ths_snap.get("kinds") or {}
    kpl_kinds = kpl_snap.get("kinds") or {}

    for key, ths_kind, kpl_kind, label in FUSED_KIND_KEYS:
        entry = ths_kinds.get(ths_kind) or {}
        ths_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        merged[key] = _build_fused_kind(
            ths_kind=ths_kind,
            kpl_kind=kpl_kind,
            kind_label=label,
            ths_rows=ths_rows,
            kpl_snap=kpl_snap,
        )

    for key, ths_kind, label in THS_ONLY_KEYS:
        entry = ths_kinds.get(ths_kind) or {}
        ths_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        if ths_kind in ("custom", "theme"):
            merged[key] = _build_ths_with_kpl_match(
                ths_kind=ths_kind,
                kind_label=label,
                ths_rows=ths_rows,
                kpl_snap=kpl_snap,
            )
        else:
            merged[key] = _build_ths_only(
                ths_kind=ths_kind,
                kind_label=label,
                ths_rows=ths_rows,
            )

    for key, kpl_kind, label in KPL_ONLY_KEYS:
        entry = kpl_kinds.get(kpl_kind) or {}
        kpl_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        if kpl_kind == "hot":
            merged[key] = _build_kpl_hot(kpl_rows=kpl_rows, ths_snap=ths_snap)
        else:
            merged[key] = []

    merged[STYLE_KIND] = _build_style(ths_snap=ths_snap)

    return merged


def snapshot(*, ensure_kpl: bool = True, force_kpl: bool = False) -> dict[str, Any]:
    """板块管理快照。"""
    if ensure_kpl:
        kpl_snap = kpl_blocks.ensure(force=force_kpl)
    else:
        kpl_snap = kpl_blocks.get_snapshot()
    ths_snap = _ths_snapshot()
    merged = build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    return {
        "updated_at": ths_snap.get("updated_at") or kpl_snap.get("updated_at"),
        "ths": ths_snap,
        "kpl": {
            "updated_at": kpl_snap.get("updated_at"),
            "fetched_date": kpl_snap.get("fetched_date"),
            "from_cache": bool(kpl_snap.get("from_cache")),
            "available": bool(kpl_snap.get("available")),
            "errors": list(kpl_snap.get("errors") or []),
            "kinds": {
                k: {
                    "kind": v.get("kind"),
                    "kind_label": v.get("kind_label"),
                    "count": v.get("count"),
                    "api_count": v.get("api_count"),
                }
                for k, v in (kpl_snap.get("kinds") or {}).items()
                if isinstance(v, dict)
            },
        },
        "merged": merged,
        "linker_unavailable": bool(ths_snap.get("linker_unavailable")),
        "linker_message": ths_snap.get("linker_message"),
        "ths_dir": ths_snap.get("ths_dir"),
        "errors": list(ths_snap.get("errors") or []) + list(kpl_snap.get("errors") or []),
    }


def refresh(*, ths_dir: str | None = None, refresh_ths: bool = True) -> dict[str, Any]:
    """手动刷新：同花顺全量（可选）+ 开盘啦强制重拉。"""
    if refresh_ths:
        try:
            from ths_block.service import refresh_cache  # noqa: PLC0415

            refresh_cache(ths_dir=ths_dir, force_theme=True)
        except Exception:  # noqa: BLE001
            pass
    return snapshot(ensure_kpl=True, force_kpl=True)


def iter_merged_rows(manage_snap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """展平融合页签中的全部行。"""
    snap = manage_snap if manage_snap is not None else snapshot(ensure_kpl=False, force_kpl=False)
    out: list[dict[str, Any]] = []
    for rows in (snap.get("merged") or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
    return out


def resolve_follow_to_kpl(
    follow: dict[str, Any],
    *,
    manage_snap: dict[str, Any] | None = None,
    fallback_index: dialect.KplNameIndex | None = None,
) -> dict[str, Any]:
    """收藏板块（同花顺 kind+id+name）→ 开盘啦 PlateID。

    优先级：
      1. 板块管理融合行：``(kind, id)`` / ``id`` / 归一名，且已有 ``kpl_code``
      2. 开盘啦全目录名称索引（``kpl_blocks``）
      3. 可选人气薄索引 / 已是 ``80xxxx`` 的直接点查
    """
    kind = str(follow.get("kind") or "").strip()
    fid = str(follow.get("id") or "").strip()
    name = str(follow.get("name") or "").strip()
    is_region = kind == "region"
    mapped = dialect.canonicalize_name(name, region=is_region)

    def _hit(row: dict[str, Any], *, via: str) -> dict[str, Any]:
        code = str(row.get("kpl_code") or row.get("code") or "").strip()
        return {
            "status": "matched",
            "lang": dialect.LANG_KPL,
            "code": code,
            "name": str(row.get("name") or name or code),
            "mapped": mapped or dialect.norm_name(str(row.get("name") or "")),
            "source_kind": kind,
            "source_id": fid,
            "via": via,
        }

    snap = manage_snap
    if snap is None:
        try:
            snap = snapshot(ensure_kpl=True, force_kpl=False)
        except Exception:  # noqa: BLE001
            snap = None

    if snap:
        by_kind_id: dict[tuple[str, str], dict[str, Any]] = {}
        by_id: dict[str, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}
        for row in iter_merged_rows(snap):
            kpl = str(row.get("kpl_code") or "").strip()
            if not kpl:
                continue
            rid = str(row.get("id") or "").strip()
            rkind = str(row.get("ths_kind") or "").strip() or str(row.get("kind") or "").strip()
            if rid:
                if rkind:
                    by_kind_id[(rkind, rid)] = row
                # 同花顺原生行优先保留
                if rid not in by_id or row.get("origin") == "ths":
                    by_id[rid] = row
            # 归一名 + 别名族均登记，便于关注项按别名命中
            is_reg = rkind == "region" or str(row.get("kpl_kind") or "") == "region"
            for nkey in _equivalence_keys(str(row.get("name") or ""), region=is_reg):
                prev = by_name.get(nkey)
                # 点查优先人气 PlateID
                if prev is None or str(row.get("kpl_kind") or "") == "hot":
                    by_name[nkey] = row

        if kind and fid and (kind, fid) in by_kind_id:
            return _hit(by_kind_id[(kind, fid)], via="block_manage:kind_id")
        if fid and fid in by_id:
            return _hit(by_id[fid], via="block_manage:id")
        for nkey in _equivalence_keys(name, region=is_region):
            if nkey in by_name:
                return _hit(by_name[nkey], via="block_manage:name")

    # 开盘啦全目录
    try:
        kpl_idx = kpl_blocks.build_name_index()
    except Exception:  # noqa: BLE001
        kpl_idx = dialect.build_kpl_index()
    if fallback_index is not None:
        # 薄索引补全未覆盖名称；不覆盖全目录已有项
        for code, row in fallback_index.by_code.items():
            if code not in kpl_idx.by_code:
                kpl_idx.add(code, str(row.get("name") or ""), **{
                    k: v for k, v in row.items() if k not in ("code", "name")
                })

    hit = dialect.resolve_to_kpl(name=name, code=fid, kind=kind, index=kpl_idx)
    if hit.get("status") == "matched":
        hit = dict(hit)
        hit["via"] = hit.get("via") or "kpl_catalog"
        return hit
    return hit
