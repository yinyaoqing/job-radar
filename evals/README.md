# evals

四個 eval 集（地區陷阱、抽取正確性、推薦品質、CV 忠實度），見 docs/spec.md「評估（evals）」。
標註資料若取自 private/，只放去識別化後的版本。

## 地區陷阱集（`region_traps/cases.yaml`）

44 筆，依常見寫法編寫，不含公司名稱與私人資料。候選人預設為台灣、UTC+8、08:00–23:00 可上線。

```bash
cd worker
uv run job-radar eval regions          # 規則層：用標註好的 policy 判斷（CI 每次跑）
uv run job-radar eval regions --live   # 完整路徑：先用 LLM 抽取再判斷（需要 ANTHROPIC_API_KEY）
```

目標：準確率 ≥ 90%、「不可申請」召回率 ≥ 95%。改到抽取、資格規則或資料集的 PR 會由 `.github/workflows/eval.yml` 跑 live 版。
