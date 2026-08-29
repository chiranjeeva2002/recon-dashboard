# Ledger Reconciler

A full-stack app that ingests an order export and a payment processor export, deterministically
reconciles them, and presents the result as a dashboard someone responsible for revenue could
actually act on — headline figures, a discrepancy breakdown, and a filterable/searchable
drill-down table, with an LLM layer that explains each discrepancy in plain language.

**Live app:** https://recon-dashboard1.onrender.com/
**Repo:** https://github.com/chiranjeeva2002/recon-dashboard
**Test credentials:** sign up with any email/password (8+ characters) — no seeded account needed.

---

## Tech stack

- **Backend:** FastAPI (Python), SQLAlchemy ORM
- **Database:** PostgreSQL in production (Neon), SQLite for local dev — same code path, only
  `DATABASE_URL` changes
- **Auth:** bcrypt password hashing, JWT stored in an httpOnly cookie (not localStorage, to avoid
  exposing the token to XSS)
- **Frontend:** server-rendered Jinja2 pages + vanilla JavaScript (no build step), Tailwind CSS
  and Chart.js via CDN
- **LLM:** OpenAI (`gpt-4o-mini`), called server-side only, structured JSON output
- **Deployment:** Render (single web service), Neon (managed Postgres)

## Running it locally

```bash
git clone https://github.com/chiranjeeva2002/recon-dashboard.git
cd recon-app
python -m venv venv
venv\Scripts\activate        # Windows; use `source venv/bin/activate` on Mac/Linux
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste output as JWT_SECRET in .env
```

Fill in `.env` (see `.env.example` for the full list of variables). `DATABASE_URL` defaults to
a local SQLite file, so no database setup is required to run it locally — Postgres is only used
in production.

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`, sign up, and upload `orders.csv` and `payments.csv` from the
dashboard's upload screen.

## Architecture

One FastAPI service serves both the JSON API and the HTML pages — deliberately a monolith rather
than a separate frontend framework + separate deploy, given the scope of this assignment and the
brief's instruction not to over-build.

```
Browser
  │
  ├─ GET /, /login, /signup, /dashboard        (Jinja2 HTML pages)
  │
  └─ fetch() calls, cookie-authenticated:
        POST /api/auth/signup, /login, /logout
        POST /api/ingest                        (upload CSVs → reconcile → persist)
        GET  /api/reconciliation                (filtered/paginated discrepancies + stats)
        POST /api/reconciliation/explain         (LLM explanation for one/more discrepancies)
              │
              ▼
        SQLAlchemy ORM → PostgreSQL (Neon)
