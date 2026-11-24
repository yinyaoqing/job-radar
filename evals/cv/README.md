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

## 撰寫與審查雙 agent（`cv --review`）

`cv.py` 只問模型一次，再用 lint 檢查。lint 看不到一種錯：句子引用了真的證據，卻寫得比證據多（證據是「降到 1.6 秒」，句子寫成「降到 0.9 秒」）。`cv_loop.py` 為此加上第二個 agent，逐句對照它引用的證據原文：

- **撰寫 agent** 有查證據庫的工具（搜尋、讀取、提交草稿），自己決定查什麼；草稿不合 schema 時以工具錯誤退回給它。
- **審查 agent** 有自己的指示，只看得到職缺、草稿與被引用的證據原文，看不到撰寫 agent 的對話。
- **關卡由程式決定**：lint 通過且審查沒有提出阻擋性問題，草稿才算接受。審查意見若沒有引用草稿裡實際存在的句子，直接作廢。

只有這一步是多 agent。抓取、資格規則與抽取維持決定性或單次呼叫：它們的順序是固定的，讓模型決定下一步只會更貴、更難重現。

`review-cases.yaml` 量測審查 agent 補上了什麼。20 份草稿全部通過 lint；其中 12 份各藏一句植入的誇大（改數字、擴大範圍、虛構職稱、多寫技術或成果、引用錯證據），8 份是忠實的改寫。

```
cd worker && uv run python -m job_radar.cv_loop ../evals/cv/review-cases.yaml     ../evals/cv/example-evidence.yaml --max-cost 1 --out ../evals/cv/review-last-run.json
```

2026-11-24 以 `claude-sonnet-5-5` 執行（`review-last-run.json`）：12 個植入的誇大抓到 12 個，8 份忠實改寫誤報 0 份，20 次呼叫共 US$0.0672。

這個結果要照實解讀：

- 案例由本專案作者撰寫，植入的錯誤都很直白（數字不同、職稱不存在）。它說明審查 agent 抓得到 lint 看不見的明顯誇大，也不會懲罰改寫；它沒有說明細微的誇大抓不抓得到。
- 20 個案例分不出 95% 與 100% 的審查器。
- 完整迴圈在同一個虛構職缺上實跑一次，一輪就被接受（US$0.019），所以那次沒有走到「退回重寫」的路徑。退回路徑由離線測試以腳本化的 agent 驗證。
