// frontend/src/App.tsx
import { useState } from "react";
import { extractClaim, finalizeClaim, Question, Paper } from "./api";

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

  // Step 2: send answers → run retrieval → show papers
  const handleRunAnalysis = async () => {
    if (!partialPico) return;
    setError("");
    setLoading(true);
    try {
      const data = await finalizeClaim({
        partial_pico: partialPico,
        answers,
        age: age ? Number(age) : undefined,
      });
      setPapers(data.papers);
      setQueryUsed(data.query_used);
      setTotalHits(data.total_pubmed_hits);
      setWarning(data.warning || null);
      setStage("results");
    } catch (e: any) {
      setError(e.message || "Something went wrong during retrieval.");
    } finally {
      setLoading(false);
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
          {warning && <Alert text={warning} kind="warning" />}

          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
            gap: 12, marginBottom: 24,
          }}>
            <div style={{ background: "#f5f5f5", borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 12, color: "#888" }}>Papers found</div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>{papers.length}</div>
              <div style={{ fontSize: 12, color: "#888" }}>of {totalHits} total hits</div>
            </div>
            <div style={{ background: "#f5f5f5", borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 12, color: "#888" }}>Retracted</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: papers.some(p => p.is_retracted) ? "#e65100" : "#2e7d32" }}>
                {papers.filter(p => p.is_retracted).length}
              </div>
              <div style={{ fontSize: 12, color: "#888" }}>flagged papers</div>
            </div>
            <div style={{ background: "#f5f5f5", borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 12, color: "#888" }}>RCTs found</div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>
                {papers.filter(p => p.pub_types.some(t => t.includes("Randomized"))).length}
              </div>
              <div style={{ fontSize: 12, color: "#888" }}>randomized trials</div>
            </div>
          </div>

          <details style={{ marginBottom: 20, fontSize: 13, color: "#888" }}>
            <summary style={{ cursor: "pointer" }}>PubMed query used (click to expand)</summary>
            <code style={{
              display: "block", background: "#f5f5f5", borderRadius: 8,
              padding: 10, marginTop: 8, wordBreak: "break-all", lineHeight: 1.6,
            }}>
              {queryUsed}
            </code>
          </details>

          {papers.length === 0 ? (
            <Alert text="No papers were retrieved. Try rephrasing your claim or answering the questions differently." kind="warning" />
          ) : (
            <div>
              <h2 style={{ marginTop: 0 }}>Retrieved papers ({papers.length})</h2>
              <p style={{ color: "#666", fontSize: 14, marginBottom: 16 }}>
                Papers are ordered by PubMed's own relevance ranking. Click any title to open it on PubMed.
              </p>
              {papers.map((p) => <PaperCard key={p.pmid} paper={p} />)}
            </div>
          )}

          <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
            <button onClick={reset}
              style={{
                padding: "12px 20px", borderRadius: 10,
                border: "1px solid #ccc", background: "white",
                fontSize: 15, cursor: "pointer",
              }}>
              ← New claim
            </button>
            <button onClick={() => setStage("questions")}
              style={{
                padding: "12px 20px", borderRadius: 10,
                border: "1px solid #ccc", background: "white",
                fontSize: 15, cursor: "pointer",
              }}>
              ← Change answers
            </button>
          </div>
        </div>
      )}
    </div>
  );
}