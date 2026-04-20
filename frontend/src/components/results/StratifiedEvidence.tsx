import { useState } from "react";
import { ChevronDown, ChevronRight, Layers } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { cn } from "../../lib/utils";
import type {
  PaperStratification,
  StratifierSlot,
  StratumBucket,
  StratumMatch,
  StratumVerdict,
} from "../../api";

interface StratifiedEvidenceProps {
  buckets: StratumBucket[];
  stratifications: PaperStratification[];
}

// ---- Labels ----

const SLOT_LABELS: Record<StratifierSlot, string> = {
  dose: "dose",
  form: "form",
  frequency: "frequency",
  population: "population",
};

const STRATUM_LABELS: Record<StratumMatch, string> = {
  matches: "Studies matching your value",
  higher: "Studies at higher values",
  lower: "Studies at lower values",
  different: "Studies on a different value",
  unreported: "Didn't report this",
  not_applicable: "Not applicable",
};

// Order in which to render strata within a bucket. "matches" leads
// because it's the direct-applicability bucket the user cares most
// about; "unreported" trails because it's the least informative.
const STRATUM_ORDER: StratumMatch[] = [
  "matches",
  "higher",
  "lower",
  "different",
  "unreported",
  "not_applicable",
];

const VERDICT_BADGE: Record<
  StratumVerdict,
  { label: string; variant: "supported" | "unsupported" | "insufficient" | "default" }
> = {
  supported: { label: "supported", variant: "supported" },
  contradicted: { label: "contradicted", variant: "unsupported" },
  insufficient_evidence: { label: "insufficient evidence", variant: "insufficient" },
  empty: { label: "no papers", variant: "default" },
};

// ---- Per-paper inline row ----

function StratifiedPaperRow({
  stratification,
  slot,
}: {
  stratification: PaperStratification;
  slot: StratifierSlot;
}) {
  const studied = (() => {
    switch (slot) {
      case "dose": return stratification.dose_studied;
      case "form": return stratification.form_studied;
      case "frequency": return stratification.frequency_studied;
      case "population": return stratification.population_studied;
    }
  })();
  return (
    <li className="text-sm text-foreground-muted flex items-start gap-2">
      <span className="text-foreground-subtle font-mono text-xs mt-0.5">
        PMID {stratification.paper_id}
      </span>
      {studied && (
        <span className="text-foreground">
          — studied <span className="font-medium">{studied}</span>
        </span>
      )}
    </li>
  );
}

// ---- Stratum row (within one bucket) ----

function StratumRow({
  stratum,
  paperIds,
  count,
  verdict,
  reasoning,
  stratifications,
  slot,
}: {
  stratum: StratumMatch;
  paperIds: string[];
  count: number;
  verdict: StratumVerdict | undefined;
  reasoning: string | undefined;
  stratifications: PaperStratification[];
  slot: StratifierSlot;
}) {
  const [expanded, setExpanded] = useState(false);
  const label = STRATUM_LABELS[stratum];
  const verdictBadge = verdict ? VERDICT_BADGE[verdict] : null;
  const strats = stratifications.filter((s) =>
    paperIds.includes(s.paper_id)
  );

  const accent = stratum === "matches"
    ? "bg-primary"
    : stratum === "unreported"
      ? "bg-foreground-subtle"
      : "bg-mixed";

  return (
    <div className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "w-full flex items-center gap-3 py-3 text-left",
          "hover:bg-muted/50 transition-colors px-2 -mx-2 rounded"
        )}
      >
        <span
          className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", accent)}
          aria-hidden
        />
        <span className="flex-1 text-sm text-foreground">
          <span className="font-medium">{label}</span>
          <span className="text-foreground-muted ml-2">
            {count} paper{count === 1 ? "" : "s"}
          </span>
          {reasoning && (
            <span className="text-foreground-subtle ml-2 text-xs">
              — {reasoning}
            </span>
          )}
        </span>
        {verdictBadge && (
          <Badge variant={verdictBadge.variant} className="flex-shrink-0">
            {verdictBadge.label}
          </Badge>
        )}
        {strats.length > 0 && (
          expanded
            ? <ChevronDown className="w-4 h-4 text-foreground-subtle flex-shrink-0" />
            : <ChevronRight className="w-4 h-4 text-foreground-subtle flex-shrink-0" />
        )}
      </button>
      {expanded && strats.length > 0 && (
        <ul className="space-y-1 pl-7 pb-3">
          {strats.map((s) => (
            <StratifiedPaperRow key={s.paper_id} stratification={s} slot={slot} />
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- Bucket (one stratifier slot) ----

function BucketBlock({
  bucket,
  stratifications,
}: {
  bucket: StratumBucket;
  stratifications: PaperStratification[];
}) {
  const entries = STRATUM_ORDER
    .map((stratum) => {
      const paperIds = bucket.strata[stratum] ?? [];
      if (paperIds.length === 0) return null;
      return {
        stratum,
        paperIds,
        count: bucket.counts[stratum] ?? paperIds.length,
        verdict: bucket.stratum_verdicts[stratum],
        reasoning: bucket.stratum_reasoning[stratum],
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  // If every paper lands in "unreported" for this slot, the bucket is
  // not informative — render a one-line note instead.
  const allUnreported = entries.length === 1 && entries[0].stratum === "unreported";
  const slotLabel = SLOT_LABELS[bucket.slot];

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">
          Your {slotLabel}
        </p>
        {bucket.user_value && (
          <p className="text-sm font-semibold text-foreground">
            {bucket.user_value}
          </p>
        )}
      </div>
      {allUnreported ? (
        <p className="text-sm text-foreground-muted italic">
          Papers don't report {slotLabel} consistently; can't stratify on this
          slot.
        </p>
      ) : (
        <div>
          {entries.map((e) => (
            <StratumRow
              key={e.stratum}
              stratum={e.stratum}
              paperIds={e.paperIds}
              count={e.count}
              verdict={e.verdict}
              reasoning={e.reasoning}
              stratifications={stratifications}
              slot={bucket.slot}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Top-level component ----

function StratifiedEvidence({
  buckets,
  stratifications,
}: StratifiedEvidenceProps) {
  // If the user didn't answer any stratifier question, Station 4 emits
  // no buckets — skip the whole section rather than showing an empty
  // heading.
  if (!buckets || buckets.length === 0) return null;

  return (
    <Card variant="elevated">
      <CardContent className="p-6 space-y-6">
        <div className="flex items-center gap-2 text-foreground">
          <Layers className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold uppercase tracking-wider">
            Evidence by your specific question
          </h3>
        </div>
        {buckets.map((b) => (
          <BucketBlock
            key={b.slot}
            bucket={b}
            stratifications={stratifications}
          />
        ))}
      </CardContent>
    </Card>
  );
}

export { StratifiedEvidence };
