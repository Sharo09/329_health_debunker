// frontend/src/App.tsx
import { useState } from "react";
import {
  extractClaim,
  finalizeClaim,
  synthesizeClaim,
  Question,
  Paper,
  CitedPaper,
  Verdict,
} from "./api";

// ---- Verdict display palette ----

const VERDICT_STYLES: Record<
  Verdict["verdict"],
  { label: string; bg: string; border: string; text: string; bar: string }
> = {
  supported: {
    label: "Supported by evidence",
    bg: "#ecfdf5",
    border: "#6ee7b7",
    text: "#065f46",
    bar: "#10b981",
  },
  contradicted: {
    label: "Contradicted by evidence",
    bg: "#fef2f2",
    border: "#fca5a5",
    text: "#991b1b",
    bar: "#ef4444",
  },
  insufficient_evidence: {
    label: "Insufficient evidence",
    bg: "#f1f5f9",
    border: "#cbd5e1",
    text: "#334155",
    bar: "#64748b",
  },
};

const STANCE_BADGE: Record<string, { bg: string; text: string }> = {
  supports: { bg: "#dcfce7", text: "#166534" },
  contradicts: { bg: "#fee2e2", text: "#991b1b" },
  neutral: { bg: "#f1f5f9", text: "#475569" },
  unclear: { bg: "#fef3c7", text: "#854d0e" },
};

// ---- Verdict block ----

function VerdictHeader({ verdict }: { verdict: Verdict }) {
  const style = VERDICT_STYLES[verdict.verdict];
  const pct = Math.round(verdict.confidence_percent);
  return (
    <div
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: 12,
        padding: 20,
        marginBottom: 20,
      }}
    >
      <div style={{ fontSize: 13, color: style.text, fontWeight: 600, letterSpacing: 0.5 }}>
        VERDICT
      </div>
      <div style={{ fontSize: 24, color: style.text, fontWeight: 700, marginTop: 4 }}>
        {style.label}
      </div>

      {/* Confidence bar */}
      <div style={{ marginTop: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 12,
            color: style.text,
            marginBottom: 4,
          }}
        >
          <span>Confidence</span>
          <span style={{ fontWeight: 600 }}>{pct}%</span>
        </div>
        <div
          style={{
            height: 8,
            background: "rgba(0,0,0,0.08)",
            borderRadius: 999,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              background: style.bar,
              transition: "width 500ms ease",
            }}
          />
        </div>
      </div>

      {verdict.verdict_reasoning && (
        <p
          style={{
            marginTop: 16,
            marginBottom: 0,
            fontSize: 14,
            lineHeight: 1.6,
            color: style.text,
          }}
        >
          {verdict.verdict_reasoning}
        </p>
      )}
    </div>
  );
}

function DemographicCaveat({ text }: { text: string }) {
  return (
    <div
      style={{
        background: "#fffbea",
        border: "1px solid #facc15",
        borderRadius: 10,
        padding: "10px 14px",
        marginBottom: 16,
        fontSize: 14,
        color: "#713f12",
      }}
    >
      <span style={{ fontWeight: 600 }}>Demographic caveat — </span>
      {text}
    </div>
  );
}

