// Port of worker/src/job_radar/eligibility.py (judge_policy + assess) over feed fields.
// lib/eligibility.test.ts runs the region trap set through it, so the two cannot drift.

import type { HardBlock, LocationPolicy, Posting } from "./feed";

export type Label = "eligible" | "blocked" | "unclear";

export interface Candidate {
  country: string;
  utcOffset: number;
  /** Local hours the candidate is willing to be online, 24h clock. */
  availableHours: [number, number];
}

export interface Assessment {
  label: Label;
  reasons: string[];
}

export const DEFAULT_CANDIDATE: Candidate = {
  country: "TW",
  utcOffset: 8,
  availableHours: [8, 23],
};

type Verdict = [Label, string];
type Regions = Record<string, string[]>;

const signed = (n: number) => (n >= 0 ? `+${n}` : `${n}`);

const REGION_LABELS: Record<string, string> = {
  EU: "歐盟",
  EEA: "歐洲經濟區",
  EUROPE: "歐洲",
  UK: "英國",
  EMEA: "歐洲、中東與非洲",
  NORTH_AMERICA: "北美",
  LATAM: "拉丁美洲",
  AMERICAS: "美洲",
  APAC: "亞太",
  ASIA: "亞洲",
  OCEANIA: "大洋洲",
  AFRICA: "非洲",
  MIDDLE_EAST: "中東",
  DACH: "德奧瑞",
  NORDICS: "北歐",
  BENELUX: "比荷盧",
};

function placeNames(countries: string[], regions: string[]): string {
  return [...regions.map((r) => REGION_LABELS[r] ?? r), ...[...countries].sort()].join("、");
}

function candidateRegions(candidate: Candidate, regions: Regions): Set<string> {
  return new Set(
    Object.entries(regions)
      .filter(([, members]) => members.includes(candidate.country))
      .map(([name]) => name),
  );
}

export function overlapHours(candidate: Candidate, referenceUtc: number): number {
  const shift = candidate.utcOffset - referenceUtc;
  const [start, end] = candidate.availableHours;
  let best = 0;
  for (const day of [-24, 0, 24]) {
    best = Math.max(best, Math.min(end, 17 + shift + day) - Math.max(start, 9 + shift + day));
  }
  return Math.max(0, best);
}

export function hasTimeLimit(policy: LocationPolicy | null | undefined): boolean {
  if (!policy) return false;
  const w = policy.timezone_window_utc;
  return (w?.from_utc != null && w?.to_utc != null) || !!policy.required_overlap_hours;
}

export function judgePolicy(policy: LocationPolicy, candidate: Candidate, regions: Regions): Verdict {
  const kind = policy.type ?? "unknown";
  if (kind === "onsite_hybrid") return ["blocked", "需要進辦公室"];
  if (kind === "unknown" && !hasTimeLimit(policy)) return ["unclear", "沒有說明可申請地區"];

  let label: Label = "eligible";
  let reason = "不限地區";
  if (kind === "country_list" || kind === "region_list") {
    const countries = policy.countries ?? [];
    const named = policy.regions ?? [];
    const mine = candidateRegions(candidate, regions);
    const allowed = countries.includes(candidate.country) || named.some((r) => mine.has(r));
    const names = placeNames(countries, named);
    if (!allowed) return ["blocked", `限 ${names}`];
    reason = `可申請地區包含 ${candidate.country}（${names}）`;
  }

  const window = policy.timezone_window_utc;
  if (window) {
    const { from_utc: lo, to_utc: hi } = window;
    if (lo != null && hi != null) {
      if (candidate.utcOffset < lo || candidate.utcOffset > hi) {
        return ["blocked", `限時區 UTC${signed(lo)} 到 UTC${signed(hi)}`];
      }
      label = "eligible";
      reason = `時區 UTC${signed(lo)} 到 UTC${signed(hi)} 包含 UTC${signed(candidate.utcOffset)}`;
    } else if (kind === "timezone_window") {
      return ["unclear", "時區範圍不完整"];
    }
  }

  let hours = policy.required_overlap_hours;
  const reference = policy.overlap_reference_utc;
  // More than 12 hours a day is impossible: the posting meant hours per week.
  const weekly = !!hours && hours > 12 && hours <= 60;
  if (weekly && hours) hours = hours / 5;
  if (hours) {
    if (reference == null) return ["unclear", `要求重疊 ${hours} 小時，但沒說和哪個時區`];
    const overlap = overlapHours(candidate, reference);
    if (overlap < hours) {
      return ["blocked", `要求與 UTC${signed(reference)} 重疊 ${hours} 小時，只能重疊 ${overlap} 小時`];
    }
    reason += `；與 UTC${signed(reference)} 可重疊 ${overlap} 小時`;
    if (weekly) reason += "（每週時數換算成每日）";
  } else if (kind === "timezone_window" && !window) {
    // A time-zone limit without offsets is still a limit; never read it as "anywhere".
    return ["unclear", "有時區限制，但沒有可判斷的範圍"];
  }
  if (kind === "unknown") {
    // Time limits still block when the place is unknown; passing them does not make it known.
    return ["unclear", `沒有說明可申請地區（時區條件符合：${reason.replace(/^不限地區；/, "")}）`];
  }
  return [label, reason];
}

