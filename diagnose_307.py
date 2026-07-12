#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
N5Y 307診斷腳本 — 印出307重導向的實際目標網址與完整回應標頭
不自動跟隨重導向,只是把307回應本身的細節攤開來看
"""
import json, urllib.request, urllib.error

URL = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
PAYLOAD = {"fundCode": "49YTW", "date": "115/07/12", "specificDate": False}

def main():
    data = json.dumps(PAYLOAD).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Origin": "https://www.ezmoney.com.tw",
        "Referer": "https://www.ezmoney.com.tw/ETF/Transaction/PCF",
    })

    class NoRedirect(urllib.request.HTTPErrorProcessor):
        def http_response(self, request, response):
            return response
        https_response = http_response

    opener = urllib.request.build_opener(NoRedirect)

    print(f"=== 對 {URL} 發送POST,不自動跟隨重導向 ===")
    print(f"[request] payload: {PAYLOAD}")
    try:
        resp = opener.open(req, timeout=30)
        print(f"[response] status: {resp.status}")
        print(f"[response] 完整headers:")
        for k, v in resp.headers.items():
            print(f"    {k}: {v}")
        body = resp.read().decode("utf-8", errors="replace")
        print(f"[response] body前500字元: {body[:500]}")
    except urllib.error.URLError as e:
        print(f"[error] URLError: {e}")
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
