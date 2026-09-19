"""Inspect raw responses for index constituent APIs."""
from __future__ import annotations

import json
import time

from duanxian import fetchers

HEADERS = {
    **fetchers.HEADERS,
    "Referer": "https://quote.eastmoney.com/",
}
UT = "fa5fd1943c7b386f172d6893dbfba10b"


def show(label, url, params=None, timeout=10):
    print(f"\n=== {label} ===", flush=True)
    try:
        r = fetchers._direct_get(url, params=params or {}, headers=HEADERS, timeout=timeout)
        print("status", r.status_code, "len", len(r.content), flush=True)
        text = r.text[:500]
        try:
            j = r.json()
            print("json keys", list(j.keys())[:12], flush=True)
            print(json.dumps(j, ensure_ascii=False)[:700], flush=True)
        except Exception:
            print("text", text, flush=True)
    except Exception as e:  # noqa: BLE001
        print("ERR", type(e).__name__, e, flush=True)


def main():
    ts = int(time.time() * 1000)
    # slist with ut (efinance style)
    show(
        "slist ut 1.000300",
        "https://push2.eastmoney.com/api/qt/slist/get",
        {
            "spt": 1, "fltt": 2, "invt": 2, "np": 3,
            "ut": UT, "fid": "f3", "pn": 1, "pz": 5, "po": 1,
            "fields": "f12,f13,f14,f3",
            "secid": "1.000300",
            "wbp2u": "|0|0|0|web",
            "_": ts,
        },
    )
    show(
        "slist delay ut 1.000300",
        "https://push2delay.eastmoney.com/api/qt/slist/get",
        {
            "spt": 1, "fltt": 2, "invt": 2, "np": 3,
            "ut": UT, "fid": "f3", "pn": 1, "pz": 5, "po": 1,
            "fields": "f12,f13,f14,f3",
            "secid": "1.000300",
            "_": ts,
        },
    )
    show(
        "clist b:1.000300 push2",
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "ut": UT, "fid": "f3", "fs": "b:1.000300",
            "fields": "f12,f14,f3", "_": ts,
        },
    )
    show(
        "datacenter 000300",
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        {
            "sortColumns": "SECURITY_CODE",
            "sortTypes": 1,
            "pageSize": 5,
            "pageNumber": 1,
            "reportName": "RPT_INDEX_TS_COMPONENT",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,WEIGHT,INDEX_CODE",
            "filter": '(INDEX_CODE="000300")',
            "source": "WEB",
            "client": "WEB",
        },
    )
    show(
        "csindex top10 000300",
        "https://www.csindex.com.cn/csindex-home/index/weight/top10/000300",
    )
    show(
        "csindex cons 000300",
        "https://www.csindex.com.cn/csindex-home/indexInfo/index-cons",
        {"indexCode": "000300"},
    )
    show(
        "sina 000300 html",
        "https://vip.stock.finance.sina.com.cn/corp/go.php/vII_NewestComponent/indexid/000300.phtml",
    )
    show(
        "cnindex sample 399303",
        "https://www.cnindex.com.cn/sample-detail/detail",
        {"indexcode": "399303", "pageNum": 1, "pageSize": 5},
    )
    show(
        "hsi slist ut",
        "https://push2.eastmoney.com/api/qt/slist/get",
        {
            "spt": 1, "fltt": 2, "invt": 2, "np": 3,
            "ut": UT, "fid": "f3", "pn": 1, "pz": 5, "po": 1,
            "fields": "f12,f13,f14,f3",
            "secid": "100.HSI",
            "_": ts,
        },
    )


if __name__ == "__main__":
    main()
