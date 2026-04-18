# UI Design Plan — Health Myth Debunker

Hand-off brief for aura.build. Filled in against the 8-section template
plus the final send-it block.

---

## 1. Product overview

- **What it does:** Fact-checks food/nutrition claims. User types something like *"Is turmeric good for inflammation?"*; the system extracts a structured query, asks up to 3 clarifying questions, pulls matching papers from PubMed, and returns an evidence-based verdict (supported / contradicted / insufficient evidence) with cited studies.
- **Users:** General public curious about nutrition myths. Secondary: students and clinicians who want a quick first-pass literature review. No login required.
- **Main UI goals:**
  1. Make the input feel simple (one text box, not a form).
  2. Make the clarifying questions feel like a conversation, not an interrogation.
  3. Make the verdict readable at a glance *and* drillable for evidence.
  4. Keep the 15–30-second synthesis wait from feeling like a freeze — show progress.
- **App type:** Public-facing site. Single "app" flow, no dashboard, no admin panel in v1.

---

## 2. Pages and user flows

### Pages / screens

| # | Name | Purpose |
|---|------|---------|
| 1 | **Landing** | Text input, "Analyze" button, 3 example chips (seed curiosity) |
| 2 | **Extracting** | Brief loading state while Gemini parses the claim (~2s) |
| 3 | **Clarifying** | 0–3 multi-choice questions, one at a time |
| 4 | **Working** | Progress stream: "Searching PubMed… 22 papers found… Scoring… Synthesizing…" (~15–30s) |
| 5 | **Verdict** | Big verdict label + confidence bar + reasoning + tabbed paper lists |
| 6 | **Scope rejection** | Shown instead of 3–5 if claim isn't food/nutrition (e.g., "aspirin prevents heart attacks") |
| 7 | **Error / no papers** | Graceful fallback if PubMed returns nothing or a retry is needed |

### Priority to build first

1. Landing (1)
2. Verdict (5)
3. Clarifying (3)

The loading screens (2, 4) can be simple spinners in v1 and upgraded later.

### User journey (happy path)

```
Landing → Analyze
  → Extracting (spinner)
  → Clarifying Q1 → Next
  → Clarifying Q2 → Submit
  → Working (progress stream)
  → Verdict
  → [Try another claim] → Landing
```

### Edge paths

- **Scope rejection:** Landing → Extracting → Scope rejection screen → [Edit claim] → Landing
- **No papers found:** Landing → … → Working → Error screen with suggestion to broaden the claim
- **Rate limit (PubMed 429):** Retry automatically up to 3 times; show "PubMed is busy, retrying…" then fall back to a polite error

No role-based flows — everyone sees the same screens.

---

## 3. Backend integration details

### Status

The backend is a Python/FastAPI pipeline. Station 4 already exposes endpoints in [src/synthesis/paper_scorer.py](../src/synthesis/paper_scorer.py); a unified `/run` endpoint wrapping all four stations is in progress.

### Endpoint contract (planned)

```
POST /api/extract
  request :  { "claim": "Is turmeric good for inflammation?" }
  response:  { "partial_pico": PartialPICO, "is_food_claim": bool,
               "scope_rejection_reason": string | null }

POST /api/elicit/next
  request :  { "partial_pico": ..., "answers_so_far": [...] }
  response:  { "next_question": Question } | { "locked_pico": LockedPICO }

POST /api/run
  request :  { "claim": "...", "answers": [...] }
  response:  SSE stream of { "stage": "...", "payload": {...} } events
  final event: { "stage": "verdict", "payload": AnalysisResponse }
```

### Sample payloads (real data from our demo run)

**Question shape (elicitation):**
```json
{
  "text": "Are you asking about turmeric as food or as a supplement?",
  "options": [
    "As a spice in food (typical culinary amounts)",
    "As a curcumin supplement (standardized extract pills)",
    "Turmeric tea or golden milk",
    "Not sure"
  ],
  "option_values": ["dietary", "supplement", "dietary_concentrated", "unknown"],
  "allow_other": false
}
```

