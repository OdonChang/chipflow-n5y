#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChipFlow N5Y Collector — 主動式ETF共識自動收集器
================================================
每個交易日自動執行:
1. 從證交所 TWSE OpenAPI 抓取 ETF 每日申購買回清單 (PCF)
2. 過濾主動式ETF (代號以A結尾, 如00981A)
3. 與前一交易日快照比對,計算逐股逐檔增減
4. 聚合成個股層級共識訊號 (N5Y規則: >=3檔同向=strong, 2檔=weak)
5. 輸出 n5y_latest.json (Scanner讀取) + 累積 n5y_history.json (趨勢分析)

設計原則: 無API金鑰、無外部服務依賴、失敗時明確報錯不靜默。
"""
import json, re, sys, hashlib, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

BASE = "https://openapi.twse.com.tw/v1"
DATA_DIR = Path(__file__).parent / "data"
SNAP_DIR = DATA_DIR / "snapshots"
TZ = ZoneInfo("Asia/Taipei")

# 已知候選端點(依序嘗試);若全失敗則從swagger自動探索
CANDIDATE_ENDPOINTS = [
    "/opendata/t187ap47_L",       # 常見編號慣例,待首跑驗證
    "/exchangeReport/ETF_PCF",
]
DISCOVER_KEYWORDS = ["申購買回", "申購贖回", "PCF"]

def http_get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": "chipflow-n5y/1.0",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def discover_endpoint():
    """先試候選端點;失敗則抓swagger規格檔,用關鍵字找PCF資料集路徑"""
    for ep in CANDIDATE_ENDPOINTS:
        try:
            data = http_get_json(BASE + ep)
            if isinstance(data, list) and len(data) > 0:
                print(f"[endpoint] 候選端點可用: {ep} ({len(data)}筆)")
                return ep, data
        except Exception as e:
            print(f"[endpoint] 候選 {ep} 失敗: {e}")
    print("[endpoint] 候選全數失敗,改從swagger自動探索...")
    try:
        spec = http_get_json(BASE + "/swagger.json")
        for path, methods in spec.get("paths", {}).items():
            desc = json.dumps(methods, ensure_ascii=False)
            if any(k in desc for k in DISCOVER_KEYWORDS):
                try:
                    data = http_get_json(BASE + path)
                    if isinstance(data, list) and len(data) > 0:
                        print(f"[endpoint] swagger探索成功: {path}")
                        return path, data
                except Exception:
                    continue
    except Exception as e:
        print(f"[endpoint] swagger探索失敗: {e}")
    sys.exit("❌ 無法定位PCF端點。請手動開啟 https://openapi.twse.com.tw/ 搜尋'申購買回',把路徑填入CANDIDATE_ENDPOINTS")

# 欄位名稱容錯對照(不同資料集欄位命名不一,首跑會print實際keys供校正)
FIELD_ALIASES = {
    "etf_code":   ["基金代號","ETF代號","證券代號","Code","FundCode","基金代碼"],
    "etf_name":   ["基金名稱","ETF名稱","證券名稱","Name","FundName"],
    "stock_code": ["成分股代號","股票代號","證券代號2","StockCode","成份股代號","股票代碼"],
    "stock_name": ["成分股名稱","股票名稱","StockName","成份股名稱"],
    "shares":     ["股數","持有股數","張數","Shares","持股數","股份數額"],
}
def pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def parse_pcf(raw):
    """把原始PCF列表轉為 {etf_code: {"name":..., "holdings": {stock_code: shares}}}
       僅保留主動式ETF(代號含字母A結尾,如00981A/00403A)"""
    if raw and isinstance(raw[0], dict):
        print(f"[parse] 首筆實際欄位: {list(raw[0].keys())}")
    etfs = {}
    skipped = 0
    for row in raw:
        ec = str(pick(row, FIELD_ALIASES["etf_code"]) or "").strip()
        if not re.match(r"^\d{4,6}[A-Z]$", ec):  # 主動式ETF代號格式
            skipped += 1
            continue
        sc = str(pick(row, FIELD_ALIASES["stock_code"]) or "").strip()
        if not re.match(r"^\d{4,5}$", sc):
            continue
        sh_raw = pick(row, FIELD_ALIASES["shares"])
        try:
            sh = int(float(str(sh_raw).replace(",", "")))
        except (TypeError, ValueError):
            continue
        e = etfs.setdefault(ec, {"name": str(pick(row, FIELD_ALIASES["etf_name"]) or ec), "holdings": {}, "stock_names": {}})
        e["holdings"][sc] = e["holdings"].get(sc, 0) + sh
        sn = pick(row, FIELD_ALIASES["stock_name"])
        if sn: e["stock_names"][sc] = str(sn).strip()
    print(f"[parse] 主動式ETF {len(etfs)}檔, 略過非主動列 {skipped}筆")
    return etfs

def load_prev_snapshot(today_str):
    snaps = sorted(SNAP_DIR.glob("*.json"), reverse=True)
    for p in snaps:
        if p.stem < today_str:
            return json.loads(p.read_text(encoding="utf-8")), p.stem
    return None, None

def aggregate(today_etfs, prev_etfs):
    """核心聚合:逐股統計跨ETF共識"""
    stocks = {}
    stock_names = {}
    for ec, e in today_etfs.items():
        prev_h = (prev_etfs.get(ec) or {}).get("holdings", {}) if prev_etfs else {}
        cur_h = e["holdings"]
        stock_names.update(e.get("stock_names", {}))
        all_codes = set(cur_h) | set(prev_h)
        for sc in all_codes:
            delta = cur_h.get(sc, 0) - prev_h.get(sc, 0)
            if delta == 0:
                continue
            s = stocks.setdefault(sc, {"buy": [], "sell": [], "newEntry": [], "exit": []})
            if delta > 0:
                s["buy"].append({"etf": ec, "shares": delta})
                if sc not in prev_h: s["newEntry"].append(ec)
            else:
                s["sell"].append({"etf": ec, "shares": delta})
                if sc not in cur_h or cur_h.get(sc, 0) == 0: s["exit"].append(ec)
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
    """連續同向天數:比對歷史,計算每檔股票連續N日同方向共識"""
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
    print(f"=== ChipFlow N5Y Collector {today_str} {now.strftime('%H:%M')} 台北時間 ===")

    ep, raw = discover_endpoint()
    today_etfs = parse_pcf(raw)
    if not today_etfs:
        sys.exit("❌ 解析後無主動式ETF資料——可能欄位名不符,請看上方[parse]印出的實際欄位,補進FIELD_ALIASES")

    # 內容雜湊防重:週末/假日API可能回舊資料,相同內容不重複存檔
    content_hash = hashlib.md5(json.dumps(today_etfs, sort_keys=True).encode()).hexdigest()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(SNAP_DIR.glob("*.json"), reverse=True)[:1]:
        prev_data = json.loads(p.read_text(encoding="utf-8"))
        if hashlib.md5(json.dumps(prev_data, sort_keys=True).encode()).hexdigest() == content_hash:
            print("[dedup] 內容與最近快照相同(假日/未更新),跳過本次")
            return

    snap_path = SNAP_DIR / f"{today_str}.json"
    snap_path.write_text(json.dumps(today_etfs, ensure_ascii=False), encoding="utf-8")
    print(f"[snapshot] 已存 {snap_path.name}")

    prev_etfs, prev_date = load_prev_snapshot(today_str)
    if prev_etfs is None:
        print("[aggregate] 首次執行,無前日快照可比對,今日僅建立基準")
        latest = {"updated": today_str, "note": "首日基準,明日起產生異動訊號", "records": []}
    else:
        print(f"[aggregate] 與 {prev_date} 快照比對")
        hist_path = DATA_DIR / "n5y_history.json"
        history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
        records = aggregate(today_etfs, prev_etfs)
        records = compute_streaks(records, history)
        latest = {"updated": today_str, "comparedWith": prev_date,
                  "etfCount": len(today_etfs), "records": records}
        history.append({"date": today_str, "records": [
            {k: r[k] for k in ("code","name","direction","consensusEtfCount","netShares","tier")}
            for r in records if r["consensusEtfCount"] >= 2]})
        history = history[-90:]  # 保留90個交易日
        hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        strong = [r for r in records if r["tier"] == "strong"]
        print(f"[result] 異動{len(records)}檔 | 強共識{len(strong)}檔: " +
              ", ".join(f"{r['name']}({r['direction']}x{r['consensusEtfCount']})" for r in strong[:8]))

    (DATA_DIR / "n5y_latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[done] n5y_latest.json 已更新")

if __name__ == "__main__":
    main()
