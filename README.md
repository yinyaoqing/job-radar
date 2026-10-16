# Job Radar

每天自動抓取全遠端職缺（不限職能，可依領域篩選），到 ATS 確認職缺仍開放，判斷台灣（UTC+8）能否申請，比對經歷打分，再產出客製 CV 草稿的求職 agent。

- 規格：[docs/spec.md](docs/spec.md)（雲端版含流程圖、架構圖與時程：[Claude Docs](https://claude.ai/code/artifact/e4f6a916-561d-46bc-b4cc-b8fb92a606e6)）
- 狀態（10/16）：ATS adapters（Ashby、Greenhouse、Lever、Recruitee、Workable）、每日抓取管線、公司匯入（remoteintech、HN）、全遠端與領域分類、LLM 抽取、資格判斷、地區陷阱 eval、公開 JSON 匯出、網站、每日 Email、CV 草稿與 CI 已完成；下一步是部署與 eval 實跑

## 評估

| Eval | 結果（2026-10-16） | 目標 |
| --- | --- | --- |
| 地區陷阱集（51 筆，LLM 抽取 + 規則，連跑 3 次） | 準確率 100%、「不可申請」召回率 100%，每次 US$0.026 | ≥ 90% / ≥ 95% |

細節見 [evals/README.md](evals/README.md)。

## 目錄

| 路徑 | 內容 |
| --- | --- |
| `worker/` | Python worker：來源 adapters、驗證、抽取、評分、CV 產生 |
| `web/` | Next.js 靜態網站：依領域篩選全遠端職缺、在瀏覽器判斷能否申請、申請看板 |
| `evals/` | eval 資料集與評分腳本（尚未建立） |
| `deploy/` | 每日抓取的主機部署（cron + Docker） |
| `docs/` | 規格與設計文件 |
| `private/` | 個人求職資料（shortlist、申請筆記），**不進版控** |

## 開發

```bash
cd worker
uv sync
uv run pytest            # 離線測試
uv run pytest -m live    # 打真實 ATS 端點的 smoke test
uv run ruff check .

uv run job-radar check ashby stickermule 6db27241-e2d4-4f35-a2c4-b58d84621843
uv run job-radar list lever binance --grep frontend

# 公共資料管線（資料庫預設 job-radar.db，可用 --db 或 JOB_RADAR_DB 指定）
uv run job-radar companies import-remoteintech --region worldwide --region asia-pacific
uv run job-radar companies import-hn --months 2
uv run job-radar companies add ashby <org>
uv run job-radar crawl
uv run job-radar postings --category marketing   # 全遠端職缺，依領域篩選
uv run job-radar extract --max-cost 1          # 需要 ANTHROPIC_API_KEY
uv run job-radar postings --eligible             # 依 JOB_RADAR_COUNTRY / JOB_RADAR_UTC_OFFSET 判斷
uv run job-radar eval regions                    # 地區陷阱 eval（--live 會呼叫 LLM）
uv run job-radar digest                          # 預覽每日 Email（--send 寄出，需 SMTP_*）
uv run job-radar cv <職缺 id> --evidence ../private/evidence.yaml --pdf   # 客製 CV + 申請筆記
uv run job-radar export --out public/feed.json
```

## 授權

MIT
