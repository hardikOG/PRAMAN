# PRAMAN

**प्रमाण — "valid proof."** A verifiable-authorization and proof-of-payment
layer for AI buyer agents paying through Razorpay.

Built for the Razorpay AI Builder Internship 2026, Track 1: AI Growth & Agentic Commerce.

![Honest purchase, decision trace resolving](docs/screenshots/01_playground.png)

## The problem

India's payment rails assume human intent is captured at the moment of
payment — OTP, 3DS, "I tapped Pay." AI buyer agents break that assumption:
the human states intent once, in natural language, ahead of time; the agent
acts later, alone, with no human at the keyboard. Three things go wrong at
once:

1. **The merchant can't prove authorization.** When a human disputes a
   charge, there's no signed artifact linking their actual intent to the
   specific cart that was charged.
2. **The PSP can't tell a good agent from a bot,** so the safe move is to
   decline agent traffic wholesale.
3. **Nobody checks whether the agent bought the right thing.** Every mandate
   spec in flight today (AP2, ACP, x402, NPCI's UAP) constrains *limits* —
   amount, merchant, expiry. PRAMAN adds an explicit intent-to-cart
   faithfulness layer that isn't captured by simple amount/merchant/expiry
   constraints: an agent that hallucinates a SKU, silently accepts an
   upsell, buys the wrong size, or gets prompt-injected by a product page
   can still satisfy every limit check in existence today, because ₹3,499
   is under the ₹4,000 cap regardless of what's actually in the cart.

**The thesis:** merchants block agent traffic because agent risk is
unquantifiable. PRAMAN makes it quantifiable — it independently verifies
that the cart matches the human's stated intent, constraint by constraint,
before money moves, and emits a hash-chained, signed evidence bundle for
every decision so the merchant has something to hand an issuer in a
dispute.

**In one example:** a user authorizes "running shoes, size 9, under
₹4,000." The agent builds a ₹3,499 cart — containing size 10.
Amount-based authorization alone still allows it: ₹3,499 is under the cap,
full stop. PRAMAN's S2 stage detects the intent/cart mismatch before
payment moves and blocks it, producing a signed proof of exactly what was
checked and why.

## Architecture

```
  HUMAN                          BUYER AGENT (any LLM, via MCP)
    │                                    │
    │ issues signed mandate              │ discovers, quotes, builds cart
    ▼                                    ▼
┌──────────────────┐            ┌───────────────────────┐
│ Mandate Service  │◀───────────│  Agent Storefront     │
│ Ed25519 keys     │  verify    │  MCP server            │
│ scope + budget   │            │  catalog / quote /     │
└──────────────────┘            │  checkout tools         │
                                └───────────┬─────────────┘
                                            │ POST /authorize
                                            ▼
                        ┌───────────────────────────────────────┐
                        │           PRAMAN GATEWAY               │
                        │  S1  Mandate verification      (~1ms)  │
                        │  S2  Intent–cart faithfulness (~0.3ms)*│
                        │  S3  Behaviour anomaly          (~0.3ms)│
                        │  S4  Policy fusion → decision           │
                        └────────┬──────────────┬─────────────────┘
                                 │              │
                     ALLOW ──────┘              └────── STEP_UP / BLOCK
                        │                                   │
                        ▼                                   ▼
              ┌───────────────────┐              ┌────────────────────┐
              │ Razorpay test-mode│              │ Human confirmation │
              │ Orders + capture  │              │ link (15 min TTL)  │
              └─────────┬─────────┘              └────────────────────┘
                        │
                        ▼
              ┌─────────────────────────────────┐
              │  PROOF LEDGER (hash-chained)    │
              │  mandate + intent + cart +      │
              │  findings + scores + rz ids     │
              │  → signed bundle, offline-      │
              │    verifiable, no DB needed      │
              └─────────────────────────────────┘
```
*\*S2's timing above is measured against the offline structural heuristic used when no `ANTHROPIC_API_KEY` is configured (see [Results](#results)) — a live per-constraint LLM call adds real network latency, which is exactly why S2 has its own p95 line in the eval report.*

Five components, one repo: **Mandate Service** (Ed25519-signed, scoped
human→agent authorizations), **Agent Storefront** (an MCP server for a demo
merchant, "Kicks & Co", backed by Razorpay test-mode Orders), the **PRAMAN
Gateway** (the four-stage pipeline above), the **Proof Ledger**
(hash-chained, independently verifiable evidence bundles), and a **Console**
(the three screens below).

## 60-second quickstart

No Docker required — SQLite + an in-process fake Redis by default.

```bash
git clone https://github.com/hardikOG/PRAMAN.git
cd PRAMAN
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env
python -m apps.api.cli seed
python -m apps.api.cli demo
```

That last command mints a mandate, builds a cart from the demo storefront,
runs it through the real S1→S4 pipeline, captures a payment (via
`DeterministicExecutor` — add real `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` to
`.env` to see a live Razorpay test-mode capture instead), and writes a signed
proof bundle to `demo_bundle.json`. Verify it independently, then tamper with
one byte and watch it fail:

```bash
python -m apps.api.cli verify demo_bundle.json "<public key printed above>"
```

Have `make` installed (Linux/macOS, or `choco install make` on Windows)? The
same steps are `make install`, `make seed`, `make demo`. `make up` brings up
the full Postgres/Redis/console stack instead, if you have Docker.

To see the console:

```bash
python -m uvicorn apps.api.main:app --port 8010 &
cd apps/web && npm install && npm run dev
```

## Results

Measured by `make eval` (or `python -m eval.runner`) against 520 generated
scenarios — 260 honest (crisp, vague, and genuinely underspecified intents)
and 260 adversarial across 8 attack classes. Full breakdown in
[`eval/RESULTS.md`](eval/RESULTS.md); raw data in
[`eval/results.json`](eval/results.json).

| Catch rate | False block | Step-up rate | p95 latency |
|---|---|---|---|
| **100.0% offline-suite catch rate** | **0.0%** | 21.2% | 0.312s |

S2 uses a deterministic structural heuristic when no LLM API key is
configured (see the caveat immediately below); live-LLM results, when run,
are reported separately rather than folded into this number.

**Ablation — what each stage actually contributes:**

| Configuration | Catch rate | False block | p95 |
|---|---|---|---|
| S1 only (limits, as every mandate spec today checks) | 23.1% | 0.0% | 0.445s |
| S1 + S3 (limits + behaviour) | 42.3% | 0.0% | 0.273s |
| S1 + S2 (limits + faithfulness) | 80.8% | 0.0% | 0.500s |
| **S1 + S2 + S3 (PRAMAN, full pipeline)** | **100.0%** | **0.0%** | 0.316s |

Limits-only — the industry's current state of the art — misses roughly
three-quarters of the attacks in this suite. Faithfulness checking (S2) is
where most of the catch rate comes from; behaviour scoring (S3) catches the
two classes (velocity drain, price-probe loops) that faithfulness checking
structurally can't, since each individual request in those attacks is
perfectly well-formed.

**Honest caveat:** these numbers were measured with no `ANTHROPIC_API_KEY`
configured, so S2's faithfulness adjudication ran on `eval/offline_llm.py` —
a documented, non-LLM structural heuristic that regex-parses fields
straight out of the rendered prompt and never reads free text. It is
*structurally* immune to the prompt-injection class (it never reads the
injected string at all), which is a different claim from a live model
*resisting* injection. Add a real key and re-run `make eval` for numbers
that say something about Claude's actual behaviour; the harness and every
number it produces are otherwise real.

Test suite: 224 passed, 1 skipped (documented — an LLM-gated test with no
key configured). `ruff` and `mypy` clean. Gateway + ledger coverage: 95%.

## Console

| Playground (attack, blocked) | Proof Inspector |
|---|---|
| ![Blocked](docs/screenshots/02_playground_blocked.png) | ![Proof](docs/screenshots/04_proof_inspector.png) |

| Live ledger | Red-team results |
|---|---|
| ![Ledger](docs/screenshots/03_ledger.png) | ![Red team](docs/screenshots/05_redteam.png) |

Ninety-second walkthrough: [`docs/screenshots/playground_demo.gif`](docs/screenshots/playground_demo.gif).

**A 3-minute live demo, in order:** in the Playground, run **Honest
purchase** (S1/S2/S3 all clear → ALLOW → real captured payment → signed
proof bundle), then **Cart substitution (size)** (S2 catches the wrong
size → BLOCK, no payment, no proof-of-ALLOW to fabricate one with), then
**"Uncertain — needs a human"** (an add-on worth 31% of the cart is too
large to auto-strip → STEP_UP → click *Confirm as human* → a *new* ALLOW
decision and proof bundle appear, the original STEP_UP entry directly above
it untouched). One mandate, one intent, three outcomes, one proof chain.

## Repo layout

```
apps/api/            fast path — FastAPI app, gateway (S1-S4), mandates, ledger, payments
apps/mcp_storefront/  demo merchant — MCP server, 40-item catalog, Razorpay orders
apps/web/             React console — Playground, Ledger, Red Team
agents/               scenario generators — honest, sloppy, 8 adversarial classes
eval/                 520-scenario harness, ablation sweep, RESULTS.md + charts
db/, core/            (see apps/api/models, apps/api/config — see ARCHITECTURE.md)
tests/                pytest — 95% coverage on gateway/ and ledger/
docs/                 ARCHITECTURE.md, SUBMISSION.md, screenshots, this README
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the six hardest design calls
and why they landed the way they did, and [`PRAMAN_BUILD.md`](PRAMAN_BUILD.md)
for the original build spec.

## Failure handling

Three specific guarantees, each backed by a test that actually simulates
the failure rather than just asserting the guarantee in prose:

- **LLM unavailable or timed out → never ALLOW.** `_evaluate_llm_constraint`
  catches `LLMError` (not just a malformed response) and downgrades to
  `UNDETERMINED`, which fuses to STEP_UP/BLOCK via S4's existing
  precedence — an outage degrades to "ask a human," never to a silent
  approval. `test_llm_unavailable_or_timeout_becomes_undetermined_never_allow`.
- **Redis unavailable → fails closed, before any write.** S1's replay guard
  is the first Redis call in the pipeline; a connection failure there
  raises immediately — no decision is constructed, no DB row written, no
  payment captured. This is a hard failure, not a graceful BLOCK decision;
  it is still, in the sense that matters, fail-closed: an outage cannot
  result in an authorized payment.
- **Payment captured, then proof persistence fails.** There is no
  distributed transaction between Razorpay and this database —
  `capture_payment` is a real, irreversible external side effect this
  process cannot roll back. `authorize()` commits the decision (with the
  real order/payment ids already attached) to the database *before*
  attempting to canonicalise, sign, and persist the proof bundle, so a
  failure at that last step can never leave a captured payment with *zero*
  local record of it. It can leave an ALLOW decision with no proof bundle
  yet — a real, narrow, honestly-documented gap, not a solved one; there is
  no outbox/retry mechanism to backfill the missing bundle today.
  `test_decision_and_payment_survive_a_proof_bundle_save_failure`.

## Limitations

- **No live-LLM measurement yet.** The headline numbers above run on the
  offline heuristic (see the caveat under Results); the code path for the
  real `AnthropicLLMClient` is complete and unit-tested, but re-running
  `make eval` with a real key — and reporting what changes — is the
  immediate next step, not a hypothetical one.
- **Docker Desktop was broken on the build machine for most of this build**
  (a documented WSL2/disk-space issue, not a PRAMAN bug). `docker-compose.yml`
  is complete and correct for the full Postgres/Redis/console stack, but it
  was not exercised end-to-end in this environment; the native SQLite +
  fake-Redis path was, extensively, and is what every gate in this repo was
  actually verified against. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for
  the specifics.
- **One demo merchant, one catalog, one currency.** Multi-merchant and
  multi-currency are straightforward extensions of the existing schema, not
  attempted here for scope reasons.
- **STEP_UP has no SMS/push/email integration.** The confirm-and-pay flow
  itself is complete: `POST /decisions/step-up/confirm` redeems the token
  (single-use, Redis `GETDEL`), captures payment exactly once, and emits a
  *new* ALLOW decision plus a *new* signed proof bundle — the original
  STEP_UP decision is never mutated (see `gateway.pipeline.confirm_step_up`
  and the "Uncertain — needs a human" preset in the console). What's
  missing is only the notification channel that would hand the human that
  link outside the console itself.
- **The behaviour-anomaly stage (S3) is threshold-based, not learned.** It
  catches the two attack classes in this suite deliberately designed to look
  clean at the single-request level, but it is not an anomaly-detection
  model and doesn't claim to generalize beyond what its thresholds encode.

## License

MIT — see [`LICENSE`](LICENSE).
