"""Probe index constituent APIs for style indices that failed clist b:CODE."""
from __future__ import annotations

import json
import time

from duanxian import fetchers
from duanxian.style_indices import ITEMS

HEADERS = fetchers.HEADERS
FAIL_CODES = {
    "399303", "399370", "399371", "931186", "000932", "000922", "000015",
    "000001", "399001", "399006", "000300", "000688", "899050", "000985",
    "000905", "000852", "000993", "931087", "HSI", "KS11", "CN00Y",
}

HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
)


def get_json(url, params, timeout=8):
    try:
        r = fetchers._direct_get(url, params=params, headers=HEADERS, timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:  # noqa: BLE001
        return None, {"_err": f"{type(e).__name__}: {e}"[:160]}


def peek_diff(data):
    if not isinstance(data, dict):
        return None, []
    inner = data.get("data") or {}
    if not isinstance(inner, dict):
        return None, []
    diff = inner.get("diff") or inner.get("slist") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    names = []
    for x in diff[:3]:
        if isinstance(x, dict):
            names.append(str(x.get("f14") or x.get("SECURITY_NAME_ABBR") or x.get("name") or ""))
    total = inner.get("total")
    if total is None:
        total = len(diff) if diff else None
    return total, names


def try_slist(secid: str):
    params = {
        "spt": 1, "np": 3, "fltt": 2, "invt": 2,
        "fields": "f12,f13,f14,f3",
        "secid": secid, "pn": 1, "pz": 5, "po": 1,
        "_": int(time.time() * 1000),
    }
    for host in HOSTS:
        code, j = get_json(host + "/api/qt/slist/get", params)
        total, names = peek_diff(j)
        if total:
            return {"via": f"slist {host.split('//')[1].split('.')[0]} {secid}", "total": total, "names": names}
    return None


def try_clist_i(secid: str):
    params = {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": f"i:{secid}", "fields": "f12,f14,f3",
        "_": int(time.time() * 1000),
    }
    for host in HOSTS:
        code, j = get_json(host + "/api/qt/clist/get", params)
        total, names = peek_diff(j)
        if total:
            return {"via": f"clist i:{secid}", "total": total, "names": names}
    return None


def try_datacenter(code: str):
    params = {
        "sortColumns": "SECURITY_CODE",
        "sortTypes": 1,
        "pageSize": 5,
        "pageNumber": 1,
        "reportName": "RPT_INDEX_TS_COMPONENT",
        "columns": "ALL",
        "filter": f'(INDEX_CODE="{code}")',
        "source": "WEB",
        "client": "WEB",
    }
    status, j = get_json("https://datacenter-web.eastmoney.com/api/data/v1/get", params)
    result = (j or {}).get("result") if isinstance(j, dict) else None
    if isinstance(result, dict) and (result.get("count") or result.get("data")):
        rows = result.get("data") or []
        names = [str(x.get("SECURITY_NAME_ABBR") or "") for x in rows[:3] if isinstance(x, dict)]
        return {"via": "datacenter", "total": result.get("count"), "names": names, "success": j.get("success"), "message": j.get("message")}
    return {"via": "datacenter", "status": status, "success": (j or {}).get("success"), "message": (j or {}).get("message"), "keys": list((j or {}).keys())[:8]}


def try_csindex(code: str):
    status, j = get_json(f"https://www.csindex.com.cn/csindex-home/index/weight/top10/{code}", {}, timeout=10)
    if isinstance(j, dict):
        data = j.get("data")
        if isinstance(data, list) and data:
            names = [str(x.get("securityShortName") or x.get("constituentName") or "") for x in data[:3]]
            return {"via": "csindex top10", "total": len(data), "names": names}
        return {"via": "csindex", "status": status, "keys": list(j.keys())[:8], "msg": str(j)[:180]}
    return {"via": "csindex", "raw": str(j)[:180]}


def try_csindex_export(code: str):
    # cons list JSON
    params = {"indexCode": code}
    status, j = get_json(
        "https://www.csindex.com.cn/csindex-home/index/weight/export/cons",
        params,
        timeout=10,
    )
    if isinstance(j, dict):
        return {"via": "csindex export", "status": status, "keys": list(j.keys())[:8], "snip": str(j)[:180]}
    return {"via": "csindex export", "status": status, "snip": str(j)[:180]}


def try_cnindex(code: str):
    params = {"indexcode": code, "pageNum": 1, "pageSize": 5}
    status, j = get_json("https://www.cnindex.com.cn/sample-detail/detail", params, timeout=10)
    if not isinstance(j, dict):
        # alternate
        status2, j2 = get_json(
            "https://www.cnindex.com.cn/index/weightList",
            {"indexCode": code, "pageNum": 1, "pageSize": 5},
            timeout=10,
        )
        return {"via": "cnindex", "status": status, "alt_status": status2, "snip": str(j)[:120], "alt": str(j2)[:180]}
    data = j.get("data") or j.get("list") or {}
    return {"via": "cnindex sample-detail", "status": status, "keys": list(j.keys())[:10], "snip": str(j)[:220]}


def main():
    items = [it for it in ITEMS if it.code in FAIL_CODES]
    for it in items:
        print(f"\n## {it.key} {it.name} {it.code} secids={it.secids}", flush=True)
        hit = None
        for sid in it.secids:
            hit = try_slist(sid)
            if hit:
                print("  HIT", hit, flush=True)
                break
            print(f"  slist miss {sid}", flush=True)
        if hit:
            continue
        for sid in it.secids:
            hit = try_clist_i(sid)
            if hit:
                print("  HIT", hit, flush=True)
                break
        if hit:
            continue
        print("  ", try_datacenter(it.code), flush=True)
        if it.code.isdigit() or (it.code.startswith("93") and it.code.isdigit()):
            print("  ", try_csindex(it.code), flush=True)
        if it.code.startswith("399") or it.code in {"399303", "399370", "399371", "399001", "399006"}:
            print("  ", try_cnindex(it.code), flush=True)


if __name__ == "__main__":
    main()
