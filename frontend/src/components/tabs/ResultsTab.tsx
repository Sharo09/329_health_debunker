import { useState } from "react";
import { ArrowLeft, ChevronDown, ChevronUp, BookOpen, RotateCcw, Loader2, FlaskConical } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { Alert } from "../ui/Alert";
import { Spinner } from "../ui/Spinner";
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
    <div className="animate-fade-in max-w-4xl space-y-6">
      <Card>
        <CardContent className="p-5">
          <div className="text-xs font-semibold text-foreground-muted uppercase tracking-wider mb-2">
            Your Claim
          </div>
          <p className="text-lg font-semibold text-foreground mb-4">
            &quot;{claim}&quot;
          </p>

          {lockedPico && (
            <div className="flex flex-wrap gap-2">
              {lockedPico.food && (
                <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                  Food: {lockedPico.food}
                </Badge>
              )}
              {lockedPico.component && (
                <Badge variant="outline" className="bg-purple-50 text-purple-700 border-purple-200">
                  Component: {lockedPico.component}
                </Badge>
              )}
              {lockedPico.outcome && (
                <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200">
                  Outcome: {lockedPico.outcome}
                </Badge>
              )}
              {lockedPico.population && (
                <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                  Population: {lockedPico.population}
                </Badge>
              )}
              {lockedPico.form && (
                <Badge variant="outline" className="bg-gray-100 text-gray-700 border-gray-300">
                  Form: {lockedPico.form}
                </Badge>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {warning && (
        <Alert variant="warning">{warning}</Alert>
      )}

      {verdictLoading && !verdict && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="p-6 sm:p-7">
            <div className="flex items-center gap-2 mb-2 text-foreground">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              <p className="text-sm font-semibold">Generating Verdict</p>
            </div>
            <p className="text-sm text-foreground-muted mb-4">
              Reviewing {papers.length} retrieved paper{papers.length === 1 ? "" : "s"} and producing an evidence-backed
              synthesis.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="rounded-lg border border-border bg-surface px-3 py-2">
                <p className="text-xs text-foreground-muted">Step 1</p>
                <p className="text-sm font-medium text-foreground">Claim Extracted</p>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-2">
                <p className="text-xs text-foreground-muted">Step 2</p>
                <p className="text-sm font-medium text-foreground">Evidence Retrieved</p>
              </div>
              <div className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2">
                <p className="text-xs text-foreground-muted">Step 3</p>
                <p className="text-sm font-medium text-foreground flex items-center gap-1.5">
                  <FlaskConical className="w-3.5 h-3.5 text-primary" />
                  Verdict in Progress
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {verdictError && !verdict && (
        <Alert variant="error">
          Verdict synthesis failed: {verdictError}
        </Alert>
      )}

      {verdict && (
        <>
          <VerdictCard verdict={verdict} />
          
          {verdict.demographic_caveat && (
            <DemographicCaveat text={verdict.demographic_caveat} />
          )}

          <div className="pt-4">
            <div className="flex border-b border-border">
              {stanceTabs.map((tab) => {
                const isActive = tab.key === stanceTab;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setStanceTab(tab.key)}
                    className={cn(
                      "flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 -mb-px transition-colors",
                      isActive
                        ? "text-foreground border-primary"
                        : "text-foreground-muted border-transparent hover:text-foreground hover:border-border"
                    )}
                  >
                    {tab.label}
                    <span
                      className={cn(
                        "px-2 py-0.5 rounded-full text-xs font-semibold",
                        isActive ? `${tab.color} text-white` : "bg-muted text-foreground-muted"
                      )}
                    >
                      {tab.papers.length}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="mt-4 space-y-3">
              {activeStance && activeStance.papers.length === 0 ? (
                <Card className="bg-muted border-0">
                  <CardContent className="p-6 text-center">
                    <BookOpen className="w-8 h-8 text-foreground-subtle mx-auto mb-2" />
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

      {!verdictLoading && !verdictError && papers.length === 0 && !verdict && (
        <Alert variant="warning">
          No papers were retrieved and no verdict could be synthesized.
        </Alert>
      )}

      <div className="pt-4">
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="flex items-center gap-2 text-sm text-foreground-muted hover:text-foreground transition-colors"
        >
          {showDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          Retrieval Details
        </button>

        {showDetails && (
          <div className="mt-4 animate-fade-in">
            <div className="grid grid-cols-3 gap-4 mb-4">
              <Card className="bg-muted border-0">
                <CardContent className="p-4 text-center">
                  <div className="text-2xl font-bold text-foreground">{papers.length}</div>
                  <div className="text-xs text-foreground-muted">Papers Retrieved</div>
                  <div className="text-xs text-foreground-subtle">of {totalHits} total</div>
                </CardContent>
              </Card>
              <Card className={cn("border-0", papers.some((p) => p.is_retracted) ? "bg-orange-50" : "bg-muted")}>
                <CardContent className="p-4 text-center">
                  <div className={cn("text-2xl font-bold", papers.some((p) => p.is_retracted) ? "text-orange-600" : "text-foreground")}>
                    {papers.filter((p) => p.is_retracted).length}
                  </div>
                  <div className="text-xs text-foreground-muted">Retracted</div>
                  <div className="text-xs text-foreground-subtle">flagged papers</div>
                </CardContent>
              </Card>
              <Card className="bg-muted border-0">
                <CardContent className="p-4 text-center">
                  <div className="text-2xl font-bold text-foreground">
                    {papers.filter((p) => p.pub_types.some((t) => t.includes("Randomized"))).length}
                  </div>
                  <div className="text-xs text-foreground-muted">RCTs Found</div>
                  <div className="text-xs text-foreground-subtle">randomized trials</div>
                </CardContent>
              </Card>
            </div>

            <div className="mb-4">
              <div className="text-xs text-foreground-muted mb-2">PubMed Query (final)</div>
              <code className="block bg-muted rounded-lg p-3 text-xs text-foreground-muted break-all leading-relaxed font-mono">
                {queryUsed || "—"}
              </code>
            </div>

            {papers.length > 0 && (
              <div>
                <button
                  onClick={() => setShowAllPapers(!showAllPapers)}
                  className="flex items-center gap-2 text-sm text-foreground-muted hover:text-foreground mb-3"
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

      <div className="flex flex-col sm:flex-row gap-3 pt-6 border-t border-border">
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
