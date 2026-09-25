# The demand side: agents buying a human judgment

Round 2 adds the other half of the loop. An agent that hits a step it cannot
resolve pays for a human verdict; the human who clocks in supplies it. This
records what was verified before building, and the two places the specs
disagree.

## Both vendors are real, and one is better placed than the spec assumed

**Jev** exists: TypeSafe AI, launched September 2026, a "System One" classifier
returning typed answers with calibrated probabilities. The `noul` type (a
yes/no question answered with a probability) is real, latency is 70–500 ms, and
input is priced around $0.042 per million tokens. The integration spec's shape
matches the vendor's.

One correction taken from TypeSafe's own documentation: the response nests
answers under an **`answers`** object, while the integration spec shows them at
the top level. The spec flagged that field names might drift, and they had.
`parse_jev_response` reads both, and refuses anything else rather than
defaulting a missing probability to zero — a zero would silently mean
"definitely do not escalate" on a question nobody answered.

**x402** is real: a Coinbase-originated protocol built on HTTP 402. And here
the flow doc is out of date in a way worth acting on.

## Recommendation: keep both legs on Solana

The user-flow draft (`README.md` → "User flow") describes the agent's payment as "USDC on Base". x402
runs natively on Solana with SPL tokens, and **Solana carries roughly 70% of
the protocol's monthly transaction volume** — around $3.3M USDC settled in a
single week, more than any other supported chain.

Locked decision #7 fixes only the *payout* rail. This build makes the inbound
leg Solana too. That removes a bridge from the demo, removes a second wallet
from the story, and makes the agent's payment and the human's payout the same
asset on the same chain — at a Solana Mobile hackathon. The flow doc should be
updated to match, or the decision reversed deliberately; it should not stay
ambiguous.

**A second correction:** x402 V2 is header-based, using `PAYMENT-REQUIRED` and
`PAYMENT-SIGNATURE`. Solana's guide states explicitly that V1's `X-PAYMENT`
fields must not be used in a new integration. This build uses V2.

## What is real here and what is simulated

Real: the 402 challenge and its Solana requirements, single-use payment
references, the escalation rule and its logging, the queue into the human feed,
the quorum, and the agreement calculation. The human's outbound USDC is the
existing claim path.

Simulated: **the agent's inbound payment is not settled on chain.**
`verify_payment` checks that a receipt is well-formed and unspent, not that a
transfer landed. The build spec permits this, and `/v1/judge` says so in its
own response — `payment_verification: "receipt shape only; not settled on
chain"` — so nobody reads a queued judgment as a confirmed transfer.

Also simulated whenever no Jev key is configured: the router falls back to a
fixed one that names itself `fixed-router`, and every response carries
`simulated: true`. A demo run without a classifier is never mistaken for one
with.

## Two structural choices

**Jev cannot answer the question.** `RoutingAnswers` has four probability
fields and no verdict field, so there is nowhere for a judgment to live. The
tempting future edit — let the classifier handle the easy ones — would have to
change the type, and a test asserts the field set. That is the difference
between a routing gate and a product that quietly stopped needing humans.

**An agent that does not need a human is not charged.** If the rule says no
escalation, `/v1/judge` returns `no_human_needed` and issues no price. Selling
a judgment nobody needed is the easiest way to make this dishonest, and the
endpoint cannot do it.

## Untuned

The four thresholds (0.70 / 0.60 / 0.50 / 0.50) are the spec's stated starting
hypothesis. `/agent/routing/recent` exposes every decision and the running
escalation rate precisely so they can be tuned against real agreement data
rather than left at their first guess.
