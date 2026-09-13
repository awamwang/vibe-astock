"""探测 PCB 相关板块的涨停数字段来源。"""
import requests

UA = {
    "User-Agent": "lhb/5.13.7 (com.kaipanla.www; build:0; iOS 16.1.0) Alamofire/4.9.1",
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}
HQ = "https://apphq.longhuvip.com/w1/api/index.php"
HIS = "https://apphis.longhuvip.com/w1/api/index.php"


def get(url, **params):
    r = requests.get(url, params=params, headers=UA, timeout=15)
    r.raise_for_status()
    return r.json()


def post(url, data):
    r = requests.post(url, data=data, headers=UA, timeout=15)
    r.raise_for_status()
    return r.json()


# 1) 人气/概念榜里找 PCB
print("=== RealRankingInfo search PCB ===")
for zs in (7, 5):
    for idx in range(0, 300, 30):
        raw = get(
            HQ,
            Order=1,
            a="RealRankingInfo",
            st=30,
            apiv="w25",
            Type=1,
            c="ZhiShuRanking",
            PhoneOSNew=1,
            Index=idx,
            ZSType=zs,
        )
        lst = raw.get("list") or []
        if not lst:
            break
        for it in lst:
            name = str(it[1])
            if "PCB" in name.upper() or "电路板" in name:
                print(f"ZS={zs}", it[:8])

# 2) PlateAnalysis Type=2 全量里找 PCB
print("\n=== PlateAnalysis Type=2 sample / PCB ===")
raw = get(
    HQ,
    Order=1,
    a="PlateAnalysis",
    st=300,
    c="HomeDingPan",
    PhoneOSNew=1,
    Index=0,
    PidType=0,
    apiv="w25",
    Type=2,
)
lst = raw.get("list") or []
print("n=", len(lst), "keys=", list(raw.keys())[:8])
if lst:
    print("row0=", lst[0])
pcb_rows = [x for x in lst if isinstance(x, list) and len(x) > 1 and ("PCB" in str(x[1]).upper() or "电路板" in str(x[1]))]
print("pcb in plateanalysis:", pcb_rows[:5])
# also show top by field2
top = sorted(
    [x for x in lst if isinstance(x, list) and len(x) > 2],
    key=lambda x: float(x[2] or 0),
    reverse=True,
)[:8]
print("top by [2]:")
for x in top:
    print(x[:6])

# 3) 若有 PCB code，点查 GetPlate_Info_QJ
codes = set()
for it in pcb_rows:
    codes.add(str(it[0]))
# from ranking search we may have printed codes; try common
print("\n=== GetPlate_Info_QJ for found codes ===", codes)
for code in list(codes)[:5]:
    for host, dated, extra in (
        (HQ, False, {}),
        (HIS, True, {"Date": "2026-09-12"}),
    ):
        try:
            if dated:
                j = post(HIS, {
                    "a": "GetPlate_Info_QJ",
                    "c": "ZhiShuRanking",
                    "PlateID": code,
                    "Date": extra["Date"],
                    "apiv": "w25",
                    "PhoneOSNew": "1",
                })
            else:
                j = get(HQ, a="GetPlate_Info_QJ", c="ZhiShuRanking", PlateID=code, apiv="w25", PhoneOSNew=1)
            print(host[8:20], "code", code, "List=", j.get("List"), "Date=", j.get("Date"))
        except Exception as e:
            print("fail", code, e)
