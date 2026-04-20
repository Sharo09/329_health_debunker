// frontend/src/App.tsx
import { useState, useCallback, useEffect } from "react";
import {
  checkPlausibility,
  extractClaim,
  finalizeClaim,
  synthesizeClaim,
  Question,
  Paper,
  PlausibilityResponse,
  Verdict,
} from "./api";

// Layout Components
import { Header } from "./components/layout/Header";
import { AnalysisPipeline } from "./components/layout/AnalysisPipeline";
import { Tabs, type TabId } from "./components/layout/Tabs";
import { Footer } from "./components/layout/Footer";

// Tab Components
import { AnalyzeTab } from "./components/tabs/AnalyzeTab";
import { QuestionsFlow } from "./components/tabs/QuestionsFlow";
import { ResultsTab } from "./components/tabs/ResultsTab";
import { CommonClaimsTab } from "./components/tabs/CommonClaimsTab";
import { HistoryTab, type HistoryEntry } from "./components/tabs/HistoryTab";
import { AboutTab } from "./components/tabs/AboutTab";
import { PlausibilityBlocked, FailureCard } from "./components/tabs/PlausibilityBlocked";
import { Alert } from "./components/ui/Alert";

// Types
interface LockedPico {
  food: string | null;
  outcome: string | null;
  population: string | null;
  form: string | null;
  component: string | null;
}

type Stage = "input" | "plausibility_blocked" | "questions" | "results";

// History storage key
const HISTORY_KEY = "nutrievidence_history";

