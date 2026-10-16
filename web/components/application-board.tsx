import { AlertTriangle, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { SavedPosting, Stage } from "@/lib/storage";

const STAGES: { id: Stage; label: string }[] = [
  { id: "to_apply", label: "待投" },
  { id: "applied", label: "已投" },
  { id: "interview", label: "面試" },
  { id: "closed", label: "結束" },
];

interface Props {
  saved: SavedPosting[];
  openIds: Set<string>;
  onMove: (id: string, stage: Stage | null) => void;
}

export function ApplicationBoard({ saved, openIds, onMove }: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-4">
      {STAGES.map((stage, index) => {
        const items = saved.filter((s) => s.mark === stage.id);
        return (
          <section key={stage.id} className="rounded-lg border bg-muted/50 p-3">
            <h3 className="mb-2 text-sm font-semibold">
              {stage.label} <span className="text-muted-foreground">{items.length}</span>
            </h3>
            <ul className="space-y-2">
              {items.map((item) => {
                // Spec: an applied posting that closed on the ATS gets a warning.
                const closed = !openIds.has(item.id) && stage.id !== "closed";
                return (
                  <li key={item.id} className="rounded-md border bg-card p-2.5 text-sm">
                    <p className="text-xs text-muted-foreground">{item.company}</p>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium hover:underline"
                    >
                      {item.title}
                      <ExternalLink className="size-3" aria-hidden />
                    </a>
                    {closed && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-blocked">
                        <AlertTriangle className="size-3" aria-hidden />
                        已在 ATS 關閉
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-1">
                      {index > 0 && (
                        <Button size="sm" variant="ghost" onClick={() => onMove(item.id, STAGES[index - 1].id)}>
                          ← {STAGES[index - 1].label}
                        </Button>
                      )}
                      {index < STAGES.length - 1 && (
                        <Button size="sm" variant="outline" onClick={() => onMove(item.id, STAGES[index + 1].id)}>
                          {STAGES[index + 1].label} →
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => onMove(item.id, null)}>
                        移除
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
