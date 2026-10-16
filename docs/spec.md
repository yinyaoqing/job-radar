# Job Radar 求職 Agent：規格文件

2026-10-16

## 摘要

Job Radar 是一個每天自動抓取遠端職缺、到 ATS 確認職缺仍開放、判斷台灣（UTC+8）能否申請、比對使用者的經歷打分，再產出客製 CV 草稿的 agent。6 週做出可公開展示的 MVP。

- **解決的問題**：求職者每一輪職缺篩選、驗證與 CV 客製多半靠手動或一次性的 AI 對話完成，結果散在各處的筆記檔。
- **成功指標（MVP）**
  - 每日推薦中「已關閉」職缺比例 < 2%
  - 地區／時區限制判斷準確率 ≥ 90%（對照人工標註集）
  - Top 10 推薦中「會投」比例 ≥ 50%
  - 客製 CV 草稿中「無依據的經歷主張」= 0
  - 每日執行成本 < US$1
- **雙重用途**：作者每天自用；同時作為 AI 產品全端職缺的公開作品，展示 agent 流程、結構化輸出、evals 與成本控制。

## 使用者與情境

目標使用者：身處亞洲時區（例如台灣 UTC+8）、尋找全遠端資深前端、全端或 AI 產品工程職缺的工程師。MVP 先服務單一使用者，之後再開放多人使用。

典型的手動流程與痛點：

| 步驟 | 現在怎麼做 | 痛點（實際發生過） |
| --- | --- | --- |
| 找職缺 | Remote Rocketship、WWR、104、HN Who's Hiring，人工彙整成 shortlist | 聚合網站的資料會過期：職缺在 ATS 上已關閉，聚合站仍列出 |
| 確認是否開放 | 逐筆呼叫 Ashby / Greenhouse / Lever / Recruitee API | 每家 ATS 的 API 形式不同，每次要重新查 |
| 判斷能否申請 | 人工讀 JD 與結構化地點欄位 | 標「Remote」實際限區：限美國、限歐盟、限 UTC-4..+4，或標題寫 Worldwide 但結構化地點不含台灣 |
| 判斷是否適合 | 人工對照技術棧與經歷 | 容易漏看硬性條件（學歷、特定語言或框架） |
| 客製 CV | 每家複製一份 HTML，用 headless Chrome 輸出 2 頁 PDF | 每份都要重新驗證「哪些經歷可以寫」，避免寫入不存在的技術 |
| 追蹤進度 | 分散的筆記檔 | 沒有狀態總覽，不知道哪些已投、哪些在等 |

**核心情境**：每天早上打開一個頁面，看到 5–10 筆「仍開放、所在地可申請、適合自己」的職缺，每筆有理由與風險提示；點一下就能產生可以直接校對的客製 CV 與申請筆記。

## 功能範圍

MVP 只做「抓、驗、判、排、寫」五個動作，不自動送出任何申請。

| 功能 | MVP | 說明 |
| --- | --- | --- |
| 來源抓取 | 做 | ATS 公開 API（Ashby、Greenhouse、Lever、Recruitee）+ HN Who's Hiring + 104 全遠端 + GitHub 公司清單與「谁在招人」；公司清單可自訂 |
| 開放狀態驗證 | 做 | 每筆推薦前都到來源 ATS 重新確認，記錄 last\_verified\_at |
| 申請資格判斷 | 做 | 地區、時區重疊、學歷、簽證／合約形式；輸出 eligible / blocked / unclear + 引文 |
| 適配評分 | 做 | 對照「經歷證據庫」打分，列出符合項與缺口 |
| 每日摘要 | 做 | Web 頁面 + Email；每筆可標「會投 / 不相關 / 已投」 |
| 客製 CV 草稿 | 做 | 以基礎 CV HTML 為模板，只引用證據庫內的事實，輸出 HTML + 2 頁 PDF |
| 申請筆記 | 做 | JD ↔ CV 對照表、表單題目清單、缺口提醒 |
| 申請狀態看板 | 做（簡版） | 待投 / 已投 / 面試 / 結束 |
| 自動送出申請 | 不做 | 部分表單明確禁止使用 AI，而且送出後無法撤回 |
| 自動寫表單題答案 | 不做 | 只列題目與可用素材，答案由使用者自己寫 |
| LinkedIn / Wellfound 抓取 | 不做 | 需登入且條款限制抓取 |
| 多使用者、付費 | 之後做 | 自用驗證後再評估 |
| 面試準備、公司研究 | 之後做 | 例如從公司部落格與 changelog 整理「Why us」素材 |