function hardBlock(blocks: HardBlock[] | undefined, candidate: Candidate): string | null {
  for (const block of blocks ?? []) {
    if (block.type === "clearance") return `需要安全許可：${block.value}`;
    if (block.type === "citizenship" && !block.countries.includes(candidate.country)) {
      return `需要特定國籍：${block.value}`;
    }
  }
  return null;
}

export function assess(posting: Posting, candidate: Candidate, regions: Regions): Assessment {
  if (posting.work_mode === "onsite" || posting.work_mode === "hybrid") {
    return { label: "blocked", reasons: ["不是全遠端"] };
  }
  const fromText = posting.field_policy;
  const textVerdict = fromText ? judgePolicy(fromText, candidate, regions) : null;
  const policy = posting.location_policy;
  const jdVerdict =
    policy && (policy.type !== "unknown" || hasTimeLimit(policy))
      ? judgePolicy(policy, candidate, regions)
      : null;

  const blocked = hardBlock(posting.hard_blocks, candidate);
  if (blocked) return { label: "blocked", reasons: [blocked] };

  // A bare "Worldwide" field is a board default; only a field naming places can conflict.
  const textIsSpecific = !!fromText && fromText.type !== "worldwide";
  if (jdVerdict && textVerdict) {
    const disagree = jdVerdict[0] !== textVerdict[0];
    if (disagree && textIsSpecific && jdVerdict[0] !== "unclear" && textVerdict[0] !== "unclear") {
      return {
        label: "unclear",
        reasons: [`職缺內文：${jdVerdict[1]}`, `ATS 地點欄位「${posting.location}」：${textVerdict[1]}`],
      };
    }
    if (jdVerdict[0] === "unclear") return { label: textVerdict[0], reasons: [textVerdict[1]] };
    return { label: jdVerdict[0], reasons: [jdVerdict[1]] };
  }
  if (jdVerdict) return { label: jdVerdict[0], reasons: [jdVerdict[1]] };
  if (textVerdict) return { label: textVerdict[0], reasons: [`依 ATS 地點欄位：${textVerdict[1]}`] };
  if (posting.ats_country) {
    // Last resort: the ATS's structured country, often a company-wide default.
    const [label, reason] = judgePolicy(
      { type: "country_list", countries: [posting.ats_country] },
      candidate,
      regions,
    );
    return { label, reasons: [`內文與地點欄位都沒寫；ATS 設定的國家：${reason}`] };
  }
  return {
    label: "unclear",
    reasons: [posting.extracted ? "沒有說明可申請地區" : "尚未分析職缺內文"],
  };
}
