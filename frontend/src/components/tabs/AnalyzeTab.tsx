import { useState } from "react";
import { Search, ChevronRight, User } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Alert } from "../ui/Alert";
import { Spinner } from "../ui/Spinner";
import { cn } from "../../lib/utils";

interface AnalyzeTabProps {
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

function AnalyzeTab({ onStartAnalysis, isLoading, error }: AnalyzeTabProps) {
  const [claim, setClaim] = useState("");
  const [age, setAge] = useState("");

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
      {/* Hero Section */}
      <section className="text-center py-16 sm:py-24">
        <div className="max-w-3xl mx-auto px-4">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 bg-surface-muted border border-border px-4 py-2 rounded-full text-xs font-medium tracking-widest text-foreground-muted mb-8">
            <span className="w-2 h-2 rounded-full bg-primary"></span>
            PUBMED SYNCHRONIZED RESEARCH PIPELINE
          </div>
          
          {/* Main Headline */}
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-serif text-foreground mb-4 leading-tight">
            Scientific clarity for
          </h1>
          <h2 className="text-4xl sm:text-5xl lg:text-6xl font-serif italic text-primary mb-8">
            health narratives.
          </h2>
          
          <p className="text-foreground-muted text-lg sm:text-xl leading-relaxed max-w-2xl mx-auto">
            We bridge the gap between wellness trends and clinical reality. Our AI-driven pipeline parses thousands of peer-reviewed sources from the NCBI database to deliver definitive results.
          </p>
        </div>
      </section>

      {/* Main Input Card */}
      <Card variant="elevated" className="max-w-2xl mx-auto">
        <CardContent className="p-6 sm:p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Claim Input */}
            <div>
              <label htmlFor="claim" className="block text-sm font-semibold text-foreground mb-2">
                Your claim or question
              </label>
              <div className="relative">
                <Search className="absolute left-4 top-4 w-5 h-5 text-foreground-subtle" />
                <textarea
                  id="claim"
                  rows={3}
                  value={claim}
                  onChange={(e) => setClaim(e.target.value)}
                  placeholder="e.g. Is turmeric good for inflammation?"
                  className={cn(
                    "w-full pl-12 pr-4 py-3 rounded-2xl border bg-surface text-foreground placeholder:text-foreground-subtle",
                    "focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary",
                    "resize-none transition-all duration-200",
                    error ? "border-unsupported" : "border-border"
                  )}
                />
              </div>
            </div>

            {/* Age Input */}
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
                  "w-32 px-4 py-2.5 rounded-xl border border-border bg-surface text-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary",
                  "placeholder:text-foreground-subtle transition-all duration-200"
                )}
              />
              <p className="mt-1.5 text-xs text-foreground-subtle">
                Helps find studies relevant to your demographic
              </p>
            </div>

            {/* Error Display */}
            {error && (
              <Alert variant="error">
                {error}
              </Alert>
            )}

            {/* Submit Button */}
            <Button
              type="submit"
              size="lg"
              disabled={!claim.trim() || isLoading}
              isLoading={isLoading}
              className="w-full"
            >
              {isLoading ? "Analyzing claim..." : "Analyze Your Claim"}
              {!isLoading && <Search className="w-5 h-5" />}
            </Button>
          </form>

          {/* Loading State */}
          {isLoading && (
            <div className="mt-6 pt-6 border-t border-border">
              <Spinner 
                message="Extracting claim details..."
                submessage="This may take a few seconds"
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Trust Badge */}
      <div className="max-w-2xl mx-auto mt-8 flex items-center justify-center gap-4">
        <div className="flex -space-x-2">
          <div className="w-8 h-8 rounded-full bg-surface-muted border-2 border-surface flex items-center justify-center text-xs font-medium text-foreground-muted">JD</div>
          <div className="w-8 h-8 rounded-full bg-surface-muted border-2 border-surface flex items-center justify-center text-xs font-medium text-foreground-muted">SR</div>
          <div className="w-8 h-8 rounded-full bg-surface-muted border-2 border-surface flex items-center justify-center text-xs font-medium text-foreground-muted">MK</div>
        </div>
        <span className="text-xs font-medium tracking-widest text-foreground-muted uppercase">
          Trusted by Clinical Researchers
        </span>
      </div>

      {/* Example Claims */}
      {!isLoading && (
        <div className="max-w-2xl mx-auto mt-12">
          <p className="text-sm text-foreground-muted text-center mb-4">
            Try an example:
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {exampleClaims.map((example) => (
              <button
                key={example}
                onClick={() => handleExampleClick(example)}
                className={cn(
                  "px-4 py-2 text-sm rounded-full border transition-all duration-200",
                  "border-border text-foreground-muted hover:border-primary hover:text-primary hover:bg-primary/5"
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
