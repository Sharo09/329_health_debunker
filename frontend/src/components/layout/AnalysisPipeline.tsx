import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

type PipelineStep = "claim" | "questions" | "evidence" | "verdict";

interface AnalysisPipelineProps {
  currentStep: PipelineStep;
  loadingStep?: PipelineStep | null;
}

const steps: Array<{ id: PipelineStep; title: string; subtitle: string }> = [
  { id: "claim", title: "Claim", subtitle: "Capture the core nutrition question" },
  { id: "questions", title: "Refining Context", subtitle: "Ask clarifying follow-up questions" },
  { id: "evidence", title: "Retrieving Evidence", subtitle: "Search and rank relevant PubMed studies" },
  { id: "verdict", title: "Generating Verdict", subtitle: "Synthesize findings into a clear result" },
];

const stepRank: Record<PipelineStep, number> = {
  claim: 0,
  questions: 1,
  evidence: 2,
  verdict: 3,
};

function AnalysisPipeline({ currentStep, loadingStep = null }: AnalysisPipelineProps) {
  return (
    <aside className="rounded-2xl border border-border bg-surface/95 backdrop-blur-sm p-4 sm:p-5 shadow-sm">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.14em] text-foreground-muted font-semibold">
          Analysis Pipeline
        </p>
        <p className="mt-1 text-sm text-foreground-muted">
          Transparent stages for every NutriEvidence verdict.
        </p>
      </div>

      <div className="space-y-3">
        {steps.map((step) => {
          const isComplete = stepRank[step.id] < stepRank[currentStep];
          const isCurrent = step.id === currentStep;
          const isLoading = step.id === loadingStep;

          return (
            <div
              key={step.id}
              className={cn(
                "relative rounded-xl border px-3.5 py-3 transition-all duration-200",
                isCurrent
                  ? "border-primary/40 bg-primary/5"
                  : "border-border bg-background/70",
                isComplete && "border-supported/30 bg-supported/5"
              )}
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex-shrink-0">
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 text-primary animate-spin" />
                  ) : isComplete ? (
                    <CheckCircle2 className="w-4 h-4 text-supported" />
                  ) : (
                    <Circle className={cn("w-4 h-4", isCurrent ? "text-primary" : "text-foreground-subtle")} />
                  )}
                </div>
                <div>
                  <p className={cn("text-sm font-semibold", isCurrent ? "text-foreground" : "text-foreground-muted")}>
                    {step.title}
                  </p>
                  <p className="text-xs text-foreground-muted leading-relaxed">{step.subtitle}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

export { AnalysisPipeline };
