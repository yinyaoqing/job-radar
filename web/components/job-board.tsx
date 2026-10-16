"use client";

import { Radar, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ApplicationBoard } from "@/components/application-board";
import { ELIGIBILITY_LABEL, PostingCard } from "@/components/posting-card";
import { SettingsPanel } from "@/components/settings-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { assess, DEFAULT_CANDIDATE, type Candidate, type Label } from "@/lib/eligibility";
import { type Feed, loadFeed, type Posting } from "@/lib/feed";
import {
  loadCandidate,
  loadMarks,
  loadOverrides,
  type Mark,
  type Override,
  type SavedPosting,
  saveCandidate,
  saveMarks,
  saveOverrides,
  type Stage,
  touchLastVisit,
} from "@/lib/storage";
import { daysAgo } from "@/lib/utils";

type View = "postings" | "board" | "settings";
const PAGE = 40;

export function JobBoard() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [candidate, setCandidate] = useState<Candidate>(DEFAULT_CANDIDATE);
  const [marks, setMarks] = useState<Record<string, SavedPosting>>({});
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [lastVisit, setLastVisit] = useState<string | null>(null);
  const [view, setView] = useState<View>("postings");
  const [categories, setCategories] = useState<Set<string>>(new Set());
  const [labels, setLabels] = useState<Set<Label>>(new Set(["eligible", "unclear"]));
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);

  useEffect(() => {
    setCandidate(loadCandidate());
    setMarks(loadMarks());
    setOverrides(loadOverrides());
    setLastVisit(touchLastVisit());
    loadFeed().then(setFeed, (e: Error) => setError(e.message));
  }, []);

  const categoryLabel = useMemo(
    () => Object.fromEntries((feed?.categories ?? []).map((c) => [c.id, c.label])),
    [feed],
  );

  const assessed = useMemo(
    () =>
      (feed?.postings ?? []).map((posting) => {
        const own = overrides[posting.id];
        return {
          posting,
          verdict: own
            ? { label: own, reasons: [`你已確認${own === "eligible" ? "可以" : "不能"}申請`] }
            : assess(posting, candidate, feed?.regions ?? {}),
        };
      }),
    [feed, candidate, overrides],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return assessed
      .filter(({ posting, verdict }) => {
        if (categories.size && !categories.has(posting.category)) return false;
        if (!labels.has(verdict.label)) return false;
        if (marks[posting.id]?.mark === "irrelevant") return false;
        if (q && !`${posting.title} ${posting.company} ${(posting.skills ?? []).join(" ")}`.toLowerCase().includes(q)) {
          return false;
        }
        return true;
      })
      .sort((a, b) => b.posting.first_seen_at.localeCompare(a.posting.first_seen_at));
  }, [assessed, categories, labels, marks, query]);

  const labelCounts = useMemo(() => {
    const counts: Record<Label, number> = { eligible: 0, blocked: 0, unclear: 0 };
    for (const { posting, verdict } of assessed) {
      if (!categories.size || categories.has(posting.category)) counts[verdict.label] += 1;
    }
    return counts;
  }, [assessed, categories]);

  const countries = useMemo(() => {
    const codes = new Set(Object.values(feed?.regions ?? {}).flat());
    codes.add(candidate.country);
    return [...codes].sort();
  }, [feed, candidate.country]);

  const updateCandidate = (next: Candidate) => {
    setCandidate(next);
    saveCandidate(next);
  };

  const updateMarks = (next: Record<string, SavedPosting>) => {
    setMarks(next);
    saveMarks(next);
  };

  const markPosting = (posting: Posting, mark: Mark | null) => {
    const next = { ...marks };
    if (mark === null) delete next[posting.id];
    else {
      next[posting.id] = {
        id: posting.id,
        title: posting.title,
        company: posting.company,
        url: posting.url,
        mark,
        markedAt: new Date().toISOString(),
      };
    }
    updateMarks(next);
  };

  const overridePosting = (posting: Posting, value: Override | null) => {
    const next = { ...overrides };
    if (value === null) delete next[posting.id];
    else next[posting.id] = value;
    setOverrides(next);
    saveOverrides(next);
  };

  const moveSaved = (id: string, stage: Stage | null) => {
    const next = { ...marks };
    if (stage === null) delete next[id];
    else next[id] = { ...next[id], mark: stage };
    updateMarks(next);
  };

  const toggle = <T,>(set: Set<T>, value: T) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  const saved = Object.values(marks).filter((m) => m.mark !== "irrelevant");
  const openIds = useMemo(() => new Set((feed?.postings ?? []).map((p) => p.id)), [feed]);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Radar className="size-6 text-primary" aria-hidden />
            Job Radar
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            每天到公司的 ATS 確認仍開放的全遠端職缺，並判斷你能不能申請。
          </p>
        </div>
        <nav className="flex gap-1.5" aria-label="檢視">
          <Button variant={view === "postings" ? "selected" : "ghost"} onClick={() => setView("postings")}>
            職缺
          </Button>
          <Button variant={view === "board" ? "selected" : "ghost"} onClick={() => setView("board")}>
            申請看板 {saved.length > 0 && <span className="text-muted-foreground">{saved.length}</span>}
          </Button>
          <Button variant={view === "settings" ? "selected" : "ghost"} onClick={() => setView("settings")}>
            設定
          </Button>
        </nav>
      </header>

      {error && (
        <p className="mt-6 rounded-md border border-blocked/40 bg-blocked/10 p-3 text-sm text-blocked">
          讀不到職缺資料：{error}
        </p>
      )}
      {!feed && !error && <p className="mt-6 text-sm text-muted-foreground">載入職缺中…</p>}

      {feed && view === "settings" && (
        <div className="mt-6">
          <SettingsPanel candidate={candidate} countries={countries} onChange={updateCandidate} />
        </div>
      )}

      {feed && view === "board" && (
        <div className="mt-6">
          {saved.length === 0 ? (
            <p className="text-sm text-muted-foreground">在職缺上按「會投」或「已投」，就會出現在這裡。</p>
          ) : (
            <ApplicationBoard saved={saved} openIds={openIds} onMove={moveSaved} />
          )}
        </div>
      )}

      {feed && view === "postings" && (
        <>
          <section className="mt-6 space-y-3" aria-label="篩選">
            <div className="relative">
              <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted-foreground" aria-hidden />
              <Input
                className="w-full pl-9"
                placeholder="搜尋職稱、公司或技能"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setShown(PAGE);
                }}
              />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {feed.categories
                .filter((c) => c.count > 0)
                .map((c) => (
                  <Button
                    key={c.id}
                    size="sm"
                    variant={categories.has(c.id) ? "selected" : "outline"}
                    onClick={() => {
                      setCategories(toggle(categories, c.id));
                      setShown(PAGE);
                    }}
                  >
                    {c.label} <span className="text-muted-foreground">{c.count}</span>
                  </Button>
                ))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              <span className="text-muted-foreground">顯示：</span>
              {(["eligible", "unclear", "blocked"] as Label[]).map((label) => (
                <Button
                  key={label}
                  size="sm"
                  variant={labels.has(label) ? "selected" : "outline"}
                  onClick={() => {
                    setLabels(toggle(labels, label));
                    setShown(PAGE);
                  }}
                >
                  {ELIGIBILITY_LABEL[label]} <span className="text-muted-foreground">{labelCounts[label]}</span>
                </Button>
              ))}
              <span className="ml-auto text-xs text-muted-foreground">
                以 {candidate.country}、UTC{candidate.utcOffset >= 0 ? "+" : ""}
                {candidate.utcOffset} 判斷 ·{" "}
                <button className="underline" onClick={() => setView("settings")}>
                  修改
                </button>
              </span>
            </div>
          </section>

          <p className="mt-4 text-sm text-muted-foreground">{visible.length} 個職缺</p>
          <div className="mt-2 space-y-3">
            {visible.slice(0, shown).map(({ posting, verdict }) => (
              <PostingCard
                key={posting.id}
                posting={posting}
                categoryLabel={categoryLabel[posting.category] ?? posting.category}
                verdict={verdict}
                isNew={!!lastVisit && posting.first_seen_at > lastVisit}
                mark={marks[posting.id]?.mark}
                onMark={markPosting}
                override={overrides[posting.id]}
                onOverride={overridePosting}
              />
            ))}
          </div>
          {visible.length > shown && (
            <div className="mt-4 flex justify-center">
              <Button variant="outline" onClick={() => setShown(shown + PAGE)}>
                顯示更多（還有 {visible.length - shown} 個）
              </Button>
            </div>
          )}
        </>
      )}

      {feed && (
        <footer className="mt-10 border-t pt-4 text-xs text-muted-foreground">
          <p>
            資料更新於 {daysAgo(feed.generated_at)}。是否開放以各公司 ATS 為準；本站不代為投遞。
          </p>
          <p className="mt-1">
            公司來源：
            {feed.attribution.map((a, i) => (
              <span key={a.name}>
                {i > 0 && "、"}
                <a className="underline" href={a.url} target="_blank" rel="noopener noreferrer">
                  {a.name}
                </a>
                {a.license && `（${a.license}）`}
              </span>
            ))}
          </p>
        </footer>
      )}
    </div>
  );
}
