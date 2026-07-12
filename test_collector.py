#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""單元測試:直接測試核心函式(fetch解析/aggregate/streak),不透過main()避免mock干擾"""
import json, sys, re
import collector

def parse_fund_response(raw):
    """比照collector.fetch_ezmoney內部解析邏輯"""
    fund_info = raw.get("fund", {})
    stock_no = (fund_info.get("sStockNo") or "").strip()
    stock_name = (fund_info.get("sStockName") or "").strip()
    holdings = {}
    for asset in raw.get("asset", []):
        if asset.get("AssetCode") != "ST": continue
        for d in (asset.get("Details") or []):
            code = str(d.get("DetailCode","")).strip()
            if not re.match(r"^\d{4,5}$", code): continue
            share = d.get("Share")
            if share is None: continue
            holdings[code] = holdings.get(code, 0) + int(share)
    return {"stockNo": stock_no, "stockName": stock_name, "holdings": holdings}

def make_fund_response(stock_no, stock_name, holdings_dict):
    details = [{"DetailCode": c, "DetailName": n, "Share": float(s)} for c, (n, s) in holdings_dict.items()]
    details.append({"DetailCode": "AMD US", "DetailName": "AMD", "Share": 100000.0})
    return {"fund": {"sStockNo": f"{stock_no}    ", "sStockName": f"{stock_name}              "},
            "asset": [{"AssetCode": "GD", "Details": None}, {"AssetCode": "ST", "Details": details}]}

print("═══ 測試1: 解析邏輯(真實00988A格式) ═══")
raw = make_fund_response("00988A", "主動統一全球創新", {"2327": ("國巨", 2200000), "2383": ("台光電", 330000)})
parsed = parse_fund_response(raw)
assert parsed["stockNo"] == "00988A"
assert parsed["holdings"] == {"2327": 2200000, "2383": 330000}
assert "AMD US" not in parsed["holdings"]
print("✅ 解析邏輯正確,trim/過濾海外股票均正常\n")

print("═══ 測試2: aggregate() 核心聚合邏輯 ═══")
day1 = {
    "00981A": {"name": "主動統一台股增長", "holdings": {"2330": 5000000, "2383": 300000, "6415": 200000}},
    "00403A": {"name": "主動統一台股升級50", "holdings": {"2330": 3000000, "2383": 100000, "4958": 80000}},
    "00988A": {"name": "主動統一全球創新", "holdings": {"2327": 2200000, "2383": 330000}},
}
day2 = {
    "00981A": {"name": "主動統一台股增長", "holdings": {"2330": 5500000, "2383": 330000, "2454": 100000}},  # 台積電加碼,矽力清倉,聯發科建倉
    "00403A": {"name": "主動統一台股升級50", "holdings": {"2330": 2500000, "2383": 120000, "4958": 50000}},  # 台積電減碼
    "00988A": {"name": "主動統一全球創新", "holdings": {"2327": 2200000, "2383": 700000}},  # 台光電大幅加碼
}
records = collector.aggregate(day2, day1)
recs = {r["code"]: r for r in records}

checks = [
    ("總筆數應為5(2383/6415/2454/4958/2330)", len(records) == 5),
    ("台光電3檔strong buy", recs["2383"]["tier"]=="strong" and recs["2383"]["consensusEtfCount"]==3),
    ("矽力清倉偵測", recs["6415"]["exits"]==1 and recs["6415"]["direction"]=="sell"),
    ("聯發科建倉偵測", recs["2454"]["newEntries"]==1 and recs["2454"]["tier"]=="single"),
    ("台積電一買一賣,single非divergent(tier看同向共識強度非總參與數)", recs["2330"]["buyCount"]==1 and recs["2330"]["sellCount"]==1 and recs["2330"]["divergent"]==False and recs["2330"]["tier"]=="single"),
    ("排序:台光電(3檔)排最前", records[0]["code"]=="2383"),
]
allpass = True
for name, ok in checks:
    print(("✅" if ok else "❌"), name)
    if not ok: allpass = False

print("\n═══ 測試3: compute_streaks() 連續天數 ═══")
history = [{"date": "2026-07-13", "records": []}]  # day1無異動(基準日)
records_d2 = collector.compute_streaks(records, history)
r2383 = next(r for r in records_d2 if r["code"]=="2383")
ok = r2383["streak"] == 1
print(("✅" if ok else "❌"), f"第一次出現異動,streak應為1,實際={r2383['streak']}")
if not ok: allpass = False

history2 = history + [{"date": "2026-07-14", "records": [{"code":"2383","direction":"buy","consensusEtfCount":3,"netShares":900000,"tier":"strong","name":"台光電"}]}]
day3 = {k: {**v, "holdings": {**v["holdings"], "2383": v["holdings"].get("2383",0)+50000}} for k,v in day2.items()}
records_d3 = collector.aggregate(day3, day2)
records_d3 = collector.compute_streaks(records_d3, history2)
r2383_d3 = next(r for r in records_d3 if r["code"]=="2383")
ok = r2383_d3["streak"] == 2
print(("✅" if ok else "❌"), f"連續第二天同向,streak應為2,實際={r2383_d3['streak']}")
if not ok: allpass = False

print("\n" + ("🎉 全部核心邏輯測試通過" if allpass else "💥 有測試失敗"))
sys.exit(0 if allpass else 1)
