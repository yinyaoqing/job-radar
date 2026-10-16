# CV 忠實度

`example-evidence.yaml` 是證據庫格式的範例，內容是虛構人物。真正的證據庫放在 `private/evidence.yaml`（不進版控）。

```bash
cd worker
uv run job-radar cv <feed 職缺 id> --evidence ../private/evidence.yaml --out ../private/cvs --pdf
```

每份草稿都會跑 lint，結果寫在輸出資料夾的 `lint.json`：

| 檢查 | 目標 |
| --- | --- |
| 沒有引用證據的句子 | 0 |
| 引用不存在的證據 id | 0 |
| 命中「不可主張」清單 | 0 |
| 沒有證據支持的技能 | 0 |
| PDF 頁數（加 `--pdf`） | ≤ 2 |

規格的 CV 忠實度集（10 份生成的 CV + 人工審閱）以這些 lint 結果為自動部分；人工審閱看的是「句子有沒有超出引用證據的內容」，lint 抓不到這一類。
