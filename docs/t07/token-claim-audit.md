# T07 — token status and claim audit

Verdict: **both source snapshots are devnet/localnet test-only designs; neither is evidence of real-value USDC or SKR settlement.** A implements test USDC; B implements test `$SKR` in backend/client names but retains USDC README, wire contract and screenshots. Token choice is unresolved and belongs to the operator. No external RPC, token metadata, live service or deployed program was queried.

## Exact token identity evidence

| Evidence | A / main `eecca02` | B / skr-bond-payout `d77a698` |
|---|---|---|
| `config.py` required mint | `usdc_mint` (15) | `skr_mint` (16) |
| `.env.example:26–27` | both public mint values present; active USDC `TXtqUVPDj6JuDoeyFJvwuUqy5jGYTgF98kEkbeN6U8Z` | both present; active SKR `3aGKaVL7GpcTcTuKjkyirnVeyNG1JGFNyGGueu8mAGbM` |
| `/health` `api.py:186,190–205` | network from Settings, `test_tokens=true`, `usdc_mint`, `usdc_payout` | same honesty flag, `skr_mint`, `skr_payout` |
| Android `BalanceScreen.kt:39`, `OnboardingScreen.kt:147`, `SeekerApp.kt:137` | test USDC / devnet / not real value | test `$SKR` / devnet / not real value |
| README `50–51,98–118` | test USDC / fixture mint / devnet | identical USDC text, inconsistent with B implementation |
| API contract `7,12–15` | test USDC / devnet | identical USDC text, inconsistent with B implementation |

Settings defaults are `cluster="devnet"`, RPC `https://api.devnet.solana.com`. `config.py:63–64` A / 64–65 B rejects clusters other than `devnet` or `localnet`. `chain.py:130–141` on both checks devnet genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG` or requires a localnet loopback RPC host; `check_environment` also binds config owner, verifier, mint, minimum bond and slash authority. Android wallet adapter uses `Solana.Devnet` (`SeekerViewModel.kt:119`). This confirms intended source restrictions, **not** the state of an unknown deployment or uninspected `.env`. A localnet hostname restriction is not independent proof of a private validator's genesis.

The example mints are six-decimal fixture identities; names do not establish backing, redemption or association with real assets. Both faucet implementations directly mint test tokens and supply test SOL from a treasury. Neither is a demonstrated revenue/payment product. B's source ABI mismatch further blocks a working-settlement inference.

## Wording that implies real value or unsupported readiness

These are audit findings; no public copy was edited.

| Location (both unless noted) | Exact existing wording / value | Claim concern and future disposition |
|---|---|---|
| README:64–66 | `$0.02 per aligned judgment`, `$0.005`, `USDC is 1:1 USD` | nearby test disclaimer does not make a controlled devnet fixture redeemable dollars; remove dollar equivalence or explicitly label hypothetical assumptions in a later approved copy change |
| README:72–74 | `$5.28/hr`, `$6.70/hr`, `$9.31/hr` at 240/hr | illustrative earnings, not observed income; neither throughput nor real payout demonstrated here |
| README:82–90 | `$0.020/label`, `~$540`, `~$9,000`, `~$0.30/judgment`, `~125 hours`, `zero operator time replaces $9k or 125 hours` | unvalidated economic/comparative claims; omit reviewer/retry/QA/operator costs required by T07 |
| README:92–94 | `earn USDC → stake more USDC → unlock higher tiers → earn faster`, `reinvest it to earn more` | investment/compounding implication; ladder is agreement-driven, not a demonstrated financial return |
| README:103–105 | `Settlement is real on-chain` | can describe execution, not value; deployment/transactions were not verified, and B source is internally incompatible |
| README:111–116 | deployed/live, `46 backend tests`, `6 unit tests`, clean BPF, `USDC everywhere`, program `5TiDw…`, `upgradeable` | historical unverified claims; A now configures another devnet program ID; B's token is not USDC everywhere |
| API contract:25–29 | `USDC is 1:1 USD`, `0.02 USDC = $0.02`, `0.005 USDC = $0.005` | same fixture/dollar conflation; B additionally uses another token |
| A config.py:37,47–48 | `test USDC (1:1 USD, 6 decimals)`, `= $0.02`, `= $0.005` | developer comments carry the same misleading equivalence; B replaces with explicit test SKR/not-real-value wording |
| Android `CalibrationScreen.kt:198,256–268` | literal dollar prefix in `Pays $…`, rate multiplication, `Disagreement pays $0`, `"Can't tell": $… flat` | survives B's rename to `formatPaySkr`; formatting still presents dollar-like amounts even beside a `$SKR` label |
| Screenshots `03`, `04` | `$0.0200`, `$0`, `$0.005` | fixed USDC/dollar artwork on both, despite devnet/no-value footers; not evidence of B's current UI |
| `BalanceScreen.kt:39`, `BondScreen.kt:52` | `Earned…staked…`, `real on-chain escrow` | scoped by test/devnet text; preserve distinction between actual test execution and monetary value when refreshing copy |
| `api.py:187,204–205` | `production_ready` can be true; payout `ready` based on treasury object existence | checks do not certify pilot readiness, current program instruction capabilities, funding or real-value settlement |
| `api.py:321–322` | `a live person performed a motion challenge on-device` | unverified client assertion; B's demo button fabricates a nonzero digest, so this wording can overclaim even motion execution |
| README:40–43; API contract §8 | dataset provenance / anchor claims; contract says anchor deferred because deployed program immutable | README says live/upgradeable and code attempts anchoring; neither deployment claim verified. Existing root omits media/model/consent/split/judgment provenance |

Positive qualifiers that must not be lost: README:50–54 explicitly states no real value and majority-preference bias; Android onboarding/balances/footer likewise disclaim value; `/health` always includes `test_tokens=true` and `dataset_bias="majority-preference"`. Majority agreement must never be relabeled factual truth. Dollar signs within the symbol `$SKR` alone are a ticker style, not evidence of USD denomination; the numeric dollar prefixes above are a separate ambiguity.

## Decisions needed from the operator

- Canonical test-token name **and** network/program/mint identity; migration treatment of old demo records and outstanding obligations.
- T01-approved boundaries for earnings/economics, on-chain/provenance, liveness and readiness claims; owner to refresh screenshots after the approved client works.
- Whether/when a pilot may accept these demo protections; adult/consent requirements, task choice with A7, and human review with A4/A10 must be settled before exposure.

Neither branch is approved for pilot release by this audit. That conclusion is based on specific inconsistencies and missing verification, not a token preference.
