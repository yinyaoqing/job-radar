# web

Job Radar 的公開網站：Next.js 靜態輸出 + Tailwind（shadcn/ui 風格元件）。讀 `feed.json`，依領域篩選全遠端職缺，並在瀏覽器裡判斷訪客所在地區能否申請。

- 個人資料（所在地、標記、申請看板）只存在訪客自己的瀏覽器（localStorage）。
- `lib/eligibility.ts` 是 `worker/src/job_radar/eligibility.py` 的移植；`lib/eligibility.test.ts` 用地區陷阱集確認兩邊結果一致。
- 沒設定 `NEXT_PUBLIC_FEED_URL` 時讀 `public/sample-feed.json`（虛構公司，由 `job-radar export --sample` 產生）。

```bash
npm ci
npm run dev          # http://localhost:3000
npm test             # 資格判斷與 Python 一致
npm run build        # 輸出到 out/
```

部署：`.github/workflows/web.yml` 在 main 上建置並發布到 GitHub Pages（需要在 repo 設定開啟 Pages，並設 `PAGES_ENABLED=true` 變數）；正式 feed 的網址設在 `FEED_URL` 變數。

用真實資料在本機看（先用 worker 匯出 feed）：

```bash
cd worker && uv run job-radar export --out ../web/public/feed.json   # public/feed.json 不進版控
cd ../web
NEXT_PUBLIC_FEED_URL=/feed.json npm run build   # Windows Git Bash 要加 MSYS_NO_PATHCONV=1，否則 /feed.json 會被改成 C:/Program Files/Git/feed.json
npx serve out                                    # http://localhost:3000
```
