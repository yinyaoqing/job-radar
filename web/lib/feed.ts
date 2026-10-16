// Shape of feed.json, written by worker/src/job_radar/export.py (FEED_VERSION 3).

export const FEED_VERSION = 3;

export type WorkMode = "remote" | "hybrid" | "onsite" | "unknown";

export interface LocationPolicy {
  type:
    | "worldwide"
    | "region_list"
    | "country_list"
    | "timezone_window"
    | "onsite_hybrid"
    | "unknown";
  countries?: string[];
  regions?: string[];
  timezone_window_utc?: { from_utc: number; to_utc: number } | null;
  required_overlap_hours?: number | null;
  overlap_reference_utc?: number | null;
}

export interface HardBlock {
  type: "clearance" | "citizenship";
  value: string | null;
  countries: string[];
}

export interface Salary {
  min: number | null;
  max: number | null;
  currency: string | null;
  period: "year" | "month" | "hour" | "unknown";
}

export interface Posting {
  id: string;
  company: string;
  company_website: string | null;
  company_region: string | null;
  title: string;
  category: string;
  department: string | null;
  location: string | null;
  work_mode: WorkMode;
  field_policy: LocationPolicy | null;
  /** The ATS's structured country; a fallback only (often a company-wide default). */
  ats_country?: string | null;
  url: string;
  ats: string;
  published_at: string | null;
  first_seen_at: string;
  last_verified_at: string;
  extracted: boolean;
  location_policy?: LocationPolicy | null;
  hard_blocks?: HardBlock[];
  seniority?: string;
  employment?: string;
  salary?: Salary | null;
  skills?: string[];
  no_ai_policy?: boolean;
  /** Where the company's other postings say candidates must be, when they agree. */
  company_hint?: { places: string[]; postings: number } | null;
}

export interface Category {
  id: string;
  label: string;
  count: number;
}

export interface Feed {
  version: number;
  generated_at: string;
  scope: string;
  count: number;
  categories: Category[];
  regions: Record<string, string[]>;
  attribution: { name: string; url: string; license?: string; used_for: string }[];
  postings: Posting[];
}

export function feedUrl(): string {
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return process.env.NEXT_PUBLIC_FEED_URL || `${base}/sample-feed.json`;
}

export async function loadFeed(url = feedUrl()): Promise<Feed> {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new Error(`feed: HTTP ${resp.status}`);
  const feed = (await resp.json()) as Feed;
  if (feed.version !== FEED_VERSION) {
    throw new Error(`feed version ${feed.version}, site expects ${FEED_VERSION}`);
  }
  return feed;
}