**AnalysisResponse (verdict) — trimmed:**
```json
{
  "user_claim": "Is turmeric good for inflammation?",
  "verdict": {
    "verdict": "supported",
    "confidence_percent": 80,
    "verdict_reasoning": "The claim is supported by a significant body of evidence. Multiple high-relevance systematic reviews and RCTs indicate that curcumin and Curcuma longa extract possess anti-inflammatory properties...",
    "demographic_caveat": null,
    "supporting_papers": [
      {
        "paper_id": "41096639",
        "title": "Curcumin in Inflammatory Complications: Therapeutic Applications and Clinical Evidence",
        "url": "https://pubmed.ncbi.nlm.nih.gov/41096639/",
        "stance": "supports",
        "relevance_score": 0.90,
        "applies_to": ["adults"],
        "demographic_match": true,
        "one_line_summary": "Curcumin administration improves disease markers in inflammatory complications."
      }
    ],
    "contradicting_papers": [
      {
        "paper_id": "41372521",
        "title": "Effects of curcumin on inflammatory biomarkers in RA and SLE: a meta-analysis",
        "url": "https://pubmed.ncbi.nlm.nih.gov/41372521/",
        "stance": "contradicts",
        "relevance_score": 0.90,
        "applies_to": ["adults"],
        "demographic_match": true,
        "one_line_summary": "Curcumin had limited and inconsistent effects on inflammatory biomarkers in RA/SLE patients."
      }
    ],
    "neutral_papers": []
  }
}
```

### Authentication

None in v1. Frontend calls backend directly. In production, the backend will sit behind Cloudflare / rate-limit middleware — no auth tokens for the frontend to handle.

### Error format

Standard HTTP JSON errors:
```json
{ "detail": "PubMed is temporarily rate-limited. Please retry in ~30s.",
  "code": "RATE_LIMITED" }
```

Codes the UI should handle:
- `400 UNSCOPABLE_CLAIM` → Scope rejection screen
- `503 RATE_LIMITED` → Retry banner
- `504 SYNTHESIS_TIMEOUT` → Error screen with retry button
- `500` (any other) → Generic error screen

### File uploads

None.

---

## 4. Auth and permissions

**v1: none.** Public, anonymous access to everything.

Future (v2+): optional user accounts for saving claim history. When built, use Clerk or Supabase Auth. Not a blocker for the initial UI.

**Protected routes:** none.
**Roles:** none.
**Session / token storage:** not applicable.

---

## 5. Brand and visual direction

- **Name:** Health Myth Debunker (working title — open to rebrand).
- **Tone:** Trustworthy medical meets clean AI product. Closer to *Mayo Clinic + Perplexity* than *TikTok + fitness influencer*.
- **Colors:**
  - Primary: Navy `#0b2138`
  - Accent: Teal `#0d9488`
  - Verdict-positive (Supported): Green `#15803d`
  - Verdict-negative (Contradicted): Red `#b91c1c`
  - Verdict-neutral (Insufficient evidence): Slate `#475569`
  - Neutrals: Tailwind `slate` scale
- **Typography:** Inter or IBM Plex Sans. Body weight 400, headings 600. No novelty fonts.
- **References to show the designer:**
  - Layout / answer density: https://perplexity.ai (citation-heavy answer format)
  - Medical trust signals: Mayo Clinic, NIH disease pages
  - Interaction feel: Claude.ai (streaming, conversational)
- **Styles to avoid:** emojis in core UI, glassmorphism, gradients, cartoon mascots, stock imagery, crypto-looking purple gradients.

---

## 6. Content and assets

### Copy (draft — OK to polish)

**Landing hero:**
> *"Ask a food or nutrition question. Get an answer backed by real research."*

Example claim chips (show as clickable suggestions):
- Is turmeric good for inflammation?
- Does red meat cause colorectal cancer?
- Is a glass of wine a day good for the heart?

**Empty state** (no text yet): subtle placeholder "e.g. Does intermittent fasting help with weight loss?"

**Loading states:**
- Extracting: *"Understanding your question…"*
- Retrieval: *"Searching {N} medical papers on PubMed…"*
- Synthesis: *"Weighing the evidence…"*

**Scope rejection:**
> *"This looks like a {claim type} question, not a food or nutrition one. We only handle food/nutrition claims for now. Try rephrasing around a food, drink, nutrient, or supplement."*

**Verdict labels:**
- `supported` → "Supported by evidence"
- `contradicted` → "Contradicted by evidence"
- `insufficient_evidence` → "Not enough evidence"

**Paper card fields:**
- Title (linked to `url`)
- Badge: stance (supports / contradicts / neutral)
- Relevance score as a small bar or percentage
- One-line summary
- Muted line: "PMID {paper_id}"

### Images / illustrations

None required in v1. If the designer proposes hero illustrations, keep them abstract / medical-adjacent, not cartoon humans.

### Empty / error / loading states

Every page must have all three:
- **Empty:** what does the verdict screen look like before the user has searched?
- **Loading:** progress indicator + current stage text
- **Error:** friendly message + "Try again" button + "Edit claim" secondary link

### Form fields / labels

- Claim input: single textarea, placeholder "Ask a food or nutrition question…", char limit 500 with visible counter after 400.
- Multi-choice questions: radio buttons, large hit targets, "Next" primary + "I'm not sure" implicit through the "Not sure" option.

---

## 7. Functional requirements

