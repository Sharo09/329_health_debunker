import { useState } from "react";
import { ArrowLeft, ChevronDown, ChevronUp, BookOpen, RotateCcw } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { Alert } from "../ui/Alert";
import { LoadingScreen } from "../ui/LoadingScreen";
import { VerdictCard, DemographicCaveat } from "../results/VerdictCard";
import { CitedPaperCard, RawPaperCard } from "../results/PaperCard";
import { cn } from "../../lib/utils";
import type { Verdict, Paper, CitedPaper } from "../../api";

interface LockedPico {
  food: string | null;
  outcome: string | null;
  population: string | null;
  form: string | null;
  component: string | null;
}

interface ResultsTabProps {
  claim: string;
  lockedPico: LockedPico | null;
  papers: Paper[];
  queryUsed: string;
  totalHits: number;
  warning: string | null;
  verdict: Verdict | null;
  verdictLoading: boolean;
  verdictError: string | null;
  onNewClaim: () => void;
  onChangeAnswers: () => void;
}

type StanceTab = "supporting" | "contradicting" | "neutral";

function ResultsTab({
  claim,
  lockedPico,
  papers,
  queryUsed,
  totalHits,
  warning,
  verdict,
  verdictLoading,
  verdictError,
  onNewClaim,
  onChangeAnswers,
}: ResultsTabProps) {
  const [stanceTab, setStanceTab] = useState<StanceTab>("supporting");
  const [showDetails, setShowDetails] = useState(false);
  const [showAllPapers, setShowAllPapers] = useState(false);

  const stanceTabs: Array<{ key: StanceTab; label: string; papers: CitedPaper[]; color: string }> = verdict
    ? [
        { key: "supporting", label: "Supporting", papers: verdict.supporting_papers, color: "bg-supported" },
        { key: "contradicting", label: "Contradicting", papers: verdict.contradicting_papers, color: "bg-unsupported" },
        { key: "neutral", label: "Neutral", papers: verdict.neutral_papers, color: "bg-insufficient" },
      ]
    : [];

  const activeStance = stanceTabs.find((t) => t.key === stanceTab);

  return (
    <div className="animate-fade-in max-w-3xl mx-auto space-y-6">
      {/* Claim Header */}
      <Card className="border-0 bg-surface-muted rounded-2xl">
        <CardContent className="p-6">
          <div className="text-xs font-medium tracking-widest text-foreground-muted uppercase mb-2">
            Your Claim
          </div>
          <p className="text-xl font-serif text-foreground mb-4">
            &quot;{claim}&quot;
          </p>

          {lockedPico && (
            <div className="flex flex-wrap gap-2">
              {lockedPico.food && (
                <Badge variant="outline" className="bg-surface text-primary border-primary/30">
                  Food: {lockedPico.food}
                </Badge>
              )}
              {lockedPico.component && (
                <Badge variant="outline" className="bg-surface text-primary border-primary/30">
                  Component: {lockedPico.component}
                </Badge>
              )}
              {lockedPico.outcome && (
                <Badge variant="outline" className="bg-surface text-mixed border-mixed/30">
                  Outcome: {lockedPico.outcome}
                </Badge>
              )}
              {lockedPico.population && (
                <Badge variant="outline" className="bg-surface text-foreground-muted border-border">
                  Population: {lockedPico.population}
                </Badge>
              )}
              {lockedPico.form && (
                <Badge variant="outline" className="bg-surface text-foreground-muted border-border">
                  Form: {lockedPico.form}
                </Badge>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Warning */}
      {warning && (
        <Alert variant="warning">{warning}</Alert>
      )}

      {/* Verdict Loading */}
      {verdictLoading && !verdict && (
        <LoadingScreen 
          message="Synthesizing Evidence..."
          submessage={`Analyzing ${papers.length} paper${papers.length === 1 ? "" : "s"} for verdict`}
        />
      )}

      {/* Verdict Error */}
      {verdictError && !verdict && (
        <Alert variant="error">
          Verdict synthesis failed: {verdictError}
        </Alert>
      )}

      {/* Verdict Display */}
      {verdict && (
        <>
          <VerdictCard verdict={verdict} />
          
          {verdict.demographic_caveat && (
            <DemographicCaveat text={verdict.demographic_caveat} />
          )}

          {/* Stance Tabs */}
          <div className="pt-4">
            <div className="flex border-b border-border">
              {stanceTabs.map((tab) => {
                const isActive = tab.key === stanceTab;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setStanceTab(tab.key)}
                    className={cn(
                      "flex items-center gap-2 px-5 py-3.5 text-sm font-medium border-b-2 -mb-px transition-colors",
                      isActive
                        ? "text-foreground border-primary"
                        : "text-foreground-muted border-transparent hover:text-foreground hover:border-border"
                    )}
                  >
                    {tab.label}
                    <span
                      className={cn(
                        "px-2.5 py-0.5 rounded-full text-xs font-semibold",
                        isActive ? `${tab.color} text-surface` : "bg-surface-muted text-foreground-muted"
                      )}
                    >
                      {tab.papers.length}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Papers List */}
            <div className="mt-5 space-y-3">
              {activeStance && activeStance.papers.length === 0 ? (
                <Card className="bg-surface-muted border-0 rounded-2xl">
                  <CardContent className="p-8 text-center">
                    <BookOpen className="w-10 h-10 text-foreground-subtle mx-auto mb-3" />
                    <p className="text-foreground-muted">
                      No {activeStance.label.toLowerCase()} papers cited in this verdict.
                    </p>
                  </CardContent>
                </Card>
              ) : (
                activeStance?.papers.map((p) => (
                  <CitedPaperCard key={p.paper_id} paper={p} />
                ))
              )}
            </div>
          </div>
        </>
      )}

      {/* No papers, no verdict, not loading */}
      {!verdictLoading && !verdictError && papers.length === 0 && !verdict && (
        <Alert variant="warning">
          No papers were retrieved and no verdict could be synthesized.
        </Alert>
      )}

      {/* Retrieval Details (Collapsible) */}
      <div className="pt-4">
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="flex items-center gap-2 text-sm font-medium text-foreground-muted hover:text-foreground transition-colors"
        >
          {showDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          Retrieval Details
        </button>

        {showDetails && (
          <div className="mt-5 animate-fade-in">
            {/* Stats Grid */}
            <div className="grid grid-cols-3 gap-4 mb-5">
              <Card className="bg-surface-muted border-0 rounded-xl">
                <CardContent className="p-4 text-center">
                  <div className="text-2xl font-bold text-foreground">{papers.length}</div>
                  <div className="text-xs text-foreground-muted">Papers Retrieved</div>
                  <div className="text-xs text-foreground-subtle">of {totalHits} total</div>
                </CardContent>
              </Card>
              <Card className={cn("border-0 rounded-xl", papers.some((p) => p.is_retracted) ? "bg-mixed-bg" : "bg-surface-muted")}>
                <CardContent className="p-4 text-center">
                  <div className={cn("text-2xl font-bold", papers.some((p) => p.is_retracted) ? "text-mixed" : "text-foreground")}>
                    {papers.filter((p) => p.is_retracted).length}
                  </div>
                  <div className="text-xs text-foreground-muted">Retracted</div>
                  <div className="text-xs text-foreground-subtle">flagged papers</div>
                </CardContent>
              </Card>
              <Card className="bg-surface-muted border-0 rounded-xl">
                <CardContent className="p-4 text-center">
                  <div className="text-2xl font-bold text-foreground">
                    {papers.filter((p) => p.pub_types.some((t) => t.includes("Randomized"))).length}
                  </div>
                  <div className="text-xs text-foreground-muted">RCTs Found</div>
                  <div className="text-xs text-foreground-subtle">randomized trials</div>
                </CardContent>
              </Card>
            </div>

            {/* Query Used */}
            <div className="mb-5">
              <div className="text-xs font-medium tracking-widest text-foreground-muted uppercase mb-2">
                PubMed Query (final)
              </div>
              <code className="block bg-surface-muted rounded-xl p-4 text-xs text-foreground-muted break-all leading-relaxed font-mono">
                {queryUsed || "—"}
              </code>
            </div>

            {/* All Papers */}
            {papers.length > 0 && (
              <div>
                <button
                  onClick={() => setShowAllPapers(!showAllPapers)}
                  className="flex items-center gap-2 text-sm font-medium text-foreground-muted hover:text-foreground mb-3"
                >
                  {showAllPapers ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  All {papers.length} retrieved papers (pre-synthesis)
                </button>

                {showAllPapers && (
                  <div className="space-y-3 animate-fade-in">
                    {papers.map((p) => (
                      <RawPaperCard key={p.pmid} paper={p} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 pt-8 border-t border-border">
        <Button variant="outline" onClick={onNewClaim}>
          <ArrowLeft className="w-4 h-4" />
          New Claim
        </Button>
        <Button variant="outline" onClick={onChangeAnswers}>
          <RotateCcw className="w-4 h-4" />
          Change Answers
        </Button>
      </div>
    </div>
  );
}

export { ResultsTab };
