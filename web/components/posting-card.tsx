import { ExternalLink, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Assessment } from "@/lib/eligibility";
import type { Posting } from "@/lib/feed";
import type { Mark } from "@/lib/storage";
import { cn, daysAgo, formatSalary } from "@/lib/utils";

export const ELIGIBILITY_LABEL = { eligible: "可申請", blocked: "地區受限", unclear: "待確認" } as const;

const SENIORITY = {
  intern: "實習",
  junior: "初階",
  mid: "中階",
  senior: "資深",
  staff: "Staff",
  principal: "Principal",
} as Record<string, string>;

interface Props {
  posting: Posting;
  categoryLabel: string;
  verdict: Assessment;
  isNew: boolean;
  mark?: Mark;
  onMark: (posting: Posting, mark: Mark | null) => void;
}

export function PostingCard({ posting, categoryLabel, verdict, isNew, mark, onMark }: Props) {
  const toggle = (next: Mark) => onMark(posting, mark === next ? null : next);
  return (
    <article
      className={cn(
        "rounded-lg border bg-card p-4 shadow-xs transition-opacity",
        mark === "irrelevant" && "opacity-50",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{posting.company}</p>
          <h3 className="text-base font-semibold leading-snug">{posting.title}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {isNew && <Badge variant="new">新</Badge>}
          <Badge variant={verdict.label}>{ELIGIBILITY_LABEL[verdict.label]}</Badge>
        </div>
      </div>

      <p className="mt-1 text-sm text-muted-foreground">
        {[categoryLabel, posting.seniority && SENIORITY[posting.seniority], posting.location]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <p className="mt-2 text-sm">{verdict.reasons.join("；")}</p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {posting.salary && <Badge>{formatSalary(posting.salary)}</Badge>}
        {(posting.skills ?? []).slice(0, 5).map((skill) => (
          <Badge key={skill}>{skill}</Badge>
        ))}
        {posting.no_ai_policy && (
          <Badge variant="blocked">
            <ShieldAlert className="size-3" aria-hidden />
            表單禁止使用 AI
          </Badge>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant={mark === "to_apply" ? "selected" : "outline"} onClick={() => toggle("to_apply")}>
            會投
          </Button>
          <Button size="sm" variant={mark === "applied" ? "selected" : "outline"} onClick={() => toggle("applied")}>
            已投
          </Button>
          <Button size="sm" variant={mark === "irrelevant" ? "selected" : "ghost"} onClick={() => toggle("irrelevant")}>
            不相關
          </Button>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {daysAgo(posting.last_verified_at)}確認仍開放
          </span>
          <Button size="sm" asChild>
            <a href={posting.url} target="_blank" rel="noopener noreferrer">
              到 ATS 申請
              <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </Button>
        </div>
      </div>
    </article>
  );
}
