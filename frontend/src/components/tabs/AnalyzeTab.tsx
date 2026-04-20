import { useEffect, useState } from "react";
import { Search, Sparkles, ChevronRight, User, ShieldCheck } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Alert } from "../ui/Alert";
import { cn } from "../../lib/utils";

interface AnalyzeTabProps {
  initialClaim?: string;
  onStartAnalysis: (claim: string, age?: number) => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

const exampleClaims = [
  "Is turmeric good for inflammation?",
  "Does drinking coffee increase anxiety?",
  "Can omega-3 supplements improve heart health?",
  "Is green tea effective for weight loss?",
];

function AnalyzeTab({ initialClaim = "", onStartAnalysis, isLoading, error }: AnalyzeTabProps) {
  const [claim, setClaim] = useState(initialClaim);
  const [age, setAge] = useState("");

  // Sync the textarea when a parent-level claim change comes in — e.g.
  // the user clicked an entry in Common Claims or History.
  useEffect(() => {
    if (initialClaim) setClaim(initialClaim);
  }, [initialClaim]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!claim.trim()) return;
    await onStartAnalysis(claim.trim(), age ? Number(age) : undefined);
  };

  const handleExampleClick = (example: string) => {
    setClaim(example);
  };

  return (
    <div className="animate-fade-in">
      <section className="text-center py-8 sm:py-12">
        <div className="max-w-3xl mx-auto px-2">
          <div className="inline-flex items-center gap-2 border border-border bg-surface px-4 py-1.5 rounded-full text-xs sm:text-sm font-semibold text-foreground-muted mb-6">
            <Sparkles className="w-4 h-4" />
            PubMed-synchronized research workflow
          </div>

          <h2 className="text-4xl sm:text-5xl font-[family-name:var(--font-display)] font-semibold text-foreground mb-4 text-balance leading-tight">
            Scientific clarity for
            <span className="block text-primary-light italic font-medium">food and nutrition narratives.</span>
          </h2>

          <p className="text-foreground-muted text-base sm:text-lg leading-relaxed max-w-2xl mx-auto">
            Turn everyday health claims into transparent, evidence-backed verdicts with a guided
            question flow and peer-reviewed supporting papers.
          </p>
        </div>
      </section>

      <Card variant="elevated" className="max-w-3xl mx-auto border-primary/10 shadow-lg">
        <CardContent className="p-6 sm:p-8 space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-foreground">Analyze your claim</p>
            <div className="inline-flex items-center gap-2 text-xs text-foreground-muted bg-muted px-3 py-1.5 rounded-full">
              <ShieldCheck className="w-3.5 h-3.5 text-supported" />
              Transparent, citation-first synthesis
            </div>
          </div>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="claim" className="block text-sm font-semibold text-foreground mb-2">
                Your claim or question
              </label>
              <div className="relative">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-foreground-subtle" />
                <textarea
                  id="claim"
                  rows={3}
                  value={claim}
                  onChange={(e) => setClaim(e.target.value)}
                  placeholder="e.g. Is turmeric good for inflammation?"
                  className={cn(
                    "w-full pl-12 pr-4 py-3 rounded-lg border bg-surface text-foreground placeholder:text-foreground-subtle",
                    "focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent",
                    "resize-none transition-all duration-200",
                    error ? "border-unsupported" : "border-border"
                  )}
                />
              </div>
            </div>

            <div>
              <label htmlFor="age" className="block text-sm font-semibold text-foreground mb-2">
                <span className="flex items-center gap-2">
                  <User className="w-4 h-4 text-foreground-muted" />
                  Your age
                  <span className="font-normal text-foreground-muted">(optional)</span>
                </span>
              </label>
              <input
                id="age"
                type="number"
                value={age}
                onChange={(e) => setAge(e.target.value)}
                placeholder="e.g. 25"
                min={1}
                max={120}
                className={cn(
                  "w-32 px-4 py-2.5 rounded-lg border border-border bg-surface text-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent",
                  "placeholder:text-foreground-subtle transition-all duration-200"
                )}
              />
              <p className="mt-1.5 text-xs text-foreground-subtle">
                Optional context to prioritize age-relevant studies
              </p>
            </div>

            {error && (
              <Alert variant="error">
                {error}
              </Alert>
            )}

            <Button
              type="submit"
              size="lg"
              disabled={!claim.trim() || isLoading}
              isLoading={isLoading}
              className="w-full sm:w-auto sm:min-w-56"
            >
              {isLoading ? "Extracting claim..." : "Analyze your claim"}
              {!isLoading && <ChevronRight className="w-5 h-5" />}
            </Button>
          </form>
        </CardContent>
      </Card>

      {!isLoading && (
        <div className="max-w-3xl mx-auto mt-8">
          <p className="text-sm text-foreground-muted text-center mb-3">
            Try an example:
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {exampleClaims.map((example) => (
              <button
                key={example}
                onClick={() => handleExampleClick(example)}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-full border transition-all duration-200",
                  "border-border text-foreground-muted hover:border-accent hover:text-accent hover:bg-accent/5"
                )}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export { AnalyzeTab };
