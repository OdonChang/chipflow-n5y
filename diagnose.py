#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
N5Y 診斷腳本 — 列出證交所OpenAPI裡所有含"ETF"字樣的端點
用途:一次性找出PCF(申購買回清單)的正確路徑,取代逐一猜測候選端點
"""
import json, urllib.request

BASE = "https://openapi.twse.com.tw/v1"

def http_get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": "chipflow-n5y-diagnose/1.0",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    print("=== 抓取 swagger 規格書 ===")
    spec = http_get_json(BASE + "/swagger.json")
    paths = spec.get("paths", {})
    print(f"總端點數: {len(paths)}\n")

    print("=== 含 'ETF' 關鍵字的端點 ===")
    etf_paths = []
    for path, methods in paths.items():
        desc = json.dumps(methods, ensure_ascii=False)
        if "ETF" in desc or "etf" in path.lower():
            summary = ""
            for method, detail in methods.items():
                summary = detail.get("summary", "") or detail.get("description", "")
                break
            print(f"  {path}")
            print(f"    → {summary}")
            etf_paths.append(path)
    print(f"\n共找到 {len(etf_paths)} 個ETF相關端點\n")

    print("=== 含 '申購' 或 '贖回' 或 'PCF' 關鍵字的端點 ===")
    pcf_paths = []
    for path, methods in paths.items():
        desc = json.dumps(methods, ensure_ascii=False)
        if any(k in desc for k in ["申購", "贖回", "PCF", "買回"]):
            summary = ""
            for method, detail in methods.items():
                summary = detail.get("summary", "") or detail.get("description", "")
                break
            print(f"  {path}")
            print(f"    → {summary}")
            pcf_paths.append(path)
    print(f"\n共找到 {len(pcf_paths)} 個PCF相關端點")

    candidates = list(set(etf_paths + pcf_paths))
    print(f"\n=== 逐一試抓候選端點的實際資料(前1筆) ===")
    for p in candidates:
        try:
            data = http_get_json(BASE + p)
            if isinstance(data, list) and len(data) > 0:
                print(f"\n--- {p} ({len(data)}筆) ---")
                print(f"欄位: {list(data[0].keys())}")
            else:
                print(f"\n--- {p} --- (空陣列或非list)")
        except Exception as e:
            print(f"\n--- {p} --- 抓取失敗: {e}")

if __name__ == "__main__":
    main()
