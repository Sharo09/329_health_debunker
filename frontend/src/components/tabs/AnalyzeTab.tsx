import { useState } from "react";
import { Search, Sparkles, ChevronRight, User } from "lucide-react";
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
      <section className="text-center py-10 sm:py-14">
        <div className="max-w-2xl mx-auto px-4">
          <div className="inline-flex items-center gap-2 bg-accent/10 text-accent-dark px-4 py-1.5 rounded-full text-sm font-medium mb-6">
            <Sparkles className="w-4 h-4" />
            Powered by PubMed Research
          </div>
          
          <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4 text-balance">
            Verify nutrition claims with peer-reviewed science
          </h2>
          
          <p className="text-foreground-muted text-lg leading-relaxed">
            Enter any food or nutrition health claim and we&apos;ll search the biomedical
            literature to find supporting or contradicting evidence.
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
                  "w-32 px-4 py-2.5 rounded-lg border border-border bg-surface text-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent",
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
              {isLoading ? "Analyzing claim..." : "Analyze Claim"}
              {!isLoading && <ChevronRight className="w-5 h-5" />}
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

      {/* Example Claims */}
      {!isLoading && (
        <div className="max-w-2xl mx-auto mt-8">
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
