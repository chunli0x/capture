# Seeker phase 1 — approved contract

Status: accepted by Lisa on 2026-10-05 following the captcha review.
Baseline: captcha eec099a59f9790f65bfef7280df8fe3bd16e6c43.

This document supersedes conflicting examples in the uploaded v1 brief for
the object-photo slice. It does not assert that implementation is deployed.

## Decisions

- Keep Kotlin/Compose and the existing MWA wallet integration.
- Human-created labels only. Local liveness and offline cloud keypoints are
  permitted exceptions to the no-model rule. Neither proves unique humanity.
- One immutable captured asset receives independent blind annotations.
  The author/requester cannot review it. Two agreeing independent reviewers
  establish eligibility; requester acceptance authorizes payment.
- No consensus-only payout or timeout auto-acceptance. A deadline expires
  unpaid submissions, with requester refund of unallocated funds.
- USDC escrow and payment; separate SKR bond. No implicit conversion.
- Private temporary quarantine may exist before moderation. Only the exact
  fully approved content may enter the approved store. Provider errors and
  incomplete results fail closed. No caller may submit its own PASS verdict.
- Fraud alone can slash SKR. First slice does not auto-slash low-quality or
  duplicate submissions. Full fraud arbitration is a later phase.
- Canonical labels: integer category_id, normalized [x,y,w,h], at least one
  box, no extra fields; x+w and y+h cannot exceed 1. Time units in later video
  APIs are integer milliseconds. Taxonomy version is immutable per bounty.
- Per-bounty duplicate rejection. Upload retry is not a new submission.
- Financial truth is the program's escrow and per-submission settlement state.
  Backend state is durable and reconciles confirmed transactions; preparation
  never consumes credit. Retries cannot issue a second payment.

## Scope and trust boundary

Implement a separate `seeker` ASGI app alongside the existing Union demo;
the new service does not mount legacy unauthenticated reward routes. Keep
the old demo's behavior isolated rather than importing its in-memory ledger.
Harden reusable liveness proof binding and independent voting where used.
Use PostgreSQL in deployment; SQLite is an explicit local test/development
adapter only. Use a devnet-only program and labeled TEST-USDC/TEST-SKR mints.
Do not represent an allowlisted test wallet as independently verified human.
Registration authorization is an operator verification decision pending a
chosen unique-human provider. Public production launch remains blocked on it.

Reviewer compensation and platform SKR sponsorship are not invented here.
The object pilot uses an operator-enrolled reviewer pool and worker-funded
TEST-SKR. Rewards/limits/fees are explicit bounty fields; fees are zero in
this pilot. Reviewer payment needs a later commercial decision.

## Ordered implementation

1. Authenticated wallet challenge/session, actor-scoped idempotency, durable
   bounty/claim/media/review/settlement records and schema migration.
2. Fail-closed upload gate, content identity, bounded JPEG/PNG ingestion,
   private access, same-asset reviews and requester accept/reject/refund.
3. Per-bounty USDC escrow and per-submission payouts; persistent SKR bonds
   locked through pending liabilities; verifier-authorized fulfillment.
4. Kotlin wallet sign-in, object capture, normalized box editor, upload,
   submission, review, acceptance and transaction confirmation screens.
5. Negative and restart/retry tests, CI, devnet instructions and evidence.

Allowed paths: docs/SEEKER*, docs/adrs/, backend/seeker/, backend/migrations/,
backend/tests/test_seeker*, backend/requirements*, programs/seeker-bounty/,
Cargo.lock, Anchor.toml, scripts/*seeker*, android/app/src/, android/app/build.gradle.kts,
android/gradle/libs.versions.toml, .github/workflows/, and narrowly scoped
repairs in backend/tapfarm/liveness.py and backend/tapfarm/main.py with tests.
Preserve unrelated existing source and the main branch.

Rollback: discard the isolated development branch or revert its commits;
do not mutate any existing deployment or migrate a live database in this task.

## Proof obligations

Reject wrong-wallet signatures, replayed/expired nonces, stolen media,
unknown fields/categories, malformed boxes, duplicate/repeated/self votes,
no consensus, stale/replaced media and caller-supplied moderation results.
Prove every rejected stage has zero payment. Prove acceptance is requester-only,
amounts and asset mints are bound, refund cannot spend reserved rewards,
repeated confirmation does not pay twice and wallet cancellation loses no credit.
Exercise DB restart and concurrent writes, plus validator-backed transfers.
Report local/CI/deployed/provider evidence separately. No provider credentials,
hardware test or deployment success is inferred from mocks.
