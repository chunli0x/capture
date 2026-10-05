# Seeker phase 1 verification receipt

Verification date: 2026-10-05.

Reviewed scope: object-photo pilot on `seeker/object-bounty-v1`, based on
`eec099a59f9790f65bfef7280df8fe3bd16e6c43`. The approved contract is recorded
in `SEEKER-PHASE-1.md`; setup and remaining gates are in `SEEKER-RUNBOOK.md`.

## Delivered behavior

- Wallet-bound, expiring, single-use sign-in challenges and hashed sessions;
  explicit operator enrollment for test workers/reviewers.
- Durable PostgreSQL records, actor-scoped idempotency, row locks and uniqueness
  constraints; no backend debit during transaction preparation.
- Bounded JPEG/PNG ingestion, canonicalization, fail-closed Hive/Sightengine
  adapters, encrypted immutable approved media and private authenticated reads.
- Immutable manual taxonomy/boxes and two distinct blind reviews of the same
  image; disputed work cannot get a verifier co-signature.
- Per-bounty TEST-USDC escrow and per-submission requester acceptance; separate
  TEST-SKR bond, pending-liability lock, cooldown and protected refunds.
- Kotlin wallet sign-in, requester draft/funding/accept/reject, camera capture,
  box editing, review and transaction recovery; expired-session recovery.
- Release builds no longer use the debug signing key or allow HTTP traffic.

## Evidence

| Check | Observed result | What it proves |
| --- | --- | --- |
| Existing baseline backend | 503 passed, 13 skipped | Reproduced the original text snapshot before edits |
| Full backend plus Seeker tests | 530 passed, 13 skipped | API behavior, authentication, restarts, concurrency, parsing and local runtime assertions |
| PostgreSQL CI | 22 passed | Same API/client tests on a real PostgreSQL 17 service; not just SQLite |
| Rust workspace host tests | 46 passed | 42 existing tests plus 4 escrow accounting tests |
| Agave 4.3 SBF build | Successful locally and in CI | Program compiles for the actual Solana target |
| SBF in LiteSVM | 5 passed locally and in CI | Real SPL token CPIs and account/signature constraints in a local Solana VM |
| Kotlin debug unit suite | 67 passed | Existing 65 tests plus 2 box-coordinate tests; not device UI tests |
| Android debug build and lint | Successful local run | Compiles and packages the app; lint has nonblocking suggestions |
| Python dependency consistency and Ruff | Passed | Installed pins resolve and new Python source passes lint |

Runtime tests exercise successful exact-amount payout, rejection without pay,
wrong verifier/requester/mint/destination/bond identity, repeated settlement,
slot exhaustion, cooldown, pending liabilities, protected refund and expiry.
They also attempt config initialization by a caller who is not the program's
upgrade authority and verify rejection. These execute the compiled SBF rather
than substituting a Python model for on-chain behavior.

API tests explicitly inject fake chain/moderation services when checking the
HTTP workflow. Those tests are **not evidence of live cloud verdicts or devnet
payment**. Separate transaction-client tests verify real Ed25519 signatures,
exact prepared messages and partial verifier signatures. LiteSVM tests execute
token transfers entirely locally with disposable balances.

Provider CI evidence at the program/API checkpoint:
https://github.com/chunli0x/captcha/actions/runs/37356790219

The 13 original skipped tests require their own live-service/validator setup;
they were not silently relabeled as passing. The local APK does not establish
Seeker camera or MWA behavior. Use the branch's CI APK for subsequent hardware
checks; original binary assets remain preserved in GitHub's base tree.

## Measured Python coverage

The exploratory `pytest --cov=seeker --cov-branch` run reports about 88% combined
line/branch coverage. Per-file measurements below exclude the migration entry
point, which is not covered. Function coverage is not claimed; Rust and Android
coverage percentages were not measured.

| Source | Lines | Branches |
| --- | ---: | ---: |
| `seeker/api.py` | 93.4% | 83.8% |
| `seeker/chain.py` | 80.9% | 75.0% |
| `seeker/config.py` | 88.2% | 50.0% |
| `seeker/db.py` | 100.0% | 50.0% |
| `seeker/media.py` | 90.8% | 56.2% |
| `seeker/schemas.py` | 98.4% | 75.0% |

The default 95% benchmark is **not met**. This repo has no configured mandatory
coverage gate; this receipt does not claim a 95% pass. Uncovered areas include
RPC transport/reconciliation error variants, environment validation, provider
success/error permutations and some API edge states. Before broader rollout,
add contract fixtures from enabled providers and more transport fault tests.
Optional follow-up: persist the measured coverage command and an agreed required
threshold in repo tooling; no new coverage policy was silently imposed.

## Deliberately not claimed

No production or devnet deployment, live provider validation, actual wallet
payment, real Seeker capture test, unique-human verification, training license,
legal compliance, fraud adjudication, slashing, paid reviewer pool, places or
video/action flows are claimed. The verifier is a trusted eligibility signer.

The original Union demo's in-memory reward routes remain unchanged. Seeker does
not mount or import them, and its separate program/config cannot be paid through
those demo routes. This is isolation of the new pilot, not a claim that all
legacy review findings have been repaired.

No main-branch update, pull request, release signing, migration of a live DB or
public deployment was performed. Review this branch before supplying live
service credentials or enrolling real participant content.
