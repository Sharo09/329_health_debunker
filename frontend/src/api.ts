// frontend/src/api.ts
// All communication between the React UI and the FastAPI backend goes here.

export type Question = {
  slot: string;
  text: string;
  option_values: string[];
  option_labels: string[];
};

export type ExtractResponse = {
  is_food_claim: boolean;
  scope_rejection_reason?: string | null;
  partial_pico: Record<string, any>;
  questions: Question[];
};

export type Paper = {
  pmid: string;
  title: string;
  abstract: string;
  journal: string;
  pub_year: number | null;
  pub_types: string[];
  pubmed_url: string;
  is_retracted: boolean;
};

export type CitedPaper = {
  paper_id: string;
  title: string;
  url: string | null;
  stance: "supports" | "contradicts" | "neutral" | "unclear";
  relevance_score: number;
  applies_to: string[];
  demographic_match: boolean;
  one_line_summary: string;
};

export type Verdict = {
  verdict: "supported" | "contradicted" | "insufficient_evidence";
  confidence_percent: number;
  verdict_reasoning: string;
  demographic_caveat: string | null;
  supporting_papers: CitedPaper[];
  contradicting_papers: CitedPaper[];
  neutral_papers: CitedPaper[];
};

export type FinalizeResponse = {
  below_threshold: boolean;
  total_pubmed_hits: number;
  query_used: string;
  relaxation_level: number;
  papers: Paper[];
  warning?: string | null;
  verdict: Verdict | null;            // always null on /api/finalize now
  raw_claim: string;
  locked_food: string | null;
  locked_outcome: string | null;
  locked_population: string | null;
  locked_form: string | null;
  locked_component: string | null;
};

export type SynthesizeResponse = {
  verdict: Verdict;
};

// BASE_URL is empty string in production (same origin) and proxied in dev
// via vite.config.ts proxy setting.
const BASE_URL = "";

export async function extractClaim(claim: string): Promise<ExtractResponse> {
  const res = await fetch(`${BASE_URL}/api/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function finalizeClaim(payload: {
  partial_pico: Record<string, any>;
  answers: Record<string, string>;
  age?: number;
}): Promise<FinalizeResponse> {
  const res = await fetch(`${BASE_URL}/api/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Hits Station 4 (synthesis) on previously-retrieved papers.
 * Run AFTER finalizeClaim so the user sees retrieved papers immediately
 * while this slow request (~25s) cooks the verdict in the background.
 */
export async function synthesizeClaim(payload: {
  partial_pico: Record<string, any>;
  answers: Record<string, string>;
  age?: number;
  papers: Paper[];
}): Promise<SynthesizeResponse> {
  const res = await fetch(`${BASE_URL}/api/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}