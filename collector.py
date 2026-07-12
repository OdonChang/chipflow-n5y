#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChipFlow N5Y Collector v2 — 主動式ETF共識自動收集器(逐投信端點版)
================================================================
架構說明(讀我!):
證交所本身不提供PCF中央API,PCF依法規定由各投信自行公布,分散在各投信網站。
本版本改為「逐投信端點」架構:ISSUERS字典裡每一家投信一組抓取設定,
逐一呼叫、統一解析成相同的內部格式後再聚合。

目前已確認可用的投信:
- 統一投信(ezmoney.com.tw):POST /ETF/Transaction/GetPCF, body={fundCode, date, specificDate}
  已知基金對照: 00981A→49YTW, 00403A→63YTW, 00988A→61YTW

擴充新投信時,在 ISSUERS 字典新增一組設定即可,不需更動聚合/比對邏輯。
新增方式:比照README「如何新增一家投信」章節操作。
"""
import json, re, sys, hashlib, urllib.request, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SNAP_DIR = DATA_DIR / "snapshots"
TZ = ZoneInfo("Asia/Taipei")

class _RedirectHandlerPOST(urllib.request.HTTPRedirectHandler):
    """urllib預設不會讓307/308保留POST方法與body去跟隨重導向(視為安全防呆)。
       但ezmoney.com.tw實際會用307導向同一個POST端點的另一節點(常見於負載平衡/CDN),
       這裡明確允許POST帶body跟隨307/308,其餘301/302仍走預設(轉GET)行為。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code in (307, 308) and req.get_method() == "POST":
            new_req = urllib.request.Request(
                newurl, data=req.data, headers=req.headers,
                method="POST")
            return new_req
        return super().redirect_request(req, fp, code, msg, headers, newurl)

_opener = urllib.request.build_opener(_RedirectHandlerPOST)

def http_post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Origin": "https://www.ezmoney.com.tw",
        "Referer": "https://www.ezmoney.com.tw/ETF/Transaction/PCF",
    })
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def roc_date(dt):
    """西元轉民國年格式 115/07/12"""
    return f"{dt.year-1911}/{dt.month:02d}/{dt.day:02d}"

# ═══════════════════════════════════════════════════════════
# 投信端點設定表——新增投信時只需在此加一組
# ═══════════════════════════════════════════════════════════
def fetch_ezmoney(fund_internal_code, dt):
    """統一投信(ezmoney.com.tw)抓取邏輯"""
    url = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
    payload = {"fundCode": fund_internal_code, "date": roc_date(dt), "specificDate": False}
    raw = http_post_json(url, payload)
    fund_info = raw.get("fund", {})
    stock_no = (fund_info.get("sStockNo") or "").strip()
    stock_name = (fund_info.get("sStockName") or fund_info.get("sFundShortName") or "").strip()
    holdings = {}
    for asset in raw.get("asset", []):
        if asset.get("AssetCode") != "ST":  # 只取股票,忽略期貨(GD)等其他資產類別
            continue
        for d in (asset.get("Details") or []):
            code = str(d.get("DetailCode", "")).strip()
            if not re.match(r"^\d{4,5}$", code):  # 只保留純數字台股代號,過濾海外股票(如"AMD US")
                continue
            share = d.get("Share")
            if share is None:
                continue
            holdings[code] = holdings.get(code, 0) + int(share)
    return {
        "stockNo": stock_no,
        "stockName": stock_name,
        "holdings": holdings,
    }

ISSUERS = {
    "統一投信": {
        "fetcher": fetch_ezmoney,
        "funds": ["49YTW", "63YTW", "61YTW"],  # 00981A / 00403A / 00988A
    },
    # ── 新增投信範例(尚未驗證,待逐一確認端點後解除註解) ──
    # "復華投信": {"fetcher": fetch_XXX, "funds": [...]},
    # "群益投信": {"fetcher": fetch_XXX, "funds": [...]},
}

def fetch_all_today():
    """呼叫所有已設定投信的所有基金,回傳 {stockNo: {name, holdings}}"""
    today_etfs = {}
    now = datetime.now(TZ)
    errors = []
    for issuer_name, cfg in ISSUERS.items():
        fetcher = cfg["fetcher"]
        for fund_code in cfg["funds"]:
            try:
                result = fetcher(fund_code, now)
                sn = result["stockNo"]
                if not sn:
                    errors.append(f"{issuer_name}/{fund_code}: 回傳無股票代號,可能格式變動")
                    continue
                today_etfs[sn] = {"name": result["stockName"], "holdings": result["holdings"]}
                print(f"[fetch] {issuer_name} {sn}({fund_code}) 持股{len(result['holdings'])}檔")
            except urllib.error.HTTPError as e:
                errors.append(f"{issuer_name}/{fund_code}: HTTP {e.code}")
            except Exception as e:
                errors.append(f"{issuer_name}/{fund_code}: {type(e).__name__} {e}")
    if errors:
        print("[fetch] 以下項目抓取失敗(不中斷,略過繼續):")
        for e in errors: print(f"  ⚠️ {e}")
    return today_etfs

def load_prev_snapshot(today_str):
    snaps = sorted(SNAP_DIR.glob("*.json"), reverse=True)
    for p in snaps:
        if p.stem < today_str:
            return json.loads(p.read_text(encoding="utf-8")), p.stem
    return None, None

