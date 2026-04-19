import { useState } from "react";
import { ArrowLeft, ChevronRight, MessageSquare, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Alert } from "../ui/Alert";
import { cn } from "../../lib/utils";
import type { Question } from "../../api";

interface QuestionsFlowProps {
  claim: string;
  questions: Question[];
  onSubmit: (answers: Record<string, string>) => Promise<void>;
  onBack: () => void;
  isLoading: boolean;
  error: string | null;
}

function QuestionsFlow({ claim, questions, onSubmit, onBack, isLoading, error }: QuestionsFlowProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  
  const answeredCount = Object.keys(answers).filter((k) => answers[k]).length;
  const allAnswered = questions.length === 0 || answeredCount === questions.length;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSubmit(answers);
  };

  const handleAnswerChange = (slot: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [slot]: value }));
  };

  return (
    <div className="animate-fade-in max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <div className="flex items-center justify-center w-8 h-8 rounded-full bg-supported-bg text-supported">
          <CheckCircle2 className="w-4 h-4" />
        </div>
        <div className="flex-1 h-1 bg-border rounded-full overflow-hidden">
          <div 
            className="h-full bg-primary transition-all duration-300"
            style={{ width: questions.length === 0 ? "100%" : `${(answeredCount / questions.length) * 100}%` }}
          />
        </div>
        <span className="text-sm text-foreground-muted">
          {questions.length === 0 ? "Ready" : `${answeredCount}/${questions.length}`}
        </span>
      </div>

      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="text-xs font-medium text-foreground-muted uppercase tracking-wide mb-1">
            Your Claim
          </div>
          <p className="text-foreground font-medium">{claim}</p>
        </CardContent>
      </Card>

      <Card variant="elevated">
        <CardContent className="p-6 sm:p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {questions.length === 0 ? (
              <Alert variant="success">
                Your claim was specific enough - no clarifying questions needed. Click below to search for evidence.
              </Alert>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-4">
                  <MessageSquare className="w-5 h-5 text-accent" />
                  <h3 className="font-semibold text-foreground">
                    {questions.length === 1 ? "One quick question" : `${questions.length} quick questions`}
                  </h3>
                </div>
                
                <p className="text-sm text-foreground-muted mb-6">
                  Help us find the most relevant research by answering these questions:
                </p>

                <div className="space-y-5">
                  {questions.map((q, index) => (
                    <div key={q.slot} className="animate-slide-up" style={{ animationDelay: `${index * 100}ms` }}>
                      <label className="block text-sm font-medium text-foreground mb-2">
                        {q.text}
                      </label>
                      <div className="relative">
                        <select
                          value={answers[q.slot] || ""}
                          onChange={(e) => handleAnswerChange(q.slot, e.target.value)}
                          className={cn(
                            "w-full px-4 py-3 rounded-lg border bg-surface text-foreground appearance-none cursor-pointer",
                            "focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent",
                            "transition-all duration-200",
                            answers[q.slot] ? "border-supported" : "border-border"
                          )}
                        >
                          <option value="">Select an option...</option>
                          {q.option_values.map((val, i) => (
                            <option key={val} value={val}>
                              {q.option_labels[i] || val}
                            </option>
                          ))}
                        </select>
                        <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none">
                          <svg className="w-4 h-4 text-foreground-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </div>
                      </div>
                      {answers[q.slot] && (
                        <div className="mt-1.5 flex items-center gap-1 text-xs text-supported">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Selected: {q.option_labels[q.option_values.indexOf(answers[q.slot])] || answers[q.slot]}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            {error && (
              <Alert variant="error">
                {error}
              </Alert>
            )}

            <div className="flex flex-col sm:flex-row gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={onBack}
                disabled={isLoading}
              >
                <ArrowLeft className="w-4 h-4" />
                Start Over
              </Button>
              
              <Button
                type="submit"
                className="flex-1"
                disabled={!allAnswered || isLoading}
                isLoading={isLoading}
              >
                {isLoading ? "Retrieving evidence..." : "Find Evidence"}
                {!isLoading && <ChevronRight className="w-5 h-5" />}
              </Button>
            </div>
          </form>

          {isLoading && (
            <div className="mt-6 pt-6 border-t border-border rounded-xl">
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground mb-1">
                  <Loader2 className="w-4 h-4 animate-spin text-primary" />
                  Retrieving Evidence
                </div>
                <p className="text-xs text-foreground-muted">
                  Building PubMed query, ranking studies, and filtering for reliability signals.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export { QuestionsFlow };
