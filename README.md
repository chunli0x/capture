# Capture

**Decentralized RLHF — humans judge vision-model outputs, consensus decides who gets paid.**

Capture is a mobile RLHF preference-judging network for the CLOCK IN hackathon
(Solana Mobile × RadiantsDAO), built for **Solana Seeker Mobile**. A judge sees
two vision-model outputs and picks the better one (A/B preference) or rates a
single output 1–5. Aggregated preferences become an RLHF preference dataset,
with trust priced into every judgment through a slashable **test-SKR** stake.

## The judgment product

Humans judge a vision model's outputs for RLHF. The incentive is
**consensus-gated pay in test $SKR**: every pair goes to K=3 judges; the
majority pick (or the crowd median for ratings) wins, aligned judges are paid
(`base_skr × level multiplier`), dissenters earn nothing, and **"can't tell" is
a first-class answer** that re-routes the pair instead of forcing a guess.

The full loop:

1. **Calibrate.** A new judge passes a 10-pair calibration gate against
   known-consensus pairs before they can stake. Correctness is only revealed at
   the pass/fail boundary, never per-answer mid-gate.
2. **Stake.** The judge deposits a test-SKR bond on-chain. The bond is the
   slashable trust layer.
3. **Judge.** The judge answers A/B or 1–5 pairs. One judge cannot answer the
   same pair twice.
4. **Resolve.** K substantive votes resolve the pair. Neutral votes ("can't
   tell"/"tie") never count as dissent and never inflate the quorum. A genuine
   split adds one tiebreaker judge.
5. **Pay or slash.** Aligned judges earn test-SKR (journaled before broadcast,
   idempotent per judgment). A judge whose rolling agreement rate stays below a
   floor runs the two-strike warn/slash ladder on-chain (full bond forfeit on
   the second strike).
6. **Anchor.** Each fully-resolved batch records a Merkle root as dataset
   provenance (on-chain anchoring is a next deploy).

A judge-accuracy ladder (agreement-rate driven) raises the rate multiplier from
1.00 up to 2.00 across five levels.

Honest notes (state, do not hide):

- **Test tokens.** $SKR here is **devnet/test $SKR** for the hackathon. It is not
  real value. The UI and `/health` both say so.
- **Majority-preference bias.** RLHF on majority preference flattens minority and
  edge preferences. This is fine for a first pass, but the dataset does **not**
  represent all humans. Do not claim it does.
- K, thresholds, and rates are starting hypotheses — tune against real agreement
  data, not once.

## Tokens & settlement

- **test-SKR** — one token, three jobs: **stake** (deposit to unlock paid
  judging), **reward** (consensus-aligned judgments earn SKR), **slash** (lose
  stake for systematic disagreement). A devnet fixture mint we control.

The production SKR token is a separate mainnet mint
(`SKRbvo6Gf7GondiT3BbTfuRDPqLWei4j2Qy2NPGZhW3`), not used in the devnet demo. The
demo mints test-SKR because we hold its mint authority; the mainnet token's mint
authority is not ours, so it is swapped in post-hackathon, not before.

Settlement is **real on-chain transfer**: the SKR bond escrows on-chain at
deposit, aligned judges are paid test-SKR on agreement, and a systematic
disagreement warns then slashes the bond to a penalty vault.

## Status

October 12 2026:

- Deployed to **Solana devnet**; backend live at `https://capture.magnumopus.ai`.
- **46 backend tests** pass; the Anchor program's **6 unit tests** pass and the
  BPF build is clean.
- The SKR bond is a real on-chain staking contract with full slash, live on
  devnet (program `5TiDwP86k95yfQWzExrPTj5qcKxED99z8pW9fN81u5SV`, upgradeable).
- Everything here runs on **devnet test tokens**.

Not done / honest caveats:

- Liveness is an on-device motion challenge, not bank-grade anti-spoofing
  (device attestation is a roadmap item). It is present but is not yet a hard
  gate in the judging path.
- Sybil resistance is partial: the bond raises the cost of fake accounts but
  does not eliminate them.

## Repository layout

```
.
├── android/            Solana Seeker Mobile app (Kotlin / Gradle)
├── backend/            FastAPI service
│   ├── seeker/         judgment API, consensus, calibration, bond, chain, DB
│   ├── migrations/     database migrations
│   └── tests/          backend test suite
├── programs/           Anchor workspaces
│   └── seeker-bounty/  on-chain SKR bond + warn/slash + batch-anchor program
├── scripts/            devnet bootstrap and demo helpers
├── docs/               API contract
└── .github/            CI workflows
```

## Quick start

Four commands from a fresh clone to a running backend (devnet, throwaway
dev-only keys — never the real verifier secret):

```bash
git clone https://github.com/chunli0x/capture.git && cd capture

# 1. PostgreSQL (Docker) — loopback-only by default
docker compose up -d

# 2. venv + dependencies + dev-only keys + DB schema; writes backend/.env
./scripts/dev_bootstrap.sh

# 3. run the API (loads the generated backend/.env)
cd backend && .venv/bin/uvicorn seeker.api:production_app --factory --env-file .env

# 4. verify
curl -s http://localhost:8000/health
```

Notes:

- The backend listens on **port 8000**.
- `dev_bootstrap.sh` generates a freshly generated dev-only verifier keypair
  (`backend/verifier.dev.json`) and writes it to `backend/.env`. This is
  intentionally **not** the real verifier — the real key authorizes every
  warn/slash/anchor and is never committed. Anything that needs the real
  verifier on-chain will fail until you point `SEEKER_VERIFIER_KEY_FILE` at
  your own keypair.
- No Docker? Use SQLite instead — set `SEEKER_LOCAL_SQLITE=true` and
  `SEEKER_DATABASE_URL=sqlite:///./seeker.db`.
- The dependency set is tested on Python 3.11. If `python3` is a newer minor,
  pass `PYTHON=python3.11 ./scripts/dev_bootstrap.sh`.

## Build & run

Backend:

```bash
cd backend
.venv/bin/pip install -r requirements-seeker.txt
.venv/bin/python -m seeker.migrate
.venv/bin/uvicorn seeker.api:production_app --factory --env-file .env
```

(Or just run `./scripts/dev_bootstrap.sh`, which does all of the above and
writes `backend/.env`.)

Tests:

```bash
# backend
cd backend && .venv/bin/python -m pytest -q

# Anchor program (Rust unit tests + BPF build)
cargo test -p seeker-bounty --lib
anchor build
```