function loadHistory(): HistoryEntry[] {
  try {
    const stored = localStorage.getItem(HISTORY_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return parsed.map((entry: HistoryEntry) => ({
      ...entry,
      timestamp: new Date(entry.timestamp),
    }));
  } catch {
    return [];
  }
}

function saveHistory(history: HistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch {
    // Ignore storage errors
  }
}

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState<TabId>("analyze");
  const [stage, setStage] = useState<Stage>("input");

  // Loading & Error States
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Input Stage
  const [claim, setClaim] = useState("");
  const [age, setAge] = useState<number | undefined>(undefined);

  // Questions Stage
  const [partialPico, setPartialPico] = useState<Record<string, unknown> | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);

  // Plausibility Stage (Station 1.5)
  const [plausibility, setPlausibility] = useState<PlausibilityResponse | null>(null);
  const [plausibilityOverride, setPlausibilityOverride] = useState(false);

  // Results Stage
  const [papers, setPapers] = useState<Paper[]>([]);
  const [queryUsed, setQueryUsed] = useState("");
  const [totalHits, setTotalHits] = useState(0);
  const [warning, setWarning] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [verdictLoading, setVerdictLoading] = useState(false);
  const [verdictError, setVerdictError] = useState<string | null>(null);
  const [lockedPico, setLockedPico] = useState<LockedPico | null>(null);

  // History
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());

  // Update history in localStorage when it changes
  useEffect(() => {
    saveHistory(history);
  }, [history]);

  // Check if we have results to show
  const hasResults = papers.length > 0 || verdict !== null;

  // Reset all state
  const reset = useCallback(() => {
    setStage("input");
    setError(null);
    setPartialPico(null);
    setQuestions([]);
    setPapers([]);
    setQueryUsed("");
    setTotalHits(0);
    setWarning(null);
    setVerdict(null);
    setVerdictLoading(false);
    setVerdictError(null);
    setLockedPico(null);
    setPlausibility(null);
    setPlausibilityOverride(false);
  }, []);

  // Handle starting analysis from input
  const handleStartAnalysis = useCallback(async (inputClaim: string, inputAge?: number) => {
    if (!inputClaim.trim()) return;

    setClaim(inputClaim);
    setAge(inputAge);
    setError(null);
    setPlausibility(null);
    setPlausibilityOverride(false);
    setLoading(true);

    try {
      const data = await extractClaim(inputClaim.trim());

      if (!data.is_food_claim) {
        setError(data.scope_rejection_reason || "This claim is outside scope (food claims only).");
        setLoading(false);
        return;
      }

      setPartialPico(data.partial_pico);
      setQuestions(data.questions);

      // Station 1.5 — gate the claim before elicitation. Fail open on any
      // endpoint error: a backend outage should never brick the UI.
      let plaus: PlausibilityResponse | null = null;
      try {
        plaus = await checkPlausibility({ partial_pico: data.partial_pico });
        setPlausibility(plaus);
      } catch {
        setPlausibility(null);
      }

      if (plaus && !plaus.should_proceed_to_pipeline) {
        setStage("plausibility_blocked");
      } else {
        setStage("questions");
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Something went wrong during extraction.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  // "Search anyway" from the plausibility-blocked panel.
  const handleProceedAnyway = useCallback(() => {
    setPlausibilityOverride(true);
    setStage("questions");
  }, []);

  // Handle running the analysis after questions
  const handleRunAnalysis = useCallback(async (answers: Record<string, string>) => {
    if (!partialPico) return;

    setError(null);
    setVerdict(null);
    setVerdictError(null);
    setLoading(true);

    let retrieval;
    try {
      retrieval = await finalizeClaim({
        partial_pico: partialPico,
        answers,
        age,
      });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Something went wrong during retrieval.";
      setError(message);
      setLoading(false);
      return;
    }

    // Phase A complete — show retrieved papers + locked PICO
    setPapers(retrieval.papers);
    setQueryUsed(retrieval.query_used);
    setTotalHits(retrieval.total_pubmed_hits);
    setWarning(retrieval.warning || null);
    setLockedPico({
      food: retrieval.locked_food,
      outcome: retrieval.locked_outcome,
      population: retrieval.locked_population,
      form: retrieval.locked_form,
      component: retrieval.locked_component,
    });
    setStage("results");
    setActiveTab("results");
    setLoading(false);

    if (retrieval.papers.length === 0) return;

    // Phase B — verdict (background)
    setVerdictLoading(true);
    try {
      const syn = await synthesizeClaim({
        partial_pico: partialPico,
        answers,
        age,
        papers: retrieval.papers,
      });
      setVerdict(syn.verdict);

      // Add to history
      const newEntry: HistoryEntry = {
        id: crypto.randomUUID(),
        claim,
        verdict: syn.verdict.verdict,
        papersCount: retrieval.papers.length,
        timestamp: new Date(),
      };
      setHistory((prev) => [newEntry, ...prev.slice(0, 49)]); // Keep last 50
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Verdict synthesis failed.";
      setVerdictError(message);
    } finally {
      setVerdictLoading(false);
    }
  }, [partialPico, age, claim]);

  // Handle selecting a claim from common claims or history
  const handleSelectClaim = useCallback((selectedClaim: string) => {
    reset();
    setClaim(selectedClaim);
    setActiveTab("analyze");
  }, [reset]);

  // Handle selecting a history entry
  const handleSelectHistoryEntry = useCallback((entry: HistoryEntry) => {
    reset();
    setClaim(entry.claim);
    setActiveTab("analyze");
  }, [reset]);

  // Handle clearing history
  const handleClearHistory = useCallback(() => {
    setHistory([]);
  }, []);

  // Handle tab changes
  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    
    // If switching to analyze tab, reset to input stage if we're not in results
    if (tab === "analyze" && stage !== "results") {
      setStage("input");
    }
  }, [stage]);

  // Handle new claim from results
  const handleNewClaim = useCallback(() => {
    reset();
    setClaim("");
    setActiveTab("analyze");
  }, [reset]);

  // Handle change answers from results
  const handleChangeAnswers = useCallback(() => {
    setStage("questions");
    setActiveTab("analyze");
  }, []);

  // Render current tab content
  const renderTabContent = () => {
    switch (activeTab) {
      case "analyze":
        if (stage === "plausibility_blocked" && plausibility) {
          return (
            <PlausibilityBlocked
              claim={claim}
              plausibility={plausibility}
              onModify={reset}
              onProceedAnyway={handleProceedAnyway}
            />
          );
        }
        if (stage === "questions") {
          const hasFailures = plausibility && plausibility.failures.length > 0;
          return (
            <div>
              {/* Plausibility warnings — non-blocking concerns above the questions. */}
              {hasFailures && !plausibilityOverride && (
                <div className="max-w-3xl mx-auto mb-4">
                  <Alert variant="warning">
                    <div className="font-semibold mb-2">Plausibility warnings</div>
                    {plausibility!.failures.map((f, i) => (
                      <FailureCard key={i} failure={f} />
                    ))}
                  </Alert>
                </div>
              )}
              {/* Override — user chose "Search anyway" despite a block. */}
              {hasFailures && plausibilityOverride && (
                <div className="max-w-3xl mx-auto mb-4">
                  <Alert variant="error">
                    <div className="font-semibold mb-2">
                      Searching anyway despite a plausibility block
                    </div>
                    <p className="mb-2">
                      You chose to proceed after we flagged this claim. The
                      evidence below will be gathered for completeness, but
                      may not directly address the concern.
                    </p>
                    {plausibility!.failures.map((f, i) => (
                      <FailureCard key={i} failure={f} />
                    ))}
                  </Alert>
                </div>
              )}
              <QuestionsFlow
                claim={claim}
                questions={questions}
                onSubmit={handleRunAnalysis}
                onBack={reset}
                isLoading={loading}
                error={error}
              />
            </div>
          );
        }
        return (
          <AnalyzeTab
            initialClaim={claim}
            onStartAnalysis={handleStartAnalysis}
            isLoading={loading}
            error={error}
          />
        );

      case "common":
        return <CommonClaimsTab onSelectClaim={handleSelectClaim} />;

      case "history":
        return (
          <HistoryTab
            history={history}
            onSelectEntry={handleSelectHistoryEntry}
            onClearHistory={handleClearHistory}
            onNewClaim={handleNewClaim}
          />
        );

      case "results":
        return (
          <ResultsTab
            claim={claim}
            lockedPico={lockedPico}
            papers={papers}
            queryUsed={queryUsed}
            totalHits={totalHits}
            warning={warning}
            verdict={verdict}
            verdictLoading={verdictLoading}
            verdictError={verdictError}
            onNewClaim={handleNewClaim}
            onChangeAnswers={handleChangeAnswers}
          />
        );

      case "about":
        return <AboutTab />;

      default:
        return null;
    }
  };

  const getPipelineStep = (): "claim" | "questions" | "evidence" | "verdict" => {
    if (activeTab === "results") {
      return verdictLoading || verdict ? "verdict" : "evidence";
    }
    if (stage === "questions") return loading ? "evidence" : "questions";
    return "claim";
  };

  const pipelineStep = getPipelineStep();
  const loadingStep = loading
    ? stage === "questions"
      ? "evidence"
      : "claim"
    : verdictLoading
      ? "verdict"
      : null;
  const showPipeline = activeTab === "analyze" || activeTab === "results";

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <Header />
      <Tabs 
        activeTab={activeTab} 
        onTabChange={handleTabChange} 
        hasResults={hasResults} 
      />
      
      <main className="flex-1 py-8 px-4 sm:px-6">
        <div className="max-w-6xl mx-auto">
          {showPipeline ? (
            <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 items-start">
              <div className="lg:sticky lg:top-28">
                <AnalysisPipeline currentStep={pipelineStep} loadingStep={loadingStep} />
              </div>
              <div>{renderTabContent()}</div>
            </div>
          ) : (
            renderTabContent()
          )}
        </div>
      </main>
      
      <Footer />
    </div>
  );
}
