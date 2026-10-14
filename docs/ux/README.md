# PRAMAN — UX case study workspace

Working notes for the design side of PRAMAN. Everything here is labelled by
how it was produced: **built** (shipped in the app), **expert review** (my own
analysis — not user research), or **to run** (needs real people and has not
happened yet). Nothing in the *to run* column is filled in with invented results.

## The problem, in one example

A shopper tells their AI agent: *"running shoes under ₹4,000, size 9, not
white."* The agent builds a cart that also contains a ₹999 bag. PRAMAN catches
it and needs the **shopper** — not an engineer — to decide.

## Before: expert review of the first console (not user research)

Source screenshots: `../screenshots/06_playground_stepup.png`,
`../screenshots/07_playground_confirmed.png`, `../screenshots/03_ledger.png`.

| # | Finding | Why it matters |
|---|---|---|
| 1 | A BLOCK's reason was `constraint_violated:112b34f2-…` — a UUID. | You had to cross-reference another panel to learn "wrong size". |
| 2 | "Confirm as human" never said *what* was being confirmed. | The ₹999 bag and its 31% share sat behind `TOTE-20` and a token. |
| 3 | Only one action: confirm. No way to remove the item or refuse. | The obvious third option — "pay without it" — didn't exist. |
| 4 | Every constraint read green SATISFIED while the decision said STEP UP. | The unrequested item isn't a constraint, so the screen contradicted itself. |
| 5 | Millisecond latencies occupied the prime position. | Right for an engineer, noise for a shopper. |
| 6 | The proof panel shows a hard-coded "✓ chained and signed". | The UI asserts verification it never performed — a trust problem. *Not yet fixed.* |

## After: what was built

| Surface | Audience | What changed | Where |
|---|---|---|---|
| Shopper confirmation (hero) | Shopper, on a phone | Plain headline, the cart with the unrequested line flagged, **Remove it & pay / Keep it & pay / Cancel**, expiry stated, "nothing is charged until you choose". | `apps/web/src/components/ShopperConfirm.tsx`, opened by `/?confirm=<token>` |
| Plain-language reasons | Merchant ops | Every decision carries a one-sentence `plain_reason`; raw code kept small underneath for engineers. | `apps/api/gateway/explain.py`, Ledger + Proof Inspector |
| Cancel is evidence | Dispute handling | Declining records its own decision (`step_up_declined:…`); the original STEP_UP is never edited. | `gateway.pipeline.confirm_step_up` |

Design decisions worth defending in an interview:

- **Two audiences, two surfaces, one token system.** The console stays dark and
  dense (a records office); the shopper screen is light, large-type, one column,
  ≥48px targets — same seal/amber/stamp meanings (`figma-tokens.json`).
- **The primary button is the safe default.** "Remove it & pay" completes what
  the shopper originally asked for; keeping the extra item is the secondary
  action, cancelling is a quiet text button.
- **Show the arithmetic.** Both buttons carry the amount they will charge.
- **Never burn the link on a bad request.** A rejected action leaves the
  one-time token usable (tested).

Screens (390×844): `shopper_1_review.png`, `shopper_2_paid_without_addon.png`,
`shopper_3_cancelled.png`, `shopper_4_link_used.png`.

## To run — the research that is still owed

Nothing below has been done. Results go in a table here, quoted verbatim.

**5-second test** (5 people who haven't seen the project). Show
`shopper_1_review.png` for 5 seconds, hide it, ask:
1. "What was that screen asking you to do?"
2. "What would you tap, and what do you think happens next?"
3. "Was anything surprising or missing?"

Run the same test on the *old* step-up screenshot first, so the comparison is
real. Record: participant · exact words · tapped what · correct understanding (Y/N).

**What to measure once there's data:** share who understand the screen in 5s,
share who pick "Remove it & pay", share who say what the extra item was.
Small-n — report as anecdote, not statistics.

## Figma

I cannot author Figma files from here (the Figma connector is read-oriented and
isn't connected). To get the screens in:
1. Import `figma-tokens.json` with the Tokens Studio plugin for variables.
2. Rebuild the four screens in Figma from the PNGs (they are the spec) or run
   the html.to.design plugin on a deployed copy of the page (untested by me).
3. Keep Figma ↔ code in sync by naming components after the React ones.
