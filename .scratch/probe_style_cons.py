"""Probe East Money constituent availability for style indices. One-shot, not imported."""
from __future__ import annotations

import json
import sys
import time

from duanxian import fetchers
from duanxian.style_indices import ITEMS

DELAY = "https://push2delay.eastmoney.com/api/qt/clist/get"
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = fetchers.HEADERS


def clist_peek(fs: str):
    params = {
        "pn": 1,
        "pz": 3,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": fs,
        "fields": "f12,f14,f3",
        "_": int(time.time() * 1000),
    }
    try:
        r = fetchers._direct_get(DELAY, params=params, headers=HEADERS, timeout=8)
        data = (r.json() or {}).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        names = [str(x.get("f14") or "") for x in diff[:3]]
        return {"ok": bool(data.get("total")), "total": data.get("total"), "names": names}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {e}"[:120]}


def datacenter_peek(code: str):
    params = {
        "sortColumns": "SECURITY_CODE",
        "sortTypes": 1,
        "pageSize": 3,
        "pageNumber": 1,
        "reportName": "RPT_INDEX_TS_COMPONENT",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,WEIGHT",
        "filter": f'(INDEX_CODE="{code}")',
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = fetchers._direct_get(DC, params=params, headers=HEADERS, timeout=8)
        j = r.json() or {}
        result = j.get("result") or {}
        rows = result.get("data") or []
        names = [str(x.get("SECURITY_NAME_ABBR") or "") for x in rows[:3]]
        count = result.get("count")
        return {"ok": bool(count), "total": count, "names": names}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {e}"[:120]}


def main() -> int:
    rows = []
    for it in ITEMS:
        rec = {
            "key": it.key,
            "name": it.name,
            "group": it.group,
            "code": it.code,
        }
        if it.code.startswith("BK"):
            hit = clist_peek(f"b:{it.code}")
            rec["via"] = f"clist b:{it.code}"
            rec.update(hit)
        else:
            hit = None
            for sid in it.secids:
                cand = clist_peek(f"b:{sid}")
                rec[f"clist_b:{sid}"] = cand
                if cand.get("ok"):
                    hit = cand
                    rec["via"] = f"clist b:{sid}"
                    break
            if hit is None:
                dc = datacenter_peek(it.code)
                rec["datacenter"] = dc
                if dc.get("ok"):
                    hit = dc
                    rec["via"] = "datacenter"
            if hit is None:
                rec["ok"] = False
            else:
                rec["ok"] = True
                rec["total"] = hit.get("total")
                rec["names"] = hit.get("names")
        rows.append(rec)
        flag = "OK" if rec.get("ok") else "NO"
        extra = rec.get("total") or rec.get("err") or rec.get("datacenter")
        print(f"{flag:3} {it.group:13} {it.key:14} {it.name:16} {it.code:10} {extra}", flush=True)

    fails = [r for r in rows if not r.get("ok")]
    print("\n=== FAIL ===", flush=True)
    for r in fails:
        print(json.dumps(r, ensure_ascii=False), flush=True)
    print(f"\nfail={len(fails)} ok={len(rows)-len(fails)} total={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
