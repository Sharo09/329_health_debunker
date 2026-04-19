import { useState } from "react";
import { ArrowLeft, ChevronRight, CheckCircle2 } from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Alert } from "../ui/Alert";
import { LoadingScreen } from "../ui/LoadingScreen";
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
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  
  const answeredCount = Object.keys(answers).filter((k) => answers[k]).length;
  const allAnswered = questions.length === 0 || answeredCount === questions.length;
  const currentQuestion = questions[currentQuestionIndex];
  const progress = questions.length === 0 ? 100 : ((currentQuestionIndex + 1) / questions.length) * 100;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSubmit(answers);
  };

  const handleOptionSelect = (slot: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [slot]: value }));
    // Auto-advance to next question after selection
    if (currentQuestionIndex < questions.length - 1) {
      setTimeout(() => {
        setCurrentQuestionIndex(currentQuestionIndex + 1);
      }, 300);
    }
  };

  const goToPreviousQuestion = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(currentQuestionIndex - 1);
    }
  };

  // Show loading screen when submitting
  if (isLoading) {
    return <LoadingScreen submessage="Searching PubMed for Evidence" />;
  }

  // No questions needed - ready to search
  if (questions.length === 0) {
    return (
      <div className="animate-fade-in max-w-2xl mx-auto">
        <Card variant="elevated">
          <CardContent className="p-8 text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-supported-bg flex items-center justify-center">
              <CheckCircle2 className="w-8 h-8 text-supported" />
            </div>
            <h2 className="text-2xl font-serif text-foreground mb-3">
              Your claim is ready
            </h2>
            <p className="text-foreground-muted mb-8">
              Your claim was specific enough - no clarifying questions needed. Click below to search for evidence.
            </p>
            
            {error && (
              <Alert variant="error" className="mb-6 text-left">
                {error}
              </Alert>
            )}

            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button variant="outline" onClick={onBack}>
                <ArrowLeft className="w-4 h-4" />
                Start Over
              </Button>
              <Button onClick={handleSubmit}>
                Find Evidence
                <ChevronRight className="w-5 h-5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in max-w-3xl mx-auto">
      {/* Progress Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium tracking-widest text-foreground-muted uppercase">
            Refining Search Scope
          </span>
          <span className="text-sm text-foreground-muted">
            Step {currentQuestionIndex + 1} of {questions.length}
          </span>
        </div>
        
        {/* Progress Bar */}
        <div className="h-1.5 bg-surface-muted rounded-full overflow-hidden">
          <div 
            className="h-full bg-primary transition-all duration-500 ease-out rounded-full"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Question Card */}
      <Card className="bg-surface-muted border-0 rounded-3xl overflow-hidden">
        <CardContent className="p-8 sm:p-12">
          {/* Claim Display */}
          <div className="mb-8 pb-8 border-b border-border">
            <span className="text-xs font-medium tracking-widest text-foreground-subtle uppercase">
              Analyzing
            </span>
            <p className="text-foreground font-medium mt-1">{claim}</p>
          </div>

          {/* Current Question */}
          <form onSubmit={handleSubmit}>
            <h2 className="text-2xl sm:text-3xl font-serif text-foreground mb-2 leading-snug">
              {currentQuestion.text}
            </h2>
            
            {/* Decorative line */}
            <div className="w-16 h-0.5 bg-primary/30 mb-8" />

            {/* Options as cards */}
            <div className="space-y-4">
              {currentQuestion.option_values.map((val, i) => {
                const isSelected = answers[currentQuestion.slot] === val;
                const label = currentQuestion.option_labels[i] || val;
                
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => handleOptionSelect(currentQuestion.slot, val)}
                    className={cn(
                      "w-full flex items-center justify-between p-5 sm:p-6 rounded-2xl border-2 transition-all duration-200 text-left group",
                      isSelected 
                        ? "border-primary bg-surface shadow-md" 
                        : "border-border bg-surface hover:border-primary/50 hover:shadow-sm"
                    )}
                  >
                    <span className={cn(
                      "text-lg font-medium transition-colors",
                      isSelected ? "text-primary" : "text-foreground-muted group-hover:text-foreground"
                    )}>
                      {label}
                    </span>
                    
                    <div className={cn(
                      "w-10 h-10 rounded-full flex items-center justify-center transition-all duration-200",
                      isSelected 
                        ? "bg-primary text-surface" 
                        : "border border-border text-foreground-subtle group-hover:border-primary/50"
                    )}>
                      <ChevronRight className="w-5 h-5" />
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Error Display */}
            {error && (
              <Alert variant="error" className="mt-6">
                {error}
              </Alert>
            )}

            {/* Navigation */}
            <div className="flex items-center justify-between mt-10 pt-6 border-t border-border">
              <Button
                type="button"
                variant="ghost"
                onClick={currentQuestionIndex > 0 ? goToPreviousQuestion : onBack}
              >
                <ArrowLeft className="w-4 h-4" />
                {currentQuestionIndex > 0 ? "Previous" : "Start Over"}
              </Button>

              {allAnswered && (
                <Button type="submit">
                  Find Evidence
                  <ChevronRight className="w-5 h-5" />
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Question navigation dots */}
      {questions.length > 1 && (
        <div className="flex items-center justify-center gap-2 mt-6">
          {questions.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentQuestionIndex(idx)}
              disabled={idx > answeredCount}
              className={cn(
                "w-2.5 h-2.5 rounded-full transition-all duration-200",
                idx === currentQuestionIndex
                  ? "bg-primary w-8"
                  : idx < currentQuestionIndex || answers[questions[idx].slot]
                    ? "bg-primary/40 hover:bg-primary/60"
                    : "bg-border"
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export { QuestionsFlow };
