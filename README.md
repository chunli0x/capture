# Capture

**Decentralized RLHF — humans judge vision-model outputs, consensus decides who gets paid.**

Capture is a mobile RLHF preference-judging network. A judge sees
two vision-model outputs and picks the better one (A/B preference) or rates a
single output 1–5. Aggregated preferences become an RLHF preference dataset,
with trust priced into every judgment through a slashable **test-USDC** stake.

## The judgment product

Humans judge a vision model's outputs for RLHF. The incentive is
**consensus-gated pay in test USDC**: every pair goes to K=3 judges; the
majority pick (or the crowd median for ratings) wins, aligned judges are paid
(`base_usdc × level multiplier`), dissenters earn nothing, and **"can't tell" is
a first-class answer** that re-routes the pair instead of forcing a guess.

The full loop:

1. **Stake.** The judge deposits a test-USDC bond on-chain. The bond is the
   slashable trust layer.
2. **Judge.** The judge answers A/B or 1–5 pairs. One judge cannot answer the
   same pair twice.
3. **Resolve.** K substantive votes resolve the pair. Neutral votes ("can't
   tell"/"tie") never count as dissent and never inflate the quorum. A genuine
   split adds one tiebreaker judge.
4. **Pay or slash.** Aligned judges earn test-USDC (journaled before broadcast,
   idempotent per judgment). A judge whose rolling agreement rate stays below a
   floor runs the two-strike warn/slash ladder on-chain (full bond forfeit on
   the second strike).
5. **Anchor.** Each fully-resolved batch records a Merkle root and commits it
   on-chain via `post_batch` as dataset provenance (append-only per batch; a
   failed final anchor is retried idempotently).

A judge-accuracy ladder (agreement-rate driven) raises the rate multiplier from
1.00 up to 2.00 across five levels.

Honest notes (state, do not hide):

- **Test tokens.** Pay and bond are both **devnet/test USDC** (one token, three
  jobs). Not real value. The UI and `/health` both say so.
- **Majority-preference bias.** RLHF on majority preference flattens minority and
  edge preferences. This is fine for a first pass, but the dataset does **not**
  represent all humans. Do not claim it does.
- K, thresholds, and rates are starting hypotheses — tune against real agreement
  data, not once.
- **Seed data.** The demo is seeded with 100 judgment pairs whose output URLs
  are placeholders (real vision-model outputs are loaded by the training
  pipeline, out of scope for the hackathon). This proves the judging
  infrastructure, not a production dataset.

## Payout economics

A judge's **base rate is $0.02 per aligned judgment**, times their level
multiplier. Dissenters earn $0. "Can't tell" earns a flat **$0.005** and
re-routes the pair. Payout is in **test USDC on devnet** (USDC is 1:1 USD).

| Level | Agreement | Rate | ~Earns at 240/hr |
|---|---|---|---|
| Scout | no gate | ×1.00 | — |
| Regular | ≥80% | ×1.10 | — |
| Veteran | ≥88% | ×1.25 | $5.28/hr |
| Expert | ≥93% | ×1.50 | $6.70/hr |
| Pathfinder | ≥97% | ×2.00 | $9.31/hr |

The gradient rewards accuracy, not speed: a Pathfinder earns ~2× a Scout because
~97% of their judgments enter the dataset.

Cost per useful label is flat regardless of judge quality, because dissenters
are free:

- 95% agreement → pay $1.90 per 100 judged → 95 useful labels → $0.020/label.
- 60% agreement → pay $1.20 per 100 judged → 60 useful labels → $0.020/label.

The operator always pays ~$0.02 per label that enters the dataset. A bad judge
earns less and gets slashed; they were never overpaying.

Whole-dataset cost (10,000 pairs at K=3): **~$540** total payout, versus ~$9,000
for enterprise RLHF (~$0.30/judgment) or ~125 hours of manual labeling. $540 and
zero operator time replaces $9k or 125 hours.

The flywheel: judge → earn USDC → stake more USDC → unlock higher tiers → earn
faster. The token accrues to people who are good at judging, and they reinvest
it to earn more.

## Token & settlement

- **test-USDC** — one token, three jobs: the **payout** (consensus-aligned
  judgments earn USDC), the **bond** (deposit to unlock paid judging), and the
  **slash** collateral (lose stake for systematic disagreement). A devnet
  fixture mint we control.

Settlement is **real on-chain**: the USDC bond escrows on-chain at deposit,
aligned judges are paid test-USDC on agreement (minted by the treasury), and a
systematic disagreement warns then slashes the USDC bond to a penalty vault.

## Status

October 13 2026:

- Deployed to **Solana devnet**; backend live at `https://capture.magnumopus.ai`.
- **46 backend tests** pass; the Anchor program's **6 unit tests** pass and the
  BPF build is clean.
- **USDC everywhere** — payout, bond, and slash are a single test-USDC token.
  The single-mint program is live on devnet (program
  `5TiDwP86k95yfQWzExrPTj5qcKxED99z8pW9fN81u5SV`, upgradeable).
- Seeded with **100 judgment pairs** (60 A/B preference + 40 rating) for the demo.
- Everything here runs on **devnet test tokens**.

Not done / honest caveats:

- Liveness is an on-device motion challenge, not bank-grade anti-spoofing
  (device attestation is a roadmap item). It is present but is not yet a hard
  gate in the judging path.
- Sybil resistance is partial: the bond raises the cost of fake accounts but
  does not eliminate them.
- **Video / frame-sequence judging** is the next tier (motion and sequence
  perception) and is planned but not yet live — the demo judges still images.

## Install the app

The Android judgment client is downloadable at
`https://capture.magnumopus.ai/capture.apk` — a devnet build, test tokens only.

## Repository layout

```
.
├── android/            Android app (Kotlin / Gradle)
├── backend/            FastAPI service
│   ├── seeker/         judgment API, consensus, bond, chain, DB
│   ├── migrations/     database migrations
│   └── tests/          backend test suite
├── programs/           Anchor workspaces
│   └── seeker-bounty/  on-chain USDC bond + warn/slash + batch-anchor program
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
