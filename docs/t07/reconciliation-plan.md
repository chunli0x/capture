# T07 — proposed reconciliation, migration and rollback

**Plan only. No merge, migration, deployment, key use or token selection occurred.** This proposal applies to R7 `eecca02` and R8 `d77a698`; [inventory](drift-inventory.md) contains the full identities and evidence. The audit branch starts from main solely to host documentation.

## Decisions and prerequisites

The operator must approve the canonical **test** token, network/program/mint identity tuple and intended client/API compatibility policy. A token symbol is insufficient: both are six-decimal test fixtures with different mint addresses and program namespaces. Decide whether existing demonstration records are to be retained as historical datasets, continued under their original asset identities, or retired after reconciliation. Never infer that equal integer amounts represent the same asset.

A6 then prepares implementation; A4 reviews lineage and label-quality semantics; A10 independently verifies. The operator (T01) must settle release boundaries and adult participation/consent requirements; A7 must select the experiment task before task/rubric and split protocols are frozen. This slice grants no authority to expose a pilot, use an operator key, publish copy or perform chain writes.

## Reconciliation sequence for a later implementation slice

1. Freeze both source SHAs and inventory actual deployment artifacts, schema and pending work with an authorized operator. Record program binary hash, account layout/IDL, network genesis, mint decimals and authority **public keys**, API/client versions and redacted effective configuration. Current deployment state was not inspected in this offline audit.
2. Write one versioned wire contract for the approved identity. Map every field in the inventory across backend, Android, settings, DB and docs. If a compatibility period is needed, define explicit version negotiation and token metadata; do not silently alias balances across distinct mints. Reject wrong-family client/server combinations instead of allowing the Android defaults to display false zero balances.
3. Reconcile security semantics independently of token branding: atomic exact-payment receipts; one reservation and immutable enforcement result per judgment; no pending-liability reset on redeposit; durable retries; liveness at GET and direct POST; bounded faucets; release configuration/signing checks and credential ignore rules. Port these to the approved identity without assuming B's Rust implements what its Python calls. Retain legacy receipt verification and fail closed on mismatches. No blind whole-file replacement or automatic “ours/theirs” choice.
4. Replace opposing, implicit startup renames with an explicit, reviewed migration step and schema-version compatibility check. Record migration IDs and checksums; API runtime should not perform DDL. Handle dual-column databases as conflicts requiring comparison, not a silent no-op. Keep additive history/provenance fields through the rollback window.
5. Reconcile setup: one approved program ID across Rust, Anchor localnet/devnet entries as appropriate, env templates, bootstrap and fixtures; one documented active mint and treasury model; Python/dependency instructions matching actual imports. Replace B's absolute external image-loader symlink with reviewed repository-owned tooling in a later change. Fix missing test paths in CI and require the relevant runtime fixture build for contract acceptance.
6. Prepare README/API wording and newly captured screenshots **after** the identity decision and working client/API checks. The operator approves claims via T01; this audit leaves all existing public-facing copy and images untouched. Dollar economics must distinguish test units from actual costs and include reviewer, retry, QA and operator effort.
7. A10/A4 review the concrete implementation and evidence. Only a separately authorized operator can carry out the rollout below. A passing host suite alone cannot establish deployed ABI compatibility, device security or dataset quality.

## Migration order (future operator procedure)

### A. Quiesce and establish a recovery point

Stop API writers, faucets, new judgments, deposit/withdraw preparation, payout/enforcement retries, seed/import jobs and client traffic. Drain in-flight operations; record finalized signatures, outstanding blockhash expiry heights and any uncertain broadcasts. Do not assume a timeout means a transaction did not land.

Back up the DB and verify restoration into an isolated copy. Save row counts, IDs, per-asset stake/earned/settled aggregates, faucet counters, pair states, calibration history, batch roots, liability/enforcement journals, prepared transactions and signed payout transaction bytes. Treat signed bytes as restricted recovery material, never as public audit attachments. Save original schema/version, deployed binary/IDL and redacted config; preserve operator keys in their existing custody, not in this repo.

### B. Rehearse schema and data conversion on copies

Order: inventory old schema → create missing tables for the chosen model → inspect/resolve legacy rename mappings → apply 0011 → 0012 → 0013 → 0014 → 0015 → future additive lineage/version migrations. For existing tables, resolve the rename **before** adding a default-zero replacement column. Numbered files are shared names with different content; pin checksums, not just `0011` labels.

| Source shape | Required treatment |
|---|---|
| USDC columns only, approved storage remains USDC | preserve names/amounts and original mint/program metadata |
| SKR columns only, approved storage remains SKR | preserve names/amounts and original mint/program metadata |
| Source family differs from approved storage naming | explicit four-pair mapping from inventory; only treat as a pure rename if asset identity is independently proven unchanged; otherwise preserve the old asset ledger separately |
| Both old/new columns exist | compare every row, null/default semantics and aggregate amounts; stop on disagreement; never sum or overwrite automatically |
| Neither family / fresh DB | create approved schema; test defaults, FK/unique constraints and empty journals; do not fabricate funded balances |

The four rename pairs include legacy `judgments.settled_*`, but current ORM has no such column. Preserve any legacy column found rather than inventing it on fresh DBs. Also inventory older tables for `*_funded` and `earned_*` omissions: `create_all` does not add missing columns to existing tables and 0011–0015 do not cover every historical possibility. An incomplete schema needs an explicit additive migration, not an application start experiment.

Preserve `judgment_id`, `pair_id`, `batch_id`, all signatures and amounts, `settling`, liability/enforcement flags and payout bytes/expiry exactly. 0015's existing-row `liability_legacy=true` is deliberately different from fresh ORM false. Do not mark any accepted vote reserved until its actual chain liability is confirmed. Preserve neutrals, dissent and unresolved votes; do not backfill consensus as factual correctness.

