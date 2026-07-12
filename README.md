# ChipFlow N5Y v2 — 主動式ETF共識自動收集器(逐投信端點版)

## 重要架構說明
證交所本身**沒有**PCF中央API。PCF依法規定由各投信自行公布,分散在各投信網站。
本版本改為「逐投信端點」架構——collector.py 的 `ISSUERS` 字典裡,每家投信一組抓取設定。

**目前已確認可用:統一投信**(ezmoney.com.tw),涵蓋 00981A / 00403A / 00988A 三檔。
其他投信(復華/群益/野村等)尚未串接,需重複下方「新增投信」的偵查流程逐一補上。

## 一次性設定(約10分鐘)
1. GitHub 建立新 repo(**Public**),或覆蓋既有 chipflow-n5y repo 內容
2. 上傳本資料夾全部檔案,保留 `.github/workflows/daily.yml` 路徑結構
   - 若拖曳上傳漏掉 `.github` 隱藏資料夾,改用 Add file → Create new file 手動輸入完整路徑貼上內容
3. repo → Settings → Actions → General → Workflow permissions → 勾選 **Read and write permissions**
4. repo → Actions → 選 "N5Y Daily PCF Collector" → **Run workflow** 手動跑第一次
5. 看執行log:
   - 成功會看到 `[fetch] 統一投信 00981A(49YTW) 持股N檔` 這類訊息
   - 首次執行只建立基準(無比較對象),**第二個執行日起**才會產生異動訊號
6. 之後每個交易日17:45自動執行

## 如何新增一家投信(擴充涵蓋範圍)
1. 用瀏覽器開該投信的ETF官網,找PCF查詢頁面(常見路徑含「申購買回」「PCF」字樣)
2. F12開發者工具 → Network分頁 → 切換查詢的基金 → 找XHR/Fetch請求
3. 記錄:請求網址、方法(GET/POST)、參數格式、回傳JSON結構
4. 把截圖或文字回傳結果提供給Claude,由Claude寫一個新的 `fetch_XXX()` 函式加入 collector.py
5. 在 `ISSUERS` 字典新增一組 `{"發行商名稱": {"fetcher": fetch_XXX, "funds": [...]}}`

## Scanner 串接
Scanner v8.2 的 `N5Y_REMOTE` 常數填入:
`https://raw.githubusercontent.com/<你的帳號>/chipflow-n5y/main/data/n5y_latest.json`

## 訊號解讀框架(N5Y規則)
| 訊號 | 意義 |
|---|---|
| 強共識加碼(≥3檔同向) | 多位經理人獨立同向,純度最高 |
| 建倉(newEntries) | 新進成分股,比加碼更強的表態 |
| 清倉(exits) | 完全出清,比減碼更強的警訊 |
| divergent分歧 | 買賣雙方都≥2檔,多空對決,不宜單邊解讀 |
| streak連續N日 | 趨勢性建倉vs單日再平衡的分水嶺 |

**現況限制**:目前僅統一投信3檔基金,共識訊號會被低估(因為缺少其他投信的同向佐證)。
隨涵蓋投信增加,訊號純度會提升。此為漸進式擴充架構,非一次到位。