- **Form validation:** claim must be 3–500 characters, whitespace-only rejected. Trim before submit.
- **Filters / sorting / search:** none in v1. Paper lists are already sorted by relevance by Station 4.
- **Pagination:** none. Max ~40 papers per verdict, show all inside tabs.
- **Notifications / modals / confirmations:**
  - Toast on rate-limit errors
  - Non-blocking banner if `below_threshold` is true in the retrieval result ("Fewer than 10 papers matched — interpret with caution")
  - No confirmation modals
- **Realtime features:**
  - Progress streaming during Stations 3+4 (SSE). The UI should re-render stage text as events arrive.
  - Typed-by-typed character animation on verdict reasoning is optional flair, not required.
- **Share / export (stretch goal):** "Copy link" button on the verdict screen that encodes the locked PICO in the URL so a shared link re-runs the same analysis. Out of scope for v1 unless easy.

---

## 8. Technical preferences

- **Framework:** Next.js 15 App Router + TypeScript + Tailwind + shadcn/ui. (Default aura.build stack.)
- **State:** React `useState` / `useReducer` locally; no Redux/Zustand needed.
- **Streaming:** `EventSource` for SSE from the backend.
- **Responsive:** Mobile-first. Layout must work on 360px wide. People fact-check on phones.
- **Browser support:** evergreen (last 2 versions of Chrome, Safari, Firefox, Edge). No IE.
- **SEO:** Landing page needs proper meta tags and Open Graph card. Verdict pages are dynamic and don't need SSR/SEO in v1.
- **Accessibility:** WCAG 2.1 AA baseline. Specifically:
  - Keyboard-only navigation for the entire claim → verdict flow
  - Semantic headings, `aria-live="polite"` region for progress updates
  - Color contrast ≥ 4.5:1 for body text
  - Focus-visible outlines

---

## Best-case handoff package

**Minimum** (what aura.build strictly needs):
- This document.
- API contract + real sample JSON (already inline in section 3).
- Page list with priority (section 2).
- Brand direction (section 5).

**Ideal** (for a cleaner first pass):
- All of the minimum, plus
- Rough wireframes for Landing + Verdict (even hand-drawn is fine).
- Copy reviewed by a second pair of eyes.
- A real `AnalysisResponse` JSON exported from a live demo run (run `demo.py` once and paste the Station 4 output).
- 2–3 screenshot references of product tones we like.

---

## Send-it block (paste into aura.build)

```
Project:
  Health Myth Debunker — a web app that fact-checks food and nutrition
  claims against real PubMed research. User types a claim, answers 0–3
  clarifying questions, and gets a verdict (Supported / Contradicted /
  Insufficient Evidence) with confidence % and cited papers.

Users:
  General public curious about nutrition myths. No account required.

Pages:
  1. Landing        — claim input + example chips
  2. Extracting     — brief spinner
  3. Clarifying     — 0–3 multi-choice questions, one at a time
  4. Working        — progress stream while papers are fetched & scored
  5. Verdict        — verdict badge + confidence bar + reasoning +
                      tabs (Supporting / Contradicting / Neutral)
  6. Scope rejection — shown when the claim isn't food/nutrition
  7. Error / no papers — graceful fallback

Priority flow:
  Landing → Clarifying → Verdict.
  Build these three first; the others are transient or edge cases.

Backend/API docs:
  FastAPI backend at /api/*. Three endpoints:
    POST /api/extract       { claim }              → PartialPICO
    POST /api/elicit/next   { partial, answers }   → next question OR locked PICO
    POST /api/run           { claim, answers }     → SSE stream → AnalysisResponse
  Sample JSON payloads are in docs/UI_design_plan.md section 3.

Auth:
  None. Public, anonymous.

Roles:
  None.

Design references:
  - perplexity.ai (citation-heavy answer layout)
  - mayoclinic.org (trust signals, conservative medical tone)
  - claude.ai (streaming, conversational interaction)
  Avoid: emojis in core UI, glassmorphism, gradient-heavy, cartoon illustrations.

Brand colors:
  Primary Navy    #0b2138
  Accent Teal     #0d9488
  Supported       #15803d (green)
  Contradicted    #b91c1c (red)
  Insufficient    #475569 (slate)
  Typography: Inter or IBM Plex Sans.

Content/assets:
  Draft copy is in docs/UI_design_plan.md section 6.
  No images or illustrations required for v1.
  Every page needs empty / loading / error states.

Special features:
  - Multi-step elicitation (up to 3 questions, one at a time)
  - Progress streaming via SSE during the 15–30s retrieval + synthesis step
  - Paper cards with stance badges, relevance scores, and PubMed deep links
  - Mobile-first responsive (target 360px min width)

Deadline:
  (fill in)
```