### C. Establish matching program capability before writers restart

For an upgrade within the same program/mint namespace, the authorized operator must establish compatibility and program capability for atomic `record_payment`, `reserve_judgment`, `resolve_judgment`, and `post_batch` before the new backend sends them. Account-layout compatibility of Config/Bond alone is insufficient: legacy `payment` and `payment-v2` receipt namespaces differ.

For a changed program ID or mint, this is a **new ledger namespace**, not a DB rename: bonds, penalty vaults, payments, liabilities and batches are program/mint-derived. Keep old obligations attached to the old identity, settle or retire them by an approved explicit process, and require genuinely confirmed new-asset funding/deposits. No automatic 1:1 balance conversion, re-mint of historical earnings or copying `bonded=true` to the new deployment. Append-only batch anchors need explicit linkage to historical roots, not overwriting them.

After schema and matching program capability are ready, with API still stopped, the authorized operator follows the liability backfill procedure in `docs/HIGH-SEVERITY-FIXES.md:43–59`. `python -m seeker.liabilities` **writes on-chain**; it is recorded here solely as a future step, not executed. Investigate missing/slashed/withdrawn legacy bonds instead of inventing reservations. Review old resolved penalties against chain history: the missing historical enforcement journal cannot be reconstructed by blindly replaying slash actions.

### D. Reconcile, validate, reopen

Reconcile uncertain payouts against exact finalized receipts/transactions in their original namespace before retrying. Preserve the same payment/resolution IDs, so retries cannot duplicate minting, warnings or slashes. Reconcile pending `resolving` / `enforcing` pairs and unanchored roots without pretending to anchor a full dataset manifest. Confirm all writer instances and clients use the same schema/API version.

Acceptance checks on isolated fixtures: fresh and both legacy schemas; deliberately conflicting dual columns; migration rerun with zero changes; counts and per-asset totals preserved; neutral/dissent rows retained; signed-byte and signature continuity; failed/expired/confirmed transaction retry paths; no premature liability release; no stale program/mint clients; liveness and release checks; PostgreSQL concurrency (SQLite alone is insufficient). Run backend, Rust host and matching SBF/LiteSVM tests; Android checks and a device exercise are required before client/pilot acceptance. Record skips as missing coverage. Reopen a controlled test environment only after A10/A4 review and the required separate authorization.

## Rollback and stop conditions

Stop for mismatched program/mint/authority, dual-column disagreements, unexpected row/amount deltas, lost journals, unknown chain outcomes, unsupported instruction/account layout, or failed mandatory checks.

1. Keep writers paused. Snapshot failed-upgrade state, new signatures, finalized receipts, liabilities and roots; retain both pre- and post-change DB copies.
2. **Before any new external writes:** restore the tested pre-change DB snapshot and matching application/config artifacts, or apply a rehearsed inverse rename only when it is strictly a naming change, old names are absent and per-row equality is proven. Never run the opposite branch's migrator as an unexamined down migration. Do not drop journals/additive columns merely to make old code start.
3. **After any on-chain write:** do not restore an old DB and resume blindly. Finalized transfers, minted tokens, slashes, liabilities and append-only anchors are not undone by Git or DB rollback. Reconcile post-backup chain effects into a recovery DB with exact IDs/signatures first; keep failed attempt evidence. Prefer a forward-compatible repair over reverting to B's incompatible/less protected program.
4. A program binary rollback, if even possible, requires the operator's separately established upgrade authority and account/receipt compatibility. This audit does not establish either. Never imply that reverting code restores chain state or that an immutable deployment can be upgraded.
5. Restore the matching client/API version pair, keep the approved asset identity and original obligations intact, and rerun balance/journal/schema/health checks. A10 reviews recovery evidence before reopening; the operator approves any changed release/claim scope. Unresolved liabilities mean the service stays paused for the operator, not silently written off.

## Later T07 lineage/quality slice — proposed interface, not delivered data

Current export (`api.py:874–904`) returns resolved pair IDs, URLs, preference/agreement/confidence, media/task types and rubric. Current Merkle leaves (`judgment.py:54–76`) hash only `pair_id|preference|agreement|confidence`, sorted by pair ID by the caller; odd nodes are duplicated at each tree level. The root does **not** bind media bytes/URLs, model revision, rubric, consent, split or individual judgment provenance. The API omits neutral and dissenting vote records from this export. `anchored=true` therefore cannot establish T07 manifest lineage or factual truth.

A later versioned manifest should bind: schema/export version; source snapshot and reproducible export code/config; media content SHA-256 and storage version; model/checkpoint and generation revision; task/rubric versions; per-judgment pseudonymous provenance, time, display-order mapping, raw choice/rating, neutral/dissent and review outcome; consent/usage basis and retention reference; duplicate/group IDs and immutable train/validation/test split; quality protocol/version and actual review evidence. Define canonical encoding, float/null handling, ordering, hash algorithm and exclusions; require independently repeatable bytes/hash. Keep private linkage records access-controlled.

Use a separate manifest version/anchor namespace or new batch identity to preserve old append-only roots; link old aggregate roots explicitly. Claim manifest provenance only after its exact hash is committed and the receipt recorded under an authorized later task. Add expert-checked calibration, randomized A/B assignment with logged mapping, duplicate/attention checks, disagreement review and anti-collusion analysis. A4/A7 decide task-specific criteria; costs include reviewers, retries, QA, operator time and infrastructure. No dataset quality, learning gain or real unit-economics result is claimed by this audit.
