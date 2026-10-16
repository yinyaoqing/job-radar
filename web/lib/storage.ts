// Personal data stays in this browser (docs/spec.md, 開源網站與商業化): settings, marks
// and the application board. Every access is guarded: storage can be blocked or full.

import { DEFAULT_CANDIDATE, type Candidate } from "./eligibility";

export type Stage = "to_apply" | "applied" | "interview" | "closed";
export type Mark = Stage | "irrelevant";

export interface SavedPosting {
  id: string;
  title: string;
  company: string;
  url: string;
  mark: Mark;
  markedAt: string;
}

/** The visitor's own answer for a posting the rules could not decide. */
export type Override = "eligible" | "blocked";

const KEYS = {
  candidate: "job-radar:candidate",
  marks: "job-radar:marks",
  lastVisit: "job-radar:last-visit",
  overrides: "job-radar:overrides",
} as const;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private mode or quota: the page keeps working, it just forgets on reload.
  }
}

export function loadCandidate(): Candidate {
  return { ...DEFAULT_CANDIDATE, ...read<Partial<Candidate>>(KEYS.candidate, {}) };
}

export function saveCandidate(candidate: Candidate): void {
  write(KEYS.candidate, candidate);
}

export function loadMarks(): Record<string, SavedPosting> {
  return read<Record<string, SavedPosting>>(KEYS.marks, {});
}

export function saveMarks(marks: Record<string, SavedPosting>): void {
  write(KEYS.marks, marks);
}

export function loadOverrides(): Record<string, Override> {
  return read<Record<string, Override>>(KEYS.overrides, {});
}

export function saveOverrides(overrides: Record<string, Override>): void {
  write(KEYS.overrides, overrides);
}

/** The previous visit's time (for "new since last visit"), then records this one. */
export function touchLastVisit(now = new Date()): string | null {
  const previous = read<string | null>(KEYS.lastVisit, null);
  write(KEYS.lastVisit, now.toISOString());
  return previous;
}
