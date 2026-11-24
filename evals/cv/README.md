# CV 忠實度

三個 `example-*.yaml` 是格式範例，內容都是同一位虛構人物。真正的檔案放在 `private/`（不進版控）。

| 範例 | 內容 | 真實位置 |
| --- | --- | --- |
| `example-evidence.yaml` | 事實：可以證明的主張與數字 | `private/evidence.yaml` |
| `example-phrases.yaml` | 文案：定稿句子與它引用的證據 id | `private/phrases.yaml` |
| `example-cv.yaml` | 單一職缺的取捨：用哪些文案、順序、標題、版面 | `private/cvs/<slug>/cv.yaml` |

兩條產生路徑都收在同一道 lint：

```bash
cd worker
# 由模型挑選並改寫證據
uv run job-radar cv <feed 職缺 id> --evidence ../private/evidence.yaml --out ../private/cvs --pdf
# 由設定檔組合既有文案（不帶 slug 會重建全部）
uv run python ../private/build_cv.py [<slug>] [--no-pdf]
```

文案路徑多一道更早的關卡：載入文案庫時就會驗證每條 `cites`，指到不存在的證據 id 直接報錯，
不會等到 lint 才發現。

每份草稿都會跑 lint，結果寫在輸出資料夾的 `lint.json`：

| 檢查 | 目標 |
| --- | --- |
| 沒有引用證據的句子 | 0 |
| 引用不存在的證據 id | 0 |
| 命中「不可主張」清單 | 0 |
| 沒有證據支持的技能 | 0 |
| PDF 頁數（加 `--pdf`） | ≤ 2 |

規格的 CV 忠實度集（10 份生成的 CV + 人工審閱）以這些 lint 結果為自動部分；人工審閱看的是「句子有沒有超出引用證據的內容」，lint 抓不到這一類。
