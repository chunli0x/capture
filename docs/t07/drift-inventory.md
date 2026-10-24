# T07 first slice — snapshot drift inventory

Audit date: 2026-10-24. Owner: A6. Reviewers: A10 + A4. Status: audit and proposed plans only; reconciliation has **not** been executed. No token is selected.

Sources read: T07 packet, page 13 of `Teddy-Companion-30-Day-Execution-Plan.pdf` (cached `doc_ba50ccea93dc_…`); `/home/hermes/companion/docs/30-day-plan/execution-board.md`, A6 role and T07 row; repository README and both requested documents. T07 depends on T01 and A7's chosen experiment. This slice does not deliver the later dataset manifest, expert quality report, or cost-per-example calculation.

| Snapshot | Local ref | Exact commit |
|---|---|---|
| R7 / A | `main` | `eecca02f93384fd4a8b511b60905679046ae97c7` |
| R8 / B | `skr-bond-payout` | `d77a6982b68d4c56311d62921fedff742078a383` |
| Common ancestor | — | `46db15fec4c74e9737b0dcc9b339b3237e43839f` |

All comparisons are **A → B**, not working-tree changes. There are 34 changed paths, 341 inserted / 964 removed lines. [Full diff](evidence/main-to-skr.diff), [all changed paths](evidence/changed-files.txt), and [scoped file hashes](evidence/snapshot-files.json) make the inventory reproducible. `A:path:line` and `B:path:line` below refer to these fixed snapshots; use `git show <commit>:<path>` for B references.

## 1. API and storage fields

`backend/seeker/schemas.py` is byte-identical: no request-schema or validation change. It contains request models, not response models, so its equality does **not** imply response compatibility. Endpoints and auth scheme are unchanged; renamed JSON keys have no compatibility aliases.

| Surface and line (same in A/B api.py) | A exact key | B exact key | Value / meaning |
|---|---|---|---|
| `/health`, 192 | `usdc_mint` | `skr_mint` | `settings.usdc_mint` → `settings.skr_mint`; public mint defaults in §2 |
| `/health`, 204 | `usdc_payout` | `skr_payout` | `ready` if treasury object exists, else `unavailable`; not proof of funded/working payout |
| `/me`, 266 | `bond_test_usdc_units` | `bond_test_skr_units` | `settings.min_bond`, default `1_000_000` |
| `/me`, 268 | `usdc_funded` | `skr_funded` | actor Boolean, default false |
| `/me`, 272; `/judge/stats`, 868 | `staked_usdc` | `staked_skr` | actor integer, default 0; deposit mirror `min_bond`, withdrawal/slash 0 |
| `/judge/stats`, 866 | `base_usdc` | `base_skr` | default `20_000` base units |
| `/judge/stats`, 867 | `flat_usdc` | `flat_skr` | default `5_000` base units |
| `/judge/stats`, 870 | `earned_usdc` | `earned_skr` | sum of all judgment obligations for wallet |
| `/judge/stats`, 871 | `settled_usdc` | `settled_skr` | sum restricted to `payout_signature IS NOT NULL` |

`backend/seeker/db.py` has exactly three mapped column renames: `seeker_actors.usdc_funded` → `skr_funded` (line 51, Boolean default false); `seeker_actors.staked_usdc` → `staked_skr` (66, BigInteger default 0); `judgments.earned_usdc` → `earned_skr` (154, BigInteger default 0). Types/defaults are unchanged. There is **no current mapped `judgments.settled_usdc` or `settled_skr` column**: that pair exists only as a legacy migration mapping; API settled totals are derived. Token comments also change. Journals, IDs, signatures, liability flags and pair states are identical.

`api.py` changes internal references at 524, 557, 588, 804, 815, 821, 844, 850, 981, 985 to those renamed amounts/fields. Settlement invocation becomes `chain.settle_skr(wallet, earned_skr, memo=judgment_id, persist=…, prepared=…)` instead of `settle_usdc`.

Exact user-visible backend string changes (A → B):

| api.py line | A | B |
|---|---|---|
| 330 | `Devnet test-USDC faucet ("Get test USDC")` | `Devnet test $SKR faucet ("Get test $SKR")` |
| 346 | `Test-USDC faucet unavailable: {exc}` | `Test $SKR faucet unavailable: {exc}` |
| 364, 389 | `Get test USDC first` | `Get test $SKR first` |
| 651 | `deposit the USDC bond to judge` | `deposit the SKR bond to judge` |
| 720 | `USDC payout pending for some judges; retry to reconcile` | `$SKR payout pending for some judges; retry to reconcile` |
| 762 | `Deposit the USDC bond to judge` | `Deposit the SKR bond to judge` |
| 771 | `Bond is slashed; deposit a fresh USDC bond to judge` | `Bond is slashed; deposit a fresh SKR bond to judge` |
| 773 | `Bond vault is empty; deposit the USDC bond to judge` | `Bond vault is empty; deposit the SKR bond to judge` |
| 775 | `Bond is not active on-chain; deposit the USDC bond to judge` | `Bond is not active on-chain; deposit the SKR bond to judge` |
| 832 | `USDC payout pending; retry to reconcile` | `$SKR payout pending; retry to reconcile` |

