# ChipFlow N5Y — 主動式ETF共識自動收集器

每個交易日自動抓取證交所PCF(ETF申購買回清單),比對主動式ETF逐日持股變化,
聚合成跨機構共識訊號,供 ChipFlow Scanner 讀取。

## 一次性設定(約10分鐘)

1. GitHub 建立新 repo(建議名稱 `chipflow-n5y`,**必須設為 Public**,Scanner才能免認證讀取)
2. 上傳本資料夾全部檔案(網頁版:Add file → Upload files,把解壓後的檔案拖進去)
   - 注意 `.github/workflows/daily.yml` 的路徑結構必須保留
3. repo → Settings → Actions → General → Workflow permissions → 勾選 **Read and write permissions** → Save
4. repo → Actions 頁籤 → 選 "N5Y Daily PCF Collector" → **Run workflow** 手動跑第一次
5. 看執行log:
   - 若成功:`data/` 會出現當日快照,首日只建基準,**第二個交易日起**開始產生異動訊號
   - 若失敗在 `[endpoint]`:照log指示開 https://openapi.twse.com.tw/ 搜尋「申購買回」,把正確路徑填入 collector.py 的 CANDIDATE_ENDPOINTS
   - 若失敗在 `[parse]`:log會印出實際欄位名稱,回報給Claude補進FIELD_ALIASES即可
6. 完成後每個交易日17:45自動執行,無需再管

## Scanner 串接

Scanner v8.2 內的 `N5Y_REMOTE` 常數改成:
`https://raw.githubusercontent.com/<你的帳號>/chipflow-n5y/main/data/n5y_latest.json`

## 訊號解讀框架(N5Y規則)

| 訊號 | 意義 | 搭配框架 |
|---|---|---|
| 強共識加碼(≥3檔) | 多位經理人獨立同向,純度最高 | +Radar籌碼低位=潛伏共振 |
| 強共識減碼 | 經理人集體撤退,常領先於新聞 | 持股中=提前預警 |
| 建倉(newEntries) | 新進成分股,比加碼更強的表態 | 值得單獨深掃 |
| 清倉(exits) | 完全出清,比減碼更強的警訊 | 持股中=最高警戒 |
| divergent分歧 | 買賣雙方都≥2檔,多空對決 | 觀望,不宜單邊解讀 |
| streak連續N日 | 趨勢性建倉vs單日再平衡的分水嶺 | streak≥3=趨勢確立 |

資料來源:證交所 TWSE OpenAPI(官方、免費、無金鑰) | 保留90交易日歷史
