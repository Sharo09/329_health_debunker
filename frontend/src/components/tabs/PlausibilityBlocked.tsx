import { AlertTriangle, ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import type { PlausibilityFailure, PlausibilityResponse } from "../../api";

interface PlausibilityBlockedProps {
  claim: string;
  plausibility: PlausibilityResponse;
  onModify: () => void;
  onProceedAnyway: () => void;
}

const FAILURE_LABELS: Record<PlausibilityFailure["failure_type"], string> = {
  F1_dose: "Dose issue",
  F2_feasibility: "Feasibility issue",
  F3_mechanism: "Mechanism issue",
  F4_frame: "Framing issue",
};

function FailureCard({ failure }: { failure: PlausibilityFailure }) {
  const label = FAILURE_LABELS[failure.failure_type] || failure.failure_type;
  const data = failure.supporting_data || {};

  return (
    <Card variant="outline" className="mb-3 border-red-300 bg-unsupported-bg">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="font-semibold text-red-900">{label}</span>
          <Badge
            variant={failure.severity === "blocking" ? "unsupported" : "mixed"}
            className="uppercase tracking-wide"
          >
            {failure.severity}
          </Badge>
          <span className="text-xs text-red-900/60">{failure.failure_type}</span>
        </div>
        <p className="text-sm text-red-900 leading-relaxed">{failure.reasoning}</p>

        {failure.failure_type === "F1_dose" && data.stated_value != null && (
          <div className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-red-900">
            <div className="opacity-75">Stated intake</div>
            <div className="font-semibold">
              {data.stated_value} {data.unit}
            </div>
            {Array.isArray(data.typical_range) && (
              <>
                <div className="opacity-75">Typical adult range</div>
                <div className="font-semibold">
                  {data.typical_range[0]}–{data.typical_range[1]} {data.unit}
                </div>
              </>
            )}
            {data.harmful_threshold != null && (
              <>
                <div className="opacity-75">Harmful threshold</div>
                <div className="font-semibold">
                  {data.harmful_threshold} {data.unit}
                </div>
              </>
            )}
            {data.implausibly_high != null && data.harmful_threshold == null && (
              <>
                <div className="opacity-75">Implausibly high</div>
                <div className="font-semibold">
                  {data.implausibly_high} {data.unit}
                </div>
              </>
            )}
            {data.source && (
              <>
                <div className="opacity-75">Source</div>
                <div className="text-xs opacity-85">{data.source}</div>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PlausibilityBlocked({
  claim,
  plausibility,
  onModify,
  onProceedAnyway,
}: PlausibilityBlockedProps) {
  return (
    <div className="animate-fade-in max-w-3xl mx-auto">
      <Card variant="elevated" className="mb-6 border-red-300 bg-unsupported-bg">
        <CardContent className="p-6">
          <div className="flex items-center gap-2 text-red-900">
            <AlertTriangle className="w-5 h-5" />
            <span className="text-xs font-bold uppercase tracking-wider">
              Plausibility issue detected
            </span>
          </div>
          <h2 className="text-2xl font-serif font-semibold text-red-900 mt-2">
            This claim may not be worth investigating empirically
          </h2>
          <div className="mt-3">
            <div className="text-xs text-red-900/60 uppercase tracking-wide">
              Your claim
            </div>
            <p className="text-red-900 font-medium italic mt-1">"{claim}"</p>
          </div>
        </CardContent>
      </Card>

      <p className="text-foreground-muted mb-4">
        We detected the following issues before starting the literature review:
      </p>

      {plausibility.failures.map((f, i) => (
        <FailureCard key={i} failure={f} />
      ))}

      <div className="flex flex-wrap gap-3 mt-6">
        <Button variant="primary" onClick={onModify}>
          <ArrowLeft className="w-4 h-4" />
          Modify my claim
        </Button>
        <Button variant="outline" onClick={onProceedAnyway}>
          Search anyway
          <ArrowRight className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}

export { PlausibilityBlocked, FailureCard };
