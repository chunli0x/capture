# T07 — actual verification record

Date: 2026-10-24. Code tested/attempted: main `eecca02f93384fd4a8b511b60905679046ae97c7` on documentation branch `t07-capture-reconciliation-audit`. B was read from Git objects, not checked out or executed. No source/test changes were made.

## Backend: blocked before test collection

Requested command, run with cwd `/home/hermes/capture-usdc/backend`:

```text
python3 -m pytest -q
```

Exit status **1**. **0 tests executed; no pytest pass/fail/skip summary was produced.** Thus there are no observed assertion passes or failures (0 executed passes, 0 executed failures); this is an environment failure, not a passing suite. Active Python: **3.14.9**. Full output and exact tail ([raw log](evidence/pytest-main.txt)):

```text
/home/hermes/.hermes/installs/019d0d114d22b7e6/environments/dc22c47018554871905857f1c5fd737f/venv/bin/python3: No module named pytest
```

Inherited `SEEKER_*` variables were removed from the subprocess environment; `.env` was not loaded. `PYTHONDONTWRITEBYTECODE=1` and repo-local `TMPDIR=/home/hermes/capture-usdc/target/t07-tmp` confined disposable artifacts. Neither `backend/.venv` nor `backend/venv` existed. The active interpreter also lacked pip.

A venv was created inside the allowed repo at `target/t07-venv` using `python3 -m venv`. Its bundled pip was 26.2.2. The authorized dependency fallback was attempted strictly offline and only against `backend/requirements.txt`:

```text
target/t07-venv/bin/python -m pip install --no-index --disable-pip-version-check --no-cache-dir -r backend/requirements.txt
```

Exit status **1**. [Exact setup log](evidence/python-offline-setup.txt):

```text
ERROR: Could not find a version that satisfies the requirement fastapi==0.141.1 (from versions: none)
ERROR: No matching distribution found for fastapi==0.141.1
```

No dependencies were downloaded and no subsequent test success is claimed. This means no distribution was available to this offline install command; it does not establish whether the pin exists on a remote package index. Do not reuse README's “46 passed” or HIGH-SEVERITY-FIXES' historical “63 passed” as this run's result. A later prepared environment also needs the seeker dependency overlay (SQLAlchemy, psycopg, cryptography), which base requirements alone do not declare; this audit did not expand the authorized install scope.

## Anchor host tests: toolchain present, dependency resolution blocked

Existing `rustup toolchain list`:

```text
stable-x86_64-unknown-linux-gnu (active, default)
1.95.0-sbpf-solana-v1.57
```

Requested command attempted from repo root:

```text
cargo test -p seeker-bounty --lib
```

Environment: `CARGO_NET_OFFLINE=true`, `RUSTUP_OFFLINE=1`, `CARGO_TARGET_DIR=/home/hermes/capture-usdc/target/t07-host`, repo-local `TMPDIR`. Exit status **101**. **0 Rust tests executed; no pass/fail summary produced.** It was not skipped for a missing toolchain; it failed before compilation due to unavailable cached dependency. Exact output ([raw log](evidence/cargo-main.txt)):

```text
error: no matching package named `anchor-lang` found
location searched: crates.io index
required by package `seeker-bounty v0.1.0 (/home/hermes/capture-usdc/programs/seeker-bounty)`
note: offline mode (via `--offline`) can sometimes cause surprising resolution failures
help: if this error is too confusing you may wish to retry without `--offline`
```

The suggested online retry was not taken because this task is offline. No Rust/Solana/Anchor toolchain was installed; no SBF build was run. `target/deploy/seeker_bounty.so` was absent, so the current pytest runtime module would skip its program execution tests in a functioning Python environment unless a separately prepared artifact is supplied. No skip count is reported as observed because collection never began.

## Audit validation and limits

- Verified exact branch tips and common ancestor locally; worktree began clean. Generated complete A→B text diff and scoped SHA-256/Git blob inventory, including all five screenshot comparisons. Visually reviewed every screenshot.
- Recomputed every recorded source SHA-256 and checked all local document links successfully. Authored docs/logs pass `git diff --cached --check` when excluding the raw `.diff` evidence: its unchanged blank context lines contain the single-space patch marker, which Git otherwise flags as trailing whitespace when storing a patch as text. The evidence file is retained byte-for-byte as generated.
- Read all changed backend contract/setup/migration paths and security-relevant client/program differences. Findings are static-source evidence; no DB or live chain inspection occurred.
- Only `docs/t07/` deliverables are committed; scratch venv/temp directories are under ignored `target/`. No runtime config, README, public token copy, screenshots or application code changed.
- No merge, push, deployment, service start, network query, seed/migration execution, signing, key reads or contact with anyone. Existing keys and `.env` were left untouched. No other repo was modified.

Next verification requires a prepared offline dependency environment, then actual backend and host results; matching SBF/LiteSVM and client/PostgreSQL checks remain later acceptance work. This audit is reviewable, but it does not satisfy T07's full “checks pass” acceptance criterion.