```

**Request flow for ingestion:** upload → validate (file type, required columns) → parse and
normalize both CSVs → run the deterministic reconciliation engine (`app/reconcile.py`, pure
function, no I/O) → persist the run, the normalized order/payment rows, and every discrepancy
found, all in one database transaction.

**Request flow for explanation:** the frontend requests an explanation for one or more
already-computed discrepancy rows → the backend loads those exact rows (scoped to the logged-in
user) → sends only their already-finalized data (type, amount, summary) to OpenAI, asking for a
structured explanation → caches the result on the discrepancy row so re-opening it later doesn't
re-call the API.

Every data-returning endpoint requires a valid session and filters every database query by the
logged-in user's id — there is no query anywhere in the codebase that returns another user's
data by id/reference alone.

## Reconciliation logic

The two files were profiled first (ad hoc pandas exploration) to find out what was actually
wrong with them, rather than guessing at plausible-sounding discrepancy types. Every rule below
exists because of a specific row found in the data.

### How matching works

Orders and payments are matched by `order_id` / `order_reference`, normalized (trimmed,
uppercased) before comparison — the raw data has inconsistent casing/whitespace
(`ord-1801 ` vs `ORD-1801`) that would otherwise silently produce false "missing payment" and
"orphan payment" results.

### Discrepancy types found

| Type | Example from the data | Severity | Reasoning |
|---|---|---|---|
| Missing payment | 4 completed orders (`ORD-1201`–`1204`) with no payment record at all | High | Store believes it was paid; processor has nothing. Full order value at risk. |
| Orphan payment | 3 settled payments referencing order ids that don't exist | Medium | Money moved with no order behind it — needs manual investigation. |
| Amount mismatch | Order says 92.81, payment settled at 117.81 | Medium/High (≥$20 escalates to high) | Real discrepancy, not rounding. |
| Currency mismatch | Order in USD, payment settled in EUR, same numeric amount | Medium | The dangerous case — the number looks right but the value isn't (210 USD ≠ 210 EUR). |
| Duplicate charge | Order charged twice, identical amount, ~30 minutes apart | High | Looks like a retried/duplicated charge, not two purchases. |
| Charge on cancelled order | Order is cancelled but has a settled charge, never refunded | High | Customer charged for something the store says didn't happen. |
| Partial refund shortfall | Order marked refunded, but only half the charge was actually refunded | Medium | Store believes the customer was made whole; the processor shows otherwise. |
| Refund on completed order | Order still marked completed, but fully refunded on the payment side | High | The order status is stale — money has been returned but the record doesn't reflect it. |
| Unsettled payment | Completed order, payment still pending | Medium | Revenue isn't secured yet. |
| Failed payment on completed order | Completed order, only payment attempt failed | High | No money was ever actually collected for a "sold" order. |

### Tolerances

- **$0.05 amount tolerance.** A genuine 2-cent difference was found in the data (floating-point/
  rounding noise) that isn't a real discrepancy. Flagging it would train the dashboard's user to
  ignore real alerts. The real mismatches found were $18.50, $25, and $60 — an order of magnitude
  larger, so a 5-cent line is conservative and defensible.
- **48-hour window for duplicate-charge detection.** The real duplicate charges found were ~30
  minutes apart. 48 hours is generous enough to catch same/next-day retries while not flagging
  two legitimate, unrelated purchases that happen to reuse a reference months apart.

### Avoiding double-counted/invented discrepancies

The first version of the engine flagged some orders under two overlapping discrepancy types for
the same underlying dollars — e.g. a duplicate charge was also being reported as an "amount
mismatch" (because collected ≠ expected), double-counting one root cause as two problems. This
was caught by running the engine against the real data and inspecting the output, not by
inspection of the code alone. The fix: once a more specific rule (duplicate charge, refund) has
already explained a gap between order value and money collected, the generic amount-mismatch
check is skipped for that order.

### Verified results (against the provided dataset)

- 184 orders (after excluding 1 exact duplicate export row), 187 payments
- 19 discrepancies across the 10 types above
- $39,963.28 reconciled cleanly
- $2,178.43 total value in dispute
- $2,093.43 in money genuinely at risk (excludes overcharges, which are a customer-service
  concern rather than lost revenue, and excludes the customer-favorable side of amount
  mismatches)

## What's actually wrong with the data

- One exact duplicate order export row.
- Inconsistent casing/whitespace on order references between the two systems.
- Two different date formats between the systems (`YYYY-MM-DD HH:MM:SS` vs `DD/MM/YYYY HH:MM`).
- Four completed orders with no payment record — revenue the store believes it collected but
  never actually did.
- Three payments referencing order ids that don't exist anywhere in the order system.
- Two orders where the numeric charge amount matches but the currency code doesn't (a store
  charging/crediting in the wrong currency while showing the "right" number).
- Two duplicate charges (same order charged twice in quick succession).
- One order charged despite being cancelled, never refunded.
- One order marked refunded but only half the money was actually returned.
- One order still marked "completed" despite being fully refunded on the payment side — the
  order record was never updated.
- One completed order backed by a still-pending payment; one backed by an outright failed
  payment attempt.

**Business implication:** taken together, these represent both revenue leakage (missing
payments, failed/duplicate charges never reconciled) and customer-facing risk (charges on
cancelled orders, unrefunded amounts) that would not be visible from either system in isolation —
only by comparing them.

## LLM approach

The LLM is used **only** to explain discrepancies the deterministic engine has already found and
classified — it is never given raw orders/payments and has no way to influence matching.

- **Model:** `gpt-4o-mini`, called server-side (`app/llm.py`); the API key is never sent to or
  used by the frontend.
- **Temperature: 0.2.** This is a summarization/explanation task, not a creative one — the same
  discrepancy should reliably produce a stable, factual explanation. `0` would be maximally
  deterministic but risks stilted, repetitive phrasing; anything above ~0.3–0.4 risks the model
  embellishing beyond what the data actually supports, which the system prompt explicitly
  instructs against.
- **Structured output:** requested via OpenAI's `response_format: json_schema` (`strict: true`),
  which constrains generation to the schema rather than just asking nicely for JSON — more
  reliable than a plain "respond in JSON" instruction, though not the only defense (see below).
- **Error handling, exercised for real during development, not just written defensively:**
  - Malformed/non-JSON response → caught, falls back to a clear "explanation unavailable"
    result
  - Valid JSON that doesn't match the expected schema → same fallback
  - The API call itself failing (bad key, exhausted credit, network error, SDK/library version
    mismatch) → caught, same fallback
  - In every case, the underlying deterministic discrepancy data is still shown — only the
    explanation panel shows a graceful failure state with a retry option, the rest of the
    dashboard is unaffected.

## What I'd improve with more time

- Alembic migrations instead of `Base.metadata.create_all()` — fine for this assignment's scope,
  but the first thing a real production system would need as the schema evolves.
- Background/async ingestion for larger files, with a progress indicator, rather than the
  synchronous request currently used (fine for ~200-row CSVs, wouldn't scale to very large
  exports).
- A confidence/severity re-ranking that also considers order age (a $60 mismatch from a year ago
  is a different priority than one from yesterday).
- Bulk "explain all high-severity discrepancies" rather than one at a time.
- Rate limiting / cost controls around the explain endpoint, since it calls a paid API on demand.

## Use of AI tools

Claude was used throughout as a coding assistant: analyzing the provided CSVs to identify real
data-quality issues, writing and iterating on the reconciliation engine, backend routes, and
frontend, and helping debug environment/deployment issues (dependency conflicts, `.env` parsing,
a `httpx`/`openai` SDK version mismatch, a missing route file). All reconciliation rules and
tolerances were derived from and verified against the actual dataset, and I reviewed and
understand the resulting code and its trade-offs.