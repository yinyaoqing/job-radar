import { Input, Select } from "@/components/ui/input";
import type { Candidate } from "@/lib/eligibility";

interface Props {
  candidate: Candidate;
  countries: string[];
  onChange: (candidate: Candidate) => void;
}

const regionNames = (() => {
  try {
    return new Intl.DisplayNames(["zh-Hant"], { type: "region" });
  } catch {
    return null;
  }
})();

export function countryName(code: string): string {
  return regionNames?.of(code) ?? code;
}

export function SettingsPanel({ candidate, countries, onChange }: Props) {
  const [start, end] = candidate.availableHours;
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="text-base font-semibold">你在哪裡工作</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        用來判斷每個職缺你能不能申請。只存在這個瀏覽器，不會上傳。
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <label className="grid gap-1 text-sm">
          所在國家
          <Select
            value={candidate.country}
            onChange={(e) => onChange({ ...candidate, country: e.target.value })}
          >
            {countries.map((code) => (
              <option key={code} value={code}>
                {countryName(code)}（{code}）
              </option>
            ))}
          </Select>
        </label>
        <label className="grid gap-1 text-sm">
          時區（UTC 偏移，小時）
          <Input
            type="number"
            step={0.5}
            min={-12}
            max={14}
            value={candidate.utcOffset}
            onChange={(e) => onChange({ ...candidate, utcOffset: Number(e.target.value) })}
          />
        </label>
        <div className="grid gap-1 text-sm">
          可上線時段（當地時間）
          <div className="flex items-center gap-2">
            <Input
              aria-label="開始"
              type="number"
              min={0}
              max={24}
              value={start}
              onChange={(e) =>
                onChange({ ...candidate, availableHours: [Number(e.target.value), end] })
              }
              className="w-20"
            />
            到
            <Input
              aria-label="結束"
              type="number"
              min={0}
              max={24}
              value={end}
              onChange={(e) =>
                onChange({ ...candidate, availableHours: [start, Number(e.target.value)] })
              }
              className="w-20"
            />
          </div>
        </div>
      </div>
    </section>
  );
}