The wire-contract document is identical but stale on both: it describes a resolved response including `aligned`, `earned_usdc`, `preference`, while `_settle_and_finalize` returns `{"status": "resolved", "preference": …, "agreement": …, "confidence": …}` without per-caller `aligned`/`earned_*`; `/judge/next` uses a 200 `kind: none` response for no work rather than the documented 404. B additionally contradicts every USDC response key in that document. Neither snapshot provides the T07 versioned lineage export.

## 2. Environment, setup and dependency drift

| Location | A | B |
|---|---|---|
| `.env.example:25`, `scripts/dev_bootstrap.sh:26`, Rust `declare_id!:5`, `Anchor.toml:11` devnet entry | `8pY9dpwhe4Tbv9Ud9r13WCrNkugirsELNKA3hwfUUdpu` | `5TiDwP86k95yfQWzExrPTj5qcKxED99z8pW9fN81u5SV` |
| Settings required field (`config.py:15` A / 16 B) | `usdc_mint` / `SEEKER_USDC_MINT` | `skr_mint` / `SEEKER_SKR_MINT` |
| Settings rates (`config.py:49–50` A / 50–51 B) | `judge_base_usdc=20_000`, `judge_flat_usdc=5_000` | `judge_base_skr=20_000`, `judge_flat_skr=5_000` |
| Corresponding env names | `SEEKER_JUDGE_BASE_USDC`, `SEEKER_JUDGE_FLAT_USDC` | `SEEKER_JUDGE_BASE_SKR`, `SEEKER_JUDGE_FLAT_SKR` |
| `scripts/load_judgment_images.py` | absent | mode `120000` symlink with literal target `/home/hermes/capture-images/load_judgment_images.py` (line 1); external target not followed |
| Android release setup | explicit HTTPS/health check and persistent signing config | those checks/config absent; release operator comment only |
| `.gitignore` | ignores `android/signing.properties`, `*.jks`, `*.keystore` | those exclusions absent |
| `android/signing.properties.example` | six-line template exists | absent |

Both env examples and bootstraps still emit **both** mint variables, unchanged:

- `SEEKER_USDC_MINT=TXtqUVPDj6JuDoeyFJvwuUqy5jGYTgF98kEkbeN6U8Z`.
- `SEEKER_SKR_MINT=3aGKaVL7GpcTcTuKjkyirnVeyNG1JGFNyGGueu8mAGbM`.
- `SEEKER_RPC_URL=https://api.devnet.solana.com`, `SEEKER_CLUSTER=devnet`, `SEEKER_DOMAIN=localhost`, `SEEKER_VERIFIER_KEY_FILE=verifier.dev.json`.
- Database template: `postgresql+psycopg://seeker:seeker@localhost:5432/seeker`; opt-in SQLite `sqlite:///./seeker.db` + `SEEKER_LOCAL_SQLITE=true`.

`Settings(extra="ignore")` means the unused mint and old rate env names can be silently ignored. Operator/media/moderation placeholders and `SEEKER_USDC_TREASURY_KEY_FILE` are absent from the current Settings model on **both** branches. `.env.example:40–46` still claims separate SKR faucet/USDC payout treasuries and DB-only faucet success with no key; actual code uses one `treasury_key_file` and fails closed when absent. These are stale setup claims, not functioning bypasses. No real `.env` or key contents were inspected.

`backend/requirements.txt` and `requirements-seeker.txt` are identical. Exact pins: `fastapi==0.141.1`, `uvicorn[standard]==0.34.0`, `solders==0.29.0`, `solana==0.40.3`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`, `pillow==12.3.0`, `numpy==2.4.6`, `pytest==8.4.2`, `pytest-asyncio==1.4.0`, `httpx==0.28.1`. The seeker file includes `-r requirements.txt` plus `SQLAlchemy==2.1.3`, `psycopg[binary]==3.3.6`, `cryptography==46.0.5`. The base file alone does not declare SQLAlchemy required by this API. Bootstrap installs the seeker file. README/CI target Python 3.11; this run's active Python is 3.14.9.

Shared setup inconsistencies: `Anchor.toml:8` localnet entry remains `5TiDw…` even on A whose compiled identity is `8pY9…`; README and API contract also retain `5TiDw…`. Android defaults to `http://10.0.2.2:8001` while README's uvicorn command serves 8000. `.github/workflows/seeker.yml:29` names four test modules absent from both trees (`test_seeker_flow.py`, `test_seeker_audit_concurrency.py`, `test_seeker_slash.py`, `test_bond_gate.py`). No CI or external services were run.

## 3. Migrations — opposite directions, same filenames

