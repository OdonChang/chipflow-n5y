#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端測試:模擬兩個交易日的PCF資料,驗證所有聚合邏輯"""
import json, sys, shutil
from pathlib import Path
from unittest import mock

import collector

# ═══ 合成PCF資料:模擬證交所回傳格式(用FIELD_ALIASES裡的欄位名之一) ═══
def make_raw(day_holdings):
    """day_holdings: {etf_code: {stock_code: (name, shares)}}"""
    rows = []
    for ec, stocks in day_holdings.items():
        for sc, (name, sh) in stocks.items():
            rows.append({"基金代號": ec, "基金名稱": f"測試{ec}", 
                        "成分股代號": sc, "成分股名稱": name, "股數": str(sh)})
    # 加入被動ETF雜訊(應被過濾)
    rows.append({"基金代號": "0050", "基金名稱": "台灣50", "成分股代號": "2330", "成分股名稱": "台積電", "股數": "999999"})
    return rows

DAY1 = {
    "00981A": {"2330": ("台積電", 5000), "2383": ("台光電", 3000), "6415": ("矽力-KY", 2000), "2454": ("聯發科", 1000)},
    "00991A": {"2330": ("台積電", 4000), "2383": ("台光電", 2500), "3037": ("欣興", 1500)},
    "00403A": {"2330": ("台積電", 3000), "2383": ("台光電", 1000), "4958": ("臻鼎-KY", 800)},
    "00992A": {"2383": ("台光電", 500),  "4958": ("臻鼎-KY", 600)},
}
DAY2 = {
    # 台光電: 4檔全加碼 → strong buy x4
    # 台積電: 2檔加碼(00981A,00991A) 1檔減碼(00403A) → buy x2 weak, 非divergent(sell僅1)
    # 矽力: 00981A清倉 → exit
    # 欣興: 00991A減碼 → single sell
    # 臻鼎: 2檔減碼 → weak sell
    # 川湖: 00981A新建倉 → newEntry
    # 聯發科: 不變 → 不應出現在records
    "00981A": {"2330": ("台積電", 5500), "2383": ("台光電", 3300), "2454": ("聯發科", 1000), "2059": ("川湖", 400)},
    "00991A": {"2330": ("台積電", 4200), "2383": ("台光電", 2800), "3037": ("欣興", 1200)},
    "00403A": {"2330": ("台積電", 2500), "2383": ("台光電", 1200), "4958": ("臻鼎-KY", 500)},
    "00992A": {"2383": ("台光電", 700),  "4958": ("臻鼎-KY", 400)},
}

def run_day(raw_data, fake_date):
    with mock.patch.object(collector, "discover_endpoint", return_value=("/mock", raw_data)), \
         mock.patch.object(collector, "datetime") as mdt:
        from datetime import datetime as real_dt
        mdt.now.return_value = real_dt.fromisoformat(fake_date + "T18:00:00+08:00")
        collector.main()

# 清空測試環境
shutil.rmtree(collector.DATA_DIR, ignore_errors=True)
collector.SNAP_DIR.mkdir(parents=True, exist_ok=True)

print("═══ Day1: 首次執行(建基準) ═══")
run_day(make_raw(DAY1), "2026-07-13")
latest = json.loads((collector.DATA_DIR/"n5y_latest.json").read_text(encoding="utf-8"))
assert latest["records"] == [], "首日應無異動records"
assert (collector.SNAP_DIR/"2026-07-13.json").exists()
print("✅ 首日建基準正確\n")

print("═══ Day2: 產生異動訊號 ═══")
run_day(make_raw(DAY2), "2026-07-14")
latest = json.loads((collector.DATA_DIR/"n5y_latest.json").read_text(encoding="utf-8"))
recs = {r["code"]: r for r in latest["records"]}

checks = [
    ("台光電4檔strong buy", recs["2383"]["tier"]=="strong" and recs["2383"]["consensusEtfCount"]==4 and recs["2383"]["direction"]=="buy"),
    ("台積電weak(2買1賣)", recs["2330"]["tier"]=="weak" and recs["2330"]["buyCount"]==2 and recs["2330"]["sellCount"]==1),
    ("台積電非divergent", recs["2330"]["divergent"]==False),
    ("矽力清倉偵測", recs["6415"]["exits"]==1 and recs["6415"]["direction"]=="sell"),
    ("川湖建倉偵測", recs["2059"]["newEntries"]==1 and recs["2059"]["tier"]=="single"),
    ("臻鼎weak sell x2", recs["4958"]["tier"]=="weak" and recs["4958"]["sellCount"]==2),
    ("欣興single sell", recs["3037"]["tier"]=="single"),
    ("聯發科無變動不出現", "2454" not in recs),
    ("排序:台光電第一", latest["records"][0]["code"]=="2383"),
    ("台光電streak=1(首個訊號日)", recs["2383"]["streak"]==1),
]
allpass = True
for name, ok in checks:
    print(("✅" if ok else "❌"), name)
    if not ok: allpass = False

print("\n═══ Day3: 驗證streak連續計算 ═══")
DAY3 = json.loads(json.dumps(DAY2).replace('"股數"','"股數"'))  # deep copy via json
DAY3_h = {ec: {sc: (n, s+100 if sc=="2383" else s) for sc,(n,s) in stocks.items()} for ec, stocks in DAY2.items()}
run_day(make_raw(DAY3_h), "2026-07-15")
latest3 = json.loads((collector.DATA_DIR/"n5y_latest.json").read_text(encoding="utf-8"))
recs3 = {r["code"]: r for r in latest3["records"]}
ok = recs3["2383"]["streak"]==2 and recs3["2383"]["consensusEtfCount"]==4
print(("✅" if ok else "❌"), f"台光電連續2日strong buy, streak={recs3['2383']['streak']}")
if not ok: allpass = False

print("\n═══ Day4: 假日防重(內容相同不重複存) ═══")
run_day(make_raw(DAY3_h), "2026-07-16")
snaps = sorted(collector.SNAP_DIR.glob("*.json"))
ok = len(snaps)==3  # 13,14,15 — 16因內容相同被dedup
print(("✅" if ok else "❌"), f"快照數={len(snaps)}(應為3,07-16被防重跳過)")
if not ok: allpass = False

hist = json.loads((collector.DATA_DIR/"n5y_history.json").read_text(encoding="utf-8"))
print(f"\n歷史檔累積: {len(hist)}個交易日的共識紀錄")
print("\n" + ("🎉 全部測試通過" if allpass else "💥 有測試失敗") )
sys.exit(0 if allpass else 1)