def aggregate(today_etfs, prev_etfs):
    stocks = {}
    stock_names = {}
    for sn, e in today_etfs.items():
        prev_h = (prev_etfs.get(sn) or {}).get("holdings", {}) if prev_etfs else {}
        cur_h = e["holdings"]
        stock_names_for_this_etf = {}
        all_codes = set(cur_h) | set(prev_h)
        for sc in all_codes:
            delta = cur_h.get(sc, 0) - prev_h.get(sc, 0)
            if delta == 0:
                continue
            s = stocks.setdefault(sc, {"buy": [], "sell": [], "newEntry": [], "exit": []})
            if delta > 0:
                s["buy"].append({"etf": sn, "shares": delta})
                if sc not in prev_h: s["newEntry"].append(sn)
            else:
                s["sell"].append({"etf": sn, "shares": delta})
                if sc not in cur_h or cur_h.get(sc, 0) == 0: s["exit"].append(sn)
    records = []
    for sc, s in stocks.items():
        nb, ns = len(s["buy"]), len(s["sell"])
        dominant = "buy" if nb >= ns else "sell"
        cnt = max(nb, ns)
        net_shares = sum(x["shares"] for x in s["buy"]) + sum(x["shares"] for x in s["sell"])
        tier = "strong" if cnt >= 3 else "weak" if cnt == 2 else "single"
        divergent = (nb >= 2 and ns >= 2)
        records.append({
            "code": sc, "name": stock_names.get(sc, sc),
            "direction": dominant, "consensusEtfCount": cnt,
            "buyCount": nb, "sellCount": ns,
            "netShares": net_shares,
            "newEntries": len(s["newEntry"]), "exits": len(s["exit"]),
            "tier": tier, "divergent": divergent,
        })
    records.sort(key=lambda r: (-r["consensusEtfCount"], -abs(r["netShares"])))
    return records

def compute_streaks(records, history):
    hist_by_date = {h["date"]: {r["code"]: r for r in h["records"]} for h in history}
    dates = sorted(hist_by_date.keys(), reverse=True)
    for r in records:
        streak = 1
        for d in dates:
            prev = hist_by_date[d].get(r["code"])
            if prev and prev.get("direction") == r["direction"] and prev.get("consensusEtfCount", 0) >= 2:
                streak += 1
            else:
                break
        r["streak"] = streak if r["consensusEtfCount"] >= 2 else 0
    return records

def main():
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")
    print(f"=== ChipFlow N5Y Collector v2 {today_str} {now.strftime('%H:%M')} 台北時間 ===")
    print(f"[config] 已設定投信: {list(ISSUERS.keys())}, 共{sum(len(c['funds']) for c in ISSUERS.values())}檔基金")

    today_etfs = fetch_all_today()
    if not today_etfs:
        sys.exit("❌ 全部投信抓取失敗,請檢查端點是否變動(見上方[fetch]錯誤訊息)")

    content_hash = hashlib.md5(json.dumps(today_etfs, sort_keys=True).encode()).hexdigest()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(SNAP_DIR.glob("*.json"), reverse=True)[:1]:
        prev_data = json.loads(p.read_text(encoding="utf-8"))
        if hashlib.md5(json.dumps(prev_data, sort_keys=True).encode()).hexdigest() == content_hash:
            print("[dedup] 內容與最近快照相同(假日/未更新),跳過本次")
            return

    snap_path = SNAP_DIR / f"{today_str}.json"
    snap_path.write_text(json.dumps(today_etfs, ensure_ascii=False), encoding="utf-8")
    print(f"[snapshot] 已存 {snap_path.name}(涵蓋{len(today_etfs)}檔ETF)")

    prev_etfs, prev_date = load_prev_snapshot(today_str)
    if prev_etfs is None:
        print("[aggregate] 首次執行,無前日快照可比對,今日僅建立基準")
        latest = {"updated": today_str, "note": "首日基準,明日起產生異動訊號", "records": [], "issuersActive": list(ISSUERS.keys())}
    else:
        print(f"[aggregate] 與 {prev_date} 快照比對")
        hist_path = DATA_DIR / "n5y_history.json"
        history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
        records = aggregate(today_etfs, prev_etfs)
        records = compute_streaks(records, history)
        latest = {"updated": today_str, "comparedWith": prev_date, "etfCount": len(today_etfs),
                  "issuersActive": list(ISSUERS.keys()), "records": records}
        history.append({"date": today_str, "records": [
            {k: r[k] for k in ("code","name","direction","consensusEtfCount","netShares","tier")}
            for r in records if r["consensusEtfCount"] >= 2]})
        history = history[-90:]
        hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        strong = [r for r in records if r["tier"] == "strong"]
        print(f"[result] 異動{len(records)}檔 | 強共識{len(strong)}檔: " +
              ", ".join(f"{r['code']}({r['direction']}x{r['consensusEtfCount']})" for r in strong[:8]))

    (DATA_DIR / "n5y_latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[done] n5y_latest.json 已更新")
    print(f"[note] 目前僅涵蓋統一投信{len(ISSUERS['統一投信']['funds'])}檔,",
          "尚未涵蓋其他投信(復華/群益/野村等),共識強度會被低估,詳見README擴充計畫")

if __name__ == "__main__":
    main()