## Agent 流程

> 圖：Agent 流程 · 11 個步驟、1 個判斷點（見[雲端規格文件](https://claude.ai/code/artifact/e4f6a916-561d-46bc-b4cc-b8fb92a606e6)）

每日排程跑到「每日推薦摘要」為止；CV 草稿只在使用者標記「會投」後才產生，最後一步一定由使用者手動送出。

## 系統架構

> 圖：系統架構 · Worker 4 個模組、資料庫、三個輸出（見[雲端規格文件](https://claude.ai/code/artifact/e4f6a916-561d-46bc-b4cc-b8fb92a606e6)）

介面不直接呼叫 LLM 或外部來源，只透過 Worker 的 API 讀寫資料庫；「產生 CV」是使用者觸發的任務，其餘步驟由排程觸發。

## 資料來源與 ATS 整合

以 ATS 公開 API 為「真實來源」，聚合網站只用來發現新公司。每個來源寫成一個 adapter，實作同一個介面：`list(org)`、`get(org, id)`、`is_open(org, id)`。

| 來源 | 列表 | 單筆 / 開放判斷 | 備註 |
| --- | --- | --- | --- |
| Ashby | `GET api.ashbyhq.com/posting-api/job-board/<org>` | `POST jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting`；`jobPosting: null` = 已關閉 | 表單欄位在 `applicationForm`；`field` 是 JSON scalar，不能再選子欄位 |
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/<token>/jobs` | `.../jobs/<id>` 回 404 = 已關閉 |  |
| Lever | `GET api.lever.co/v0/postings/<org>?mode=json` | `.../<id>` | `createdAt` 為 epoch ms |
| Recruitee | `GET <co>.recruitee.com/api/offers/` | `/api/offers/<slug>` 含表單 | 結構化地點可能與標題「Worldwide」矛盾 |
| Personio / Breezy | 公開職缺頁 | 頁面是否仍存在 | 第二階段 |
| 104 全遠端 | `www.104.com.tw/jobs/search/api/jobs?remoteWork=1&...` | 列表內已含描述與薪資 | 需 Chrome User-Agent、`Accept: application/json` 與對應的 Referer，否則被 Cloudflare 擋下 |
| HN Who's Hiring | 每月貼文（HN Algolia API） | 留言內的 ATS 連結交給對應 adapter | 留言為自由文字，需 LLM 抽取 |
| Remote Rocketship | 頁面內 `__NEXT_DATA__` 的 `initialJobOpenings` | 不用於判斷開放 | 只用來發現公司；有 ghostScore 欄位 |

### GitHub 上的來源

GitHub 上的來源主要用來「發現公司」與「收華語職缺」，從這裡找到的公司一樣交給上表的 ATS adapter 驗證是否仍開放。以下活躍度為 2026-10-15 的查詢結果。

| 來源 | 內容 | 抓取方式 | 用途 |
| --- | --- | --- | --- |
| [remoteintech/remote-jobs](https://github.com/remoteintech/remote-jobs) | 887 家遠端公司各一個 md 檔（`src/companies/*.md`），frontmatter 有 `region`、`remote_policy`、`technologies`、`careers_url`；最近一次 push 於 2026-10-01 | 用 `commits?path=src/companies&since=` 只抓變動的檔案，解析 frontmatter | **主要公司來源**：依 region 與 technologies 篩選，從 careers\_url 辨識 ATS 類型後自動加入 `companies` |
| [ruanyf/weekly](https://github.com/ruanyf/weekly) 「谁在招人」 | 每月一個 issue，職缺在留言中（2026 年 9 月 21 則、10 月 10 則） | 用 issue comments API，留言交給 LLM 抽取 | 華語職缺，含不少遠端；處理方式同 HN Who's Hiring |
| [lukasz-madon/awesome-remote-job](https://github.com/lukasz-madon/awesome-remote-job) | 遠端公司與求職網站清單 | 監看 README 的 commit diff | 新加入的公司進入待審核的關注清單 |
| [yanirs/established-remote](https://github.com/yanirs/established-remote) | 成熟遠端公司清單 | 同上 | 同上，更新頻率較低 |
| [poteto/hiring-without-whiteboards](https://github.com/poteto/hiring-without-whiteboards) | 不考白板題的公司，附地點與遠端標註 | 同上 | 適配評分的加分訊號 |

- **API 限制**：未登入每小時 60 次請求，帶 token 可到 5,000 次，每日執行一次足夠。
- **不接**：GitHub Jobs 已於 2021 年關閉；全站 `hiring` label 的 issue 自 2026 年 8 月起僅 3 則，量太少。
- **第二階段**：用 GitHub 搜尋找出「公開 repo 使用 Next.js / TypeScript」的公司，當作技術棧符合度的加分。

**不接的來源**：CakeResume、Himalayas 詳情頁對程式化請求回 403；LinkedIn、Wellfound 需登入。

**抓取規範**：每個網域限速（預設 1 req/s）、尊重 robots.txt、快取 ETag；每日只抓關注公司清單，不做全網爬取。

## 資料模型

公共資料層用 SQLite（已實作，一個檔案、不需維運）；個人資料預設存在使用者瀏覽器，只有託管的付費版才需要 PostgreSQL + pgvector。核心是「職缺快照」與「經歷證據庫」兩張表：前者讓每個判斷可以回溯到當時的 JD，後者讓 CV 的每一句都有出處。

| 表 | 主要欄位 | 用途 |
| --- | --- | --- |
| `companies` | id, name, ats, ats\_org, watch, notes | 關注公司清單與 ATS 對應 |
| `postings` | id, company\_id, ats\_job\_id, title, url, status (open / closed), first\_seen\_at, last\_verified\_at | 每個職缺一筆，狀態由驗證步驟更新 |
| `posting_snapshots` | posting\_id, fetched\_at, raw\_json, jd\_text, content\_hash | JD 原文版本；內容變動才新增一筆 |
| `extractions` | snapshot\_id, model, schema\_version, payload (JSON), cost\_usd | LLM 結構化抽取結果（見下節 schema） |
| `assessments` | posting\_id, eligibility (eligible / blocked / unclear), eligibility\_quotes, fit\_score, matched\_evidence\_ids, gaps, rationale | 資格判斷與適配評分 |
| `evidence` | id, claim, source\_repo, source\_path, verified\_at, tags, embedding, public\_ok | 經歷證據庫：每條可寫進 CV 的事實與出處 |
| `evidence_exclusions` | term, reason | 「不可主張」清單：使用者沒用過、不能寫進 CV 的技術 |
| `cv_drafts` | posting\_id, html, pdf\_path, pages, evidence\_ids, lint\_report | 客製 CV 草稿與檢查結果 |
| `applications` | posting\_id, stage, applied\_at, next\_action, notes | 申請狀態看板 |
| `feedback` | posting\_id, label (will\_apply / irrelevant / applied), reason | 使用者回饋，同時是 eval 資料 |
| `runs` | id, started\_at, step, tokens, cost\_usd, error, trace\_id | 每次執行的成本與追蹤 |

**證據庫的初始資料**：從使用者既有履歷與作品中已驗證的事實匯入（例如某個 repo 的測試檔案數、某項功能的規模）。每條標記 `public_ok`，私有 repo 的細節不進公開版。

## LLM 設計

能用規則解決的不交給 LLM；LLM 只做「讀自由文字」與「寫理由、寫 CV」，而且每個判斷都要附上 JD 原文引文。

| 步驟 | 做法 | 模型 |
| --- | --- | --- |
| 結構化抽取 | JD → 固定 JSON schema（tool use / structured output） | 便宜模型（Claude Haiku 5.5） |
| 資格判斷 | 先用規則判斷結構化地點欄位與時區重疊；規則無法判斷時才交給 LLM，結果為 unclear 時人工確認 | 規則為主 |
| 適配評分 | embedding 取前 20 條證據 → LLM 逐條對應 JD 要求、標出缺口 | 中階模型（Claude Sonnet 5.5） |
| 推薦理由 | 每筆 ≤ 2 句，必須引用 extraction 欄位 | 中階模型 |
| CV 草稿 | 只能引用 `evidence` 表內的條目（以 id 引用），由程式組裝成 HTML | 中階模型 |

**抽取 schema（v1）**

```json
{
  "title": "string",
  "seniority": "junior | mid | senior | staff | unknown",
  "employment": "full_time | contract | part_time | unknown",
  "location_policy": {
    "type": "worldwide | region_list | country_list | timezone_window | onsite_hybrid | unknown",
    "countries": ["ISO-3166 alpha-2"],
    "timezone_window_utc": {"from": -4, "to": 4},
    "required_overlap_hours": 0,
    "quotes": ["JD 原文引文"]
  },
  "must_have": [{"skill": "string", "quote": "string"}],
  "nice_to_have": [{"skill": "string", "quote": "string"}],
  "hard_requirements": [{"type": "degree | years | language | clearance | other", "value": "string", "quote": "string"}],
  "salary": {"min": 0, "max": 0, "currency": "USD", "period": "year"},
  "application_form": {"no_ai_policy": false, "required_links": ["github", "linkedin", "code_sample"], "questions": ["string"]}
}
```

**防幻覺規則**

- 每個抽取的 `quote` 由程式對 JD 原文做字串比對，找不到就把該欄位標為 unclear。
- 結構化地點欄位（例如 Recruitee 的 applicantLocationRequirements）與 JD 文字衝突時，不自動下結論，標為 unclear 並顯示兩邊依據。
- CV 草稿經過 lint：出現 `evidence_exclusions` 內的詞、未引用 evidence id 的句子、超過 2 頁，都視為失敗。
- 表單標示禁用 AI 時（`no_ai_policy`），只產出題目清單，不產出任何答案草稿。

## 評估（evals）

四個 eval 集放在 repo 內，每次改 prompt、模型或 schema 都在 GitHub Actions 跑，分數下降就擋住合併。

| Eval 集 | 內容 | 指標 | 目標 |
| --- | --- | --- | --- |
| 地區陷阱集 | 已知案例 30–50 筆，涵蓋：限單一國家、限歐盟、時區窗口（例如 UTC-4..+4）、指定時段重疊 N 小時、明列可申請國家清單、標題 Worldwide 但結構化地點不符等 | eligible / blocked / unclear 準確率；blocked 的召回率 | 準確率 ≥ 90%；blocked 召回率 ≥ 95% |
| 抽取正確性集 | 50 份 JD 人工標註的 must\_have、hard\_requirements、表單題目 | 欄位 F1；引文可在原文找到的比例 | F1 ≥ 0.85；引文命中 100% |
| 推薦品質集 | 每日回饋（會投 / 不相關）累積 | Top 10 precision（會投比例） | ≥ 50% |
| CV 忠實度集 | 10 份生成的 CV + 人工審閱 | 無依據主張數、禁用詞命中數、頁數 | 0 / 0 / 剛好 2 頁 |

地區陷阱集的標註來自實際求職紀錄（去識別化後才放進 repo）；評分結果與失敗案例會寫進 README，當作作品展示的主要證據。

## 介面與使用流程

Next.js + shadcn/ui，四個頁面；每天的主要動作都在第一個頁面完成。

1. **今日推薦**
   - 卡片列表，依適配分數排序。每張卡片有公司、職稱、薪資、資格徽章（可申請 / 地區受限 / 待確認）、最後驗證時間。
   - 展開後顯示符合項、缺口、JD 引文。
   - 三個按鈕：會投、不相關（附原因）、產生 CV。
2. **職缺詳情**
   - 左欄 JD 原文（引文高亮），右欄抽取結果與判斷。
   - 表單題目清單與「禁用 AI」提醒。
3. **CV 工作區**
   - 生成的 CV 預覽、每句對應的 evidence 出處、lint 結果。
   - 可編輯後重新輸出 PDF。
4. **申請看板**
   - 待投 → 已投 → 面試 → 結束，可拖曳。
   - 已投的職缺若在 ATS 上關閉，顯示提醒。

**每日 Email**：早上 8 點（台灣時間）寄出前 5 名與「已投但已關閉」的變動。

## 非功能需求

| 項目 | 需求 |
| --- | --- |
| 成本 | 每日執行 < US$1；JD 內容未變（content\_hash 相同）不重新抽取；固定的系統提示與證據庫使用 prompt caching；每步驟記錄 tokens 與費用到 `runs` |
| 可靠性 | 單一來源失敗不影響其他來源（每個 adapter 獨立 timeout 與重試）；任務中斷可從上次進度繼續 |
| 可觀測性 | OpenTelemetry trace 涵蓋每個步驟與 LLM 呼叫；後台顯示每日抓取數、關閉數、各步驟耗時與費用 |
| 隱私 | CV、證據庫、申請紀錄只存在使用者自己的資料庫；公開 demo 使用假資料；私有 repo 不匯入、不外連 |
| 抓取規範 | 只用公開 API 與公開頁面；限速、尊重 robots.txt；不繞過登入或驗證的保護 |
| 部署 | 先在本機與一台小型雲端主機執行；每日排程用主機 cron，GitHub Actions 只跑 CI（見「部署計畫」） |
| 開源 | 程式碼以 MIT 公開，個人資料與證據庫內容不進 repo |

## 開源網站與商業化

公共資料集中處理一次、所有人共用；個人資料預設留在使用者自己的瀏覽器。公共層成本因此不隨使用者數增加，主機上也沒有需要保護的個資。

| 層 | 內容 | 執行位置 | 成本由誰負擔 |
| --- | --- | --- | --- |
| 公共資料 | 公司清單、職缺、開放驗證、地區與時區判斷、抽取結果 | 自己的主機，每日 cron，輸出 `feed.json` | 營運方，固定成本 |
| 網站 | 職缺瀏覽與篩選，不需登入 | 靜態託管 | 營運方，接近零 |
| 個人資料 | 證據庫、適配評分、CV 草稿、申請看板 | 使用者的瀏覽器；LLM 用使用者自己的 key | 使用者 |
| CI | lint、測試、每晚 ATS 契約檢查、網站建置 | GitHub Actions | 公開 repo 免費 |

每日抓取不放 GitHub Actions：GitHub 條款限定其 runner 只用於專案的建置、測試、部署與發布，並排除當作 serverless 應用的一部分。

**商業化方向（提案）**

| 功能 | 免費（開源或公開網站） | 付費（託管） |
| --- | --- | --- |
| 職缺 | 列表、開放驗證、地區篩選 | 更多來源、新職缺即時通知 |
| 個人功能 | 自備 API key，資料在瀏覽器 | 不需自備 key、跨裝置同步 |
| 每日摘要 | 網頁 | Email 或推播 |

**商轉前要先處理的限制**

- **不轉載 JD 全文**：feed 只放職缺事實與連回 ATS 的連結（已實作）。
- **ATS API 使用條款**：Ashby、Greenhouse、Lever、Recruitee 是否允許第三方商業聚合，收費前要逐家確認。
- **104 與聚合網站**：條款確認前只用於自用版與發現公司，不出現在公開網站。
- **出處標示**：remoteintech 是 ISC 授權，feed 已附 attribution。
- **託管個資**：付費版一旦在伺服器存 CV 或證據庫，就需要隱私權政策、資料匯出與刪除（個資法、GDPR）。
- **不自動送出申請**：維持原則，也是和大量投遞工具的差異。

**最大的產品風險是公司覆蓋率**：付費價值來自覆蓋率與資料新鮮度，不是程式碼本身；目前可直接對到 ATS 的公司只有 17 家。

- [ ] 授權維持 MIT，還是改 AGPL 或 open-core？MIT 允許任何人直接架競品；建議維持 MIT，把付費價值放在託管與資料營運。
- [ ] 收費對象：求職者訂閱，還是向雇主收費（刊登、置頂）？後者會影響推薦的中立性。

## 里程碑

**目前進度（10/16）**：Ashby、Greenhouse、Lever 三個 adapter 與 `job-radar list / check` CLI 已完成，7 個離線測試與 4 個 live 測試全數通過，比原定 10/19 開工提早。同日又完成：SQLite 資料庫、每日抓取管線（發現 → 驗證 → 存快照 → 關閉從看板消失的職缺）、Recruitee adapter、remoteintech 公司匯入、公開 JSON 匯出、GitHub Actions CI；第一次實跑 17 家公司、71 筆開放職缺。還沒開始：抽取、資格判斷、網站。

**時程調整**（兩個里程碑日期不變）：

- 第 1 週改做資料庫（`companies`、`postings`、`posting_snapshots`）與每日管線「發現 → 驗證 → 存快照」，加上 Recruitee adapter 與 remoteintech 公司清單匯入。
- 需要 LLM 抽取的來源（HN Who's Hiring、谁在招人）移到第 2 週，和抽取一起做；104 也放在第 2 週，列為可失效來源。
- CI 從第 6 週提前到第 1 週；第 6 週只把四個 eval 接成合併門檻。
- 第 1 週剩下的時間改做公司清單擴充：remoteintech 886 家只有 17 家的徵才網址直接指向支援的 ATS，其中 5 家已失效；以 slug 探測 asia-pacific 23 家只命中 1 家。下一步加 Workable adapter，並從 HN 留言裡的 ATS 連結收集公司。

> 圖：開發與部署時程 · 6 週、2 個里程碑，ATS adapters 已提前完成（截至 10/16）（見[雲端規格文件](https://claude.ai/code/artifact/e4f6a916-561d-46bc-b4cc-b8fb92a606e6)）

| 週 | 日期 | 開發 | 部署 |
| --- | --- | --- | --- |
| 0 | 10/15–10/16 | adapters、管線（已完成） | CI 與 Docker（已完成） |
| 1 | 10/19–10/25 | 公司清單擴充與 Workable | |
| 2 | 10/26–11/1 | 抽取與陷阱 eval | 本機每日排程 |
| 3 | 11/2–11/8 | 資格規則與評分；11/8 開始自用 | 本機每日排程 |
| 4 | 11/9–11/15 | 每日摘要與 Email | 搬到小型主機 |
| 5 | 11/16–11/22 | CV 產生與 lint | |
| 6 | 11/23–11/29 | eval 門檻、README、demo；11/29 公開發布 | 公開網站 |

「開始自用」的條件是地區陷阱 eval 準確率 ≥ 90%；「公開發布」的條件是四個 eval 集都達標，且 README 附上分數與 2 分鐘 demo 影片。

### 部署計畫

每日任務先在本機跑到「開始自用」，第 4 週再搬到一台小型主機；GitHub Actions 只跑 CI，不跑每日任務。

| 階段 | 時間 | 執行位置 | 排程 | 資料庫 | 進入條件 |
| --- | --- | --- | --- | --- | --- |
| CI | 第 1 週起 | GitHub Actions（公開 repo） | push / PR 跑 ruff 與離線 pytest；每晚跑 `pytest -m live` | 無 | 無 |
| 本機自用 | 第 2–3 週 | 作者的 Windows 電腦 | 工作排程器，每天 07:00（台灣時間） | SQLite 檔 | 每日管線能從頭跑完 |
| 主機 | 第 4 週起 | 小型雲端主機，cron + Docker 跑 crawl 與 export（`deploy/daily.sh`） | cron 07:00 跑管線，08:00 寄 Email | SQLite 檔（Docker volume），每日備份 | 「開始自用」達標 |
| 公開網站 | 第 6 週 | 靜態託管（例如 Vercel），不需登入 | 無 | 讀 `feed.json`（真實公開職缺）；個人功能的示範用假資料 | 四個 eval 集達標 |

- **每日任務不放公開 repo 的 Actions**：公開 repo 的執行紀錄任何人都看得到，會洩漏關注公司清單與評分。
- **機密**：`ANTHROPIC_API_KEY`、`DATABASE_URL`、SMTP 帳密只放在主機的 `.env`；repo 只放 `.env.example`。
- **私人介面**：證據庫、評分、CV 與看板存在使用者自己的瀏覽器，LLM 呼叫用使用者自己的 API key；主機上只有公開職缺資料。
- **每晚 live 測試失敗**：視為 ATS API 變動的警示，對應風險表第一列。

## 風險與開放問題

| 風險 | 緩解 |
| --- | --- |
| ATS API 未公告就更動（例如 Ashby GraphQL 欄位） | 每個 adapter 有契約測試與錄製的回應；每日抓取失敗時發出警示 |
| 104 的 Cloudflare 規則改變 | 104 列為「可失效」來源，失效時略過不影響其他來源 |
| 資格判斷誤判，錯過好職缺 | blocked 的職缺仍可在「已過濾」分頁查看；定期抽檢 |
| CV 寫入不實經歷 | 證據庫引用制 + lint + 投遞前人工校對 |
| 只有作者一位使用者，缺少外部回饋 | 第 6 週後邀 3–5 位同樣找遠端的工程師試用 |

**開放問題**

- [ ] 關注公司清單從哪裡開始？（建議：既有的職缺 shortlist + GitHub 公司清單 + HN 每月新公司）
- [ ] 要不要支援中文 CV（104 職缺）？
- [x] 公開 demo 是否需要登入，還是只放假資料的唯讀版？（已決定 10/16：假資料、唯讀、不需登入）
- [ ] 日後若開放給別人，證據庫的建立方式（上傳 CV + GitHub 授權）？