| File | A | B |
|---|---|---|
| `0011_judgment.py:14` | add `seeker_actors.staked_usdc BIGINT DEFAULT 0` | add `seeker_actors.staked_skr BIGINT DEFAULT 0`; description says `$SKR` |
| `0012_skr_payout_journal.py:1–4` | description says `USDC` / `earned-USDC` | says `$SKR` / `earned-$SKR`; same `judgments.settling BOOLEAN DEFAULT FALSE` DDL |
| `0013_batch_anchor_state.py` | `judgment_batches.anchored BOOLEAN DEFAULT FALSE` | identical |
| `0014_faucet_count.py:3–5` | description `test-USDC`, `usdc_funded` | `test-$SKR`, `skr_funded`; same `seeker_actors.faucet_count INTEGER DEFAULT 0` DDL |
| `0015_judgment_liabilities.py` | liability and signed-payout journal additions | identical |
| `README-seeker.md` | old version-1 guidance | identical; says schema never automatic, contradicted by `api.py:110–111` |

0015 adds `judgments.liability_legacy BOOLEAN NOT NULL DEFAULT TRUE`; `liability_reserved`, `enforcement_requested`, `enforcement_penalty`, `enforcement_complete` each `BOOLEAN NOT NULL DEFAULT FALSE`; `payout_transaction VARCHAR(4096)`, `payout_pending_signature VARCHAR(88)`, `payout_last_valid_height BIGINT`. Existing rows are tagged legacy, unlike the ORM default false for new votes.

`backend/seeker/migrate.py:17–22` renames **SKR → USDC on A** and **USDC → SKR on B** for four pairs: actor funded, actor stake, judgment earned, and legacy judgment settled. The runner only renames when old exists and new is absent. If both columns exist it silently skips the rename, with no equality check or reconciliation. It then adds missing numbered columns in filename order. There is no durable migration-version/checksum ledger or down migration. `create_all` precedes it in both CLI and API startup. Switching executables can therefore rename a shared DB in opposite directions automatically. A numeric rename cannot transfer assets between mints or program IDs.

## 4. README, documentation and screenshots

README and `docs/judgment-api-contract.md` are **byte-identical**, not reconciled. Both still describe USDC. `docs/HIGH-SEVERITY-FIXES.md` exists only on A (114 lines); do not interpret its historical test/deployment notes as current verification. It also predates A's later program-ID change.

All five JPEGs are byte-identical across snapshots (individual SHA-256 and Git blob hashes in the evidence JSON). All were visually inspected:

| Screenshot | Observed unchanged content on A and B |
|---|---|
| `01-judge-mountains.jpg` | `DEVNET · TEST USDC`, earn test USDC, `1 USDC` staked; mountain comparison |
| `02-judge-interior.jpg` | same token text/amounts; interior comparison |
| `03-calibrate-guide.jpg` | USDC badge, `$0.02 × 1.00 = $0.0200`, `$0.005` neutral pay; devnet/not-real-value footer |
| `04-calibrate-standing.jpg` | USDC badge, `$0.0200`, `$0`, `$0.005`, `0 USDC` earned; not-real-value footer |
| `05-balances.jpg` | USDC badge; earned/pending/settled `0 USDC`, staked `1 USDC`; devnet-only/not-real-value text |

B's Android screens change `USDC` → `$SKR` in balances, bond, calibration, judgment, onboarding and sign-in/header text; screenshots do not. Exact wording is preserved in the full diff and assessed in [token audit](token-claim-audit.md). Client fields rename `bondTestUsdcUnits` → `bondTestSkrUnits`; `judgeStakedUsdc`, `judgeBaseUsdc`, `judgeFlatUsdc`, `judgeEarnedUsdc`, `judgeSettledUsdc`, `judgePendingUsdc` each replace suffix `Usdc` with `Skr`; helper `formatPayUsdc` → `formatPaySkr`. Six decimals are unchanged. `optLong`/`optBoolean` defaults can make a mismatched client show 0/unfunded instead of a contract error.

## 5. Security/ABI drift that blocks a mechanical reconciliation

B's backend is newer than its Rust contract in important ways. Both `chain.py:383–419` call `reserve_judgment` / `resolve_judgment`, but B's Rust has neither instruction nor `Liability` account. Both backends use a `payment-v2` PDA bound to mint, recipient, amount and payment ID (`chain.py:434–448`), and expect the program to mint atomically. A's Rust implements this (`lib.rs:175–285,350–369,481–533`); B's `record_payment` accepts only the ID, creates the old `payment` PDA, stores only `mint_authority`, has no mint CPI and does not bind the signer to a configured mint authority (`lib.rs:179–193,244–247,361–370`). These are source-level incompatibilities, not live RPC findings.

B also resets `bond.pending=0` on a terminal-slash redeposit (`lib.rs:55–57`), where A requires pending zero before resetting warnings (`53–55`). B lacks A's resolution-warning host test and many adversarial LiteSVM tests. B's Android has the explicit camera bypass and weaker spoof continuity described in [bypass inventory](demo-bypass-inventory.md), and lacks A's release distribution checks. Preserve the stronger invariants whichever token Lisa selects; that recommendation does not select a token or authorize deployment.

Read next: [reconciliation and rollback plan](reconciliation-plan.md), [token claims](token-claim-audit.md), [demo bypasses](demo-bypass-inventory.md), [actual verification](verification.md).