function CitedPaperCard({ paper }: { paper: CitedPaper }) {
  const stance = STANCE_BADGE[paper.stance] || STANCE_BADGE.unclear;
  const rel = Math.round(paper.relevance_score * 100);
  return (
    <div
      style={{
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: 14,
        marginBottom: 10,
        background: "white",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <span
          style={{
            background: stance.bg,
            color: stance.text,
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: 0.5,
            padding: "2px 8px",
            borderRadius: 999,
            textTransform: "uppercase",
          }}
        >
          {paper.stance}
        </span>
        <span style={{ fontSize: 12, color: "#64748b" }}>
          Relevance {rel}%
        </span>
        {paper.demographic_match && (
          <span
            style={{
              background: "#e0f2fe",
              color: "#075985",
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 999,
            }}
          >
            demographic match
          </span>
        )}
      </div>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        {paper.url ? (
          <a href={paper.url} target="_blank" rel="noreferrer" style={{ color: "#0f172a", textDecoration: "none" }}>
            {paper.title}
          </a>
        ) : (
          paper.title
        )}
      </div>
      {paper.one_line_summary && (
        <div style={{ fontSize: 13, color: "#475569", lineHeight: 1.5 }}>
          {paper.one_line_summary}
        </div>
      )}
      <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>PMID {paper.paper_id}</div>
    </div>
  );
}

// ---- Small reusable components ----

function Spinner() {
  return (
    <div style={{ textAlign: "center", padding: "40px 0", color: "#666" }}>
      <div style={{
        display: "inline-block", width: 32, height: 32,
        border: "3px solid #ddd", borderTop: "3px solid #333",
        borderRadius: "50%", animation: "spin 0.8s linear infinite",
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <p style={{ marginTop: 12 }}>Working — this may take 20–40 seconds…</p>
    </div>
  );
}

function Alert({ text, kind }: { text: string; kind: "error" | "warning" | "info" }) {
  const colors = {
    error:   { bg: "#fff0f0", border: "#ffcdd2", text: "#b71c1c" },
    warning: { bg: "#fffbea", border: "#ffe082", text: "#6d4c00" },
    info:    { bg: "#f0f7ff", border: "#bbdefb", text: "#0d47a1" },
  }[kind];
  return (
    <div style={{
      background: colors.bg, border: `1px solid ${colors.border}`,
      color: colors.text, borderRadius: 10, padding: "12px 16px", marginBottom: 16,
    }}>
      {text}
    </div>
  );
}

function PaperCard({ paper }: { paper: Paper }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{
      border: "1px solid #e0e0e0", borderRadius: 10, padding: 16,
      marginBottom: 12, background: paper.is_retracted ? "#fff8f0" : "#fff",
    }}>
      {paper.is_retracted && (
        <span style={{
          background: "#ff6f00", color: "white", fontSize: 11,
          padding: "2px 8px", borderRadius: 20, marginBottom: 8, display: "inline-block",
        }}>
          ⚠ RETRACTED
        </span>
      )}
      <div style={{ fontWeight: 600, marginBottom: 6 }}>
        <a href={paper.pubmed_url} target="_blank" rel="noreferrer"
          style={{ color: "#1565c0", textDecoration: "none" }}>
          {paper.title}
        </a>
      </div>
      <div style={{ fontSize: 13, color: "#555", marginBottom: 6 }}>
        {paper.journal}{paper.pub_year ? ` · ${paper.pub_year}` : ""}
        {paper.pub_types.length > 0 && (
          <span style={{
            marginLeft: 8, background: "#e8f5e9", color: "#2e7d32",
            padding: "1px 8px", borderRadius: 20, fontSize: 11,
          }}>
            {paper.pub_types[0]}
          </span>
        )}
      </div>
      {paper.abstract && (
        <>
          <p style={{ fontSize: 14, color: "#333", margin: "6px 0", lineHeight: 1.5 }}>
            {expanded ? paper.abstract : paper.abstract.slice(0, 200) + (paper.abstract.length > 200 ? "…" : "")}
          </p>
          {paper.abstract.length > 200 && (
            <button onClick={() => setExpanded(!expanded)}
              style={{ background: "none", border: "none", color: "#1565c0", cursor: "pointer", fontSize: 13, padding: 0 }}>
              {expanded ? "Show less" : "Read more"}
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ---- Main App ----

type Stage = "input" | "questions" | "results";

export default function App() {
  const [stage, setStage] = useState<Stage>("input");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Stage: input
  const [claim, setClaim] = useState("");
  const [age, setAge] = useState("");

  // Stage: questions
  const [partialPico, setPartialPico] = useState<Record<string, any> | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // Stage: results
  const [papers, setPapers] = useState<Paper[]>([]);
  const [queryUsed, setQueryUsed] = useState("");
  const [totalHits, setTotalHits] = useState(0);
  const [warning, setWarning] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [verdictLoading, setVerdictLoading] = useState(false);
  const [verdictError, setVerdictError] = useState<string | null>(null);
  const [stanceTab, setStanceTab] = useState<"supporting" | "contradicting" | "neutral">(
    "supporting"
  );

  // Locked PICO summary (echoed back from /api/finalize) to display
  // alongside the claim in the results header.
  const [lockedPico, setLockedPico] = useState<{
    food: string | null;
    outcome: string | null;
    population: string | null;
    form: string | null;
    component: string | null;
  } | null>(null);

  const reset = () => {
    setStage("input");
    setError("");
    setPartialPico(null);
    setQuestions([]);
    setAnswers({});
    setPapers([]);
    setQueryUsed("");
    setTotalHits(0);
    setWarning(null);
    setVerdict(null);
    setVerdictLoading(false);
    setVerdictError(null);
    setLockedPico(null);
    setStanceTab("supporting");
  };

  // Step 1: extract claim → get questions
  const handleStartAnalysis = async () => {
    if (!claim.trim()) return;
    setError("");
    setLoading(true);
    try {
      const data = await extractClaim(claim.trim());
      if (!data.is_food_claim) {
        setError(data.scope_rejection_reason || "This claim is outside scope (food claims only).");
        setLoading(false);
        return;
      }
      setPartialPico(data.partial_pico);
      setQuestions(data.questions);
      setStage("questions");
    } catch (e: any) {
      setError(e.message || "Something went wrong during extraction.");
    } finally {
      setLoading(false);
    }
  };

  // Step 2: streaming flow.
  //   Phase A — /api/finalize: retrieval. Show papers as soon as it returns.
  //   Phase B — /api/synthesize: verdict. Runs in the background; the
  //             verdict block shows a placeholder spinner until it lands.
  const handleRunAnalysis = async () => {
    if (!partialPico) return;
    setError("");
    setVerdict(null);
    setVerdictError(null);
    setLoading(true);

    let retrieval;
    try {
      retrieval = await finalizeClaim({
        partial_pico: partialPico,
        answers,
        age: age ? Number(age) : undefined,
      });
    } catch (e: any) {
      setError(e.message || "Something went wrong during retrieval.");
      setLoading(false);
      return;
    }

    // Phase A complete — show retrieved papers + locked PICO.
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
    setLoading(false);

    if (retrieval.papers.length === 0) return;   // nothing to synthesize

    // Phase B — verdict (background).
    setVerdictLoading(true);
    try {
      const syn = await synthesizeClaim({
        partial_pico: partialPico,
        answers,
        age: age ? Number(age) : undefined,
        papers: retrieval.papers,
      });
      setVerdict(syn.verdict);
      // Pick the most populated stance tab to default to.
      if (syn.verdict.supporting_papers.length > 0) setStanceTab("supporting");
      else if (syn.verdict.contradicting_papers.length > 0) setStanceTab("contradicting");
      else setStanceTab("neutral");
    } catch (e: any) {
      setVerdictError(e.message || "Verdict synthesis failed.");
    } finally {
      setVerdictLoading(false);
    }
  };

  // ---- Render ----

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "24px 20px", fontFamily: "system-ui, sans-serif" }}>

      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 28, margin: 0 }}>🥦 Health Myth Debunker</h1>
        <p style={{ color: "#666", marginTop: 6 }}>
          Submit a food health claim and we'll search the biomedical literature for evidence.
        </p>
        <p style={{
          fontSize: 12, color: "#888", background: "#f5f5f5",
          borderRadius: 8, padding: "6px 12px", display: "inline-block",
        }}>
          ⚠ For academic purposes only. Not medical advice.
        </p>
      </div>

      {/* Step indicators */}
      <div style={{ display: "flex", gap: 8, marginBottom: 28 }}>
        {[
          { label: "1. Enter claim", s: "input" },
          { label: "2. Answer questions", s: "questions" },
          { label: "3. See evidence", s: "results" },
        ].map(({ label, s }) => (
          <div key={s} style={{
            flex: 1, textAlign: "center", padding: "8px 4px",
            borderRadius: 8, fontSize: 13, fontWeight: stage === s ? 700 : 400,
            background: stage === s ? "#1a1a1a" : "#f0f0f0",
            color: stage === s ? "white" : "#555",
          }}>
            {label}
          </div>
        ))}
      </div>

      {/* Error display */}
      {error && <Alert text={error} kind="error" />}

      {/* ---- STAGE: INPUT ---- */}
      {stage === "input" && (
        <div>
          <label style={{ display: "block", marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Your claim or question</div>
            <textarea
              rows={3}
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
              placeholder="e.g. Is turmeric good for inflammation?"
              style={{
                width: "100%", padding: 12, borderRadius: 10,
                border: "1px solid #ccc", fontSize: 15, boxSizing: "border-box",
                resize: "vertical",
              }}
            />
          </label>

          <label style={{ display: "block", marginBottom: 20 }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Your age <span style={{ color: "#888", fontWeight: 400 }}>(optional — helps find relevant studies)</span></div>
            <input
              type="number"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              placeholder="e.g. 22"
              min={1} max={120}
              style={{
                width: 120, padding: 10, borderRadius: 10,
                border: "1px solid #ccc", fontSize: 15,
              }}
            />
          </label>

          <button
            onClick={handleStartAnalysis}
            disabled={loading || !claim.trim()}
            style={{
              padding: "12px 28px", borderRadius: 10, border: "none",
              background: claim.trim() ? "#1a1a1a" : "#ccc",
              color: "white", fontSize: 15, cursor: claim.trim() ? "pointer" : "not-allowed",
            }}
          >
            Start Analysis →
          </button>

          {loading && <Spinner />}
        </div>
      )}

      {/* ---- STAGE: QUESTIONS ---- */}
      {stage === "questions" && (
        <div>
          <div style={{
            background: "#f8f8f8", borderRadius: 12,
            padding: 16, marginBottom: 20,
          }}>
            <div style={{ fontSize: 13, color: "#888" }}>Your claim</div>
            <div style={{ fontWeight: 600 }}>{claim}</div>
          </div>

          {questions.length === 0 ? (
            <Alert text="No clarifying questions needed — your claim was specific enough." kind="info" />
          ) : (
            <>
              <p style={{ marginTop: 0, color: "#444" }}>
                Please answer {questions.length === 1 ? "this question" : `these ${questions.length} questions`} so we can find the most relevant papers:
              </p>
              {questions.map((q) => (
                <div key={q.slot} style={{ marginBottom: 20 }}>
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>{q.text}</div>
                  <select
                    value={answers[q.slot] || ""}
                    onChange={(e) => setAnswers({ ...answers, [q.slot]: e.target.value })}
                    style={{
                      width: "100%", padding: 10, borderRadius: 10,
                      border: "1px solid #ccc", fontSize: 14,
                    }}
                  >
                    <option value="">Select one…</option>
                    {q.option_values.map((val, i) => (
                      <option key={val} value={val}>
                        {q.option_labels[i] || val}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </>
          )}

          <div style={{ display: "flex", gap: 12 }}>
            <button onClick={reset}
              style={{
                padding: "12px 20px", borderRadius: 10,
                border: "1px solid #ccc", background: "white",
                fontSize: 15, cursor: "pointer",
              }}>
              ← Start over
            </button>
            <button
              onClick={handleRunAnalysis}
              disabled={loading}
              style={{
                padding: "12px 28px", borderRadius: 10, border: "none",
                background: "#1a1a1a", color: "white", fontSize: 15, cursor: "pointer",
              }}>
              {loading ? "Searching PubMed…" : "Find Evidence →"}
            </button>
          </div>

          {loading && <Spinner />}
        </div>
      )}

      {/* ---- STAGE: RESULTS ---- */}
      {stage === "results" && (
        <div>
          {/* --- Claim + locked PICO header --- */}
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: 12,
              padding: 16,
              marginBottom: 20,
            }}
          >
            <div style={{ fontSize: 12, color: "#64748b", letterSpacing: 0.5, fontWeight: 600 }}>
              YOUR CLAIM
            </div>
            <div style={{ fontSize: 18, fontWeight: 600, marginTop: 4, color: "#0f172a" }}>
              "{claim}"
            </div>
            {lockedPico && (
              <div
                style={{
                  marginTop: 10,
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  fontSize: 12,
                }}
              >
                {lockedPico.food && (
                  <span style={{ background: "#e0f2fe", color: "#075985", padding: "3px 10px", borderRadius: 999 }}>
                    food: {lockedPico.food}
                  </span>
                )}
                {lockedPico.component && (
                  <span style={{ background: "#ede9fe", color: "#5b21b6", padding: "3px 10px", borderRadius: 999 }}>
                    component: {lockedPico.component}
                  </span>
                )}
                {lockedPico.outcome && (
                  <span style={{ background: "#fef3c7", color: "#854d0e", padding: "3px 10px", borderRadius: 999 }}>
                    outcome: {lockedPico.outcome}
                  </span>
                )}
                {lockedPico.population && (
                  <span style={{ background: "#dcfce7", color: "#166534", padding: "3px 10px", borderRadius: 999 }}>
                    population: {lockedPico.population}
                  </span>
                )}
                {lockedPico.form && (
                  <span style={{ background: "#f1f5f9", color: "#475569", padding: "3px 10px", borderRadius: 999 }}>
                    form: {lockedPico.form}
                  </span>
                )}
              </div>
            )}
          </div>

          {warning && <Alert text={warning} kind="warning" />}

          {/* --- Verdict block (streams in after retrieval) --- */}
          {verdictLoading && !verdict && (
            <div
              style={{
                background: "#f1f5f9",
                border: "1px dashed #cbd5e1",
                borderRadius: 12,
                padding: 24,
                marginBottom: 20,
                textAlign: "center",
              }}
            >
              <div
                style={{
                  display: "inline-block",
                  width: 24,
                  height: 24,
                  border: "3px solid #cbd5e1",
                  borderTop: "3px solid #475569",
                  borderRadius: "50%",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              <div style={{ marginTop: 10, color: "#475569", fontSize: 14 }}>
                Synthesizing verdict from {papers.length} paper{papers.length === 1 ? "" : "s"}…
              </div>
              <div style={{ marginTop: 4, color: "#94a3b8", fontSize: 12 }}>
                ~20–30 seconds. You can read the papers below while this runs.
              </div>
            </div>
          )}
          {verdictError && !verdict && (
            <Alert text={`Verdict synthesis failed: ${verdictError}`} kind="error" />
          )}
          {verdict ? (
            <>
              <VerdictHeader verdict={verdict} />
              {verdict.demographic_caveat && (
                <DemographicCaveat text={verdict.demographic_caveat} />
              )}

              {/* Tabs for supporting / contradicting / neutral */}
              {(() => {
                const tabs: Array<{
                  key: "supporting" | "contradicting" | "neutral";
                  label: string;
                  count: number;
                  papers: CitedPaper[];
                  accent: string;
                }> = [
                  {
                    key: "supporting",
                    label: "Supporting",
                    count: verdict.supporting_papers.length,
                    papers: verdict.supporting_papers,
                    accent: "#10b981",
                  },
                  {
                    key: "contradicting",
                    label: "Contradicting",
                    count: verdict.contradicting_papers.length,
                    papers: verdict.contradicting_papers,
                    accent: "#ef4444",
                  },
                  {
                    key: "neutral",
                    label: "Neutral / inconclusive",
                    count: verdict.neutral_papers.length,
                    papers: verdict.neutral_papers,
                    accent: "#64748b",
                  },
                ];
                const active = tabs.find((t) => t.key === stanceTab) || tabs[0];

                return (
                  <div>
                    <div
                      style={{
                        display: "flex",
                        gap: 4,
                        borderBottom: "1px solid #e2e8f0",
                        marginBottom: 16,
                      }}
                    >
                      {tabs.map((t) => {
                        const isActive = t.key === stanceTab;
                        return (
                          <button
                            key={t.key}
                            onClick={() => setStanceTab(t.key)}
                            style={{
                              background: "transparent",
                              border: "none",
                              borderBottom: isActive
                                ? `3px solid ${t.accent}`
                                : "3px solid transparent",
                              padding: "10px 14px",
                              marginBottom: -1,
                              fontSize: 14,
                              fontWeight: isActive ? 600 : 500,
                              color: isActive ? "#0f172a" : "#64748b",
                              cursor: "pointer",
                            }}
                          >
                            {t.label}{" "}
                            <span
                              style={{
                                background: isActive ? t.accent : "#e2e8f0",
                                color: isActive ? "white" : "#475569",
                                padding: "1px 8px",
                                borderRadius: 999,
                                fontSize: 12,
                                marginLeft: 4,
                              }}
                            >
                              {t.count}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {active.papers.length === 0 ? (
                      <div
                        style={{
                          background: "#f8fafc",
                          borderRadius: 10,
                          padding: 20,
                          textAlign: "center",
                          color: "#64748b",
                          fontSize: 14,
                        }}
                      >
                        No {active.label.toLowerCase()} papers cited in this verdict.
                      </div>
                    ) : (
                      active.papers.map((p) => <CitedPaperCard key={p.paper_id} paper={p} />)
                    )}
                  </div>
                );
              })()}
            </>
          ) : (
            // No verdict yet AND not currently loading AND no error AND we have papers:
            // show nothing extra (the spinner above is the "loading" UI).
            // The fallback alert only shows when synthesis is over and a verdict
            // couldn't be produced (covered by ``verdictError`` block above) or
            // when we have no papers at all.
            !verdictLoading && !verdictError && papers.length === 0 && (
              <Alert
                text="No papers were retrieved and no verdict could be synthesized."
                kind="warning"
              />
            )
          )}

          {/* --- Advanced / debug details (collapsed) --- */}
          <details style={{ marginTop: 28, fontSize: 13, color: "#64748b" }}>
            <summary style={{ cursor: "pointer", marginBottom: 8 }}>
              Retrieval details
            </summary>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 12,
                marginTop: 12,
              }}
            >
              <div style={{ background: "#f8fafc", borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>Papers retrieved</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#0f172a" }}>
                  {papers.length}
                </div>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>
                  of {totalHits} total hits
                </div>
              </div>
              <div style={{ background: "#f8fafc", borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>Retracted</div>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 700,
                    color: papers.some((p) => p.is_retracted) ? "#c2410c" : "#0f172a",
                  }}
                >
                  {papers.filter((p) => p.is_retracted).length}
                </div>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>flagged papers</div>
              </div>
              <div style={{ background: "#f8fafc", borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>RCTs found</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#0f172a" }}>
                  {
                    papers.filter((p) =>
                      p.pub_types.some((t) => t.includes("Randomized"))
                    ).length
                  }
                </div>
                <div style={{ fontSize: 11, color: "#94a3b8" }}>randomized trials</div>
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 4 }}>
                PubMed query (final)
              </div>
              <code
                style={{
                  display: "block",
                  background: "#f1f5f9",
                  borderRadius: 8,
                  padding: 10,
                  wordBreak: "break-all",
                  lineHeight: 1.6,
                  fontSize: 12,
                }}
              >
                {queryUsed || "—"}
              </code>
            </div>

            {/* All retrieved papers list (pre-synthesis) — useful for debugging */}
            {papers.length > 0 && (
              <details style={{ marginTop: 12 }}>
                <summary style={{ cursor: "pointer" }}>
                  All {papers.length} retrieved papers (pre-synthesis)
                </summary>
                <div style={{ marginTop: 8 }}>
                  {papers.map((p) => (
                    <PaperCard key={p.pmid} paper={p} />
                  ))}
                </div>
              </details>
            )}
          </details>

          <div style={{ marginTop: 28, display: "flex", gap: 12 }}>
            <button
              onClick={reset}
              style={{
                padding: "12px 20px",
                borderRadius: 10,
                border: "1px solid #cbd5e1",
                background: "white",
                fontSize: 15,
                cursor: "pointer",
              }}
            >
              ← New claim
            </button>
            <button
              onClick={() => setStage("questions")}
              style={{
                padding: "12px 20px",
                borderRadius: 10,
                border: "1px solid #cbd5e1",
                background: "white",
                fontSize: 15,
                cursor: "pointer",
              }}
            >
              ← Change answers
            </button>
          </div>
        </div>
      )}
    </div>
  );
}