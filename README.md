# Capture

**Ground truth, from the ground up.**

Capture is an open-upload data-labeling network for **ground-level egocentric
capture** — a photo or short video shot six to twelve inches off the ground,
angled forward or up. Anyone with a phone can prove they are human, capture
physical-world media, and label it against a structured taxonomy in exchange
for devnet **TEST-USDC**, backed by a slashable **TEST-SKR** quality bond. It
is built for the CLOCK IN hackathon (Solana Mobile × RadiantsDAO, September 8
– October 8 2026).

## How it works

1. **Prove human (liveness gate).** Before a first upload, the backend issues
   a fresh, single-use motion challenge (blink, turn left, turn right, smile).
   The check runs on-device; no biometric material leaves the phone. This is a
   liveness gate, not bank-grade anti-spoofing.
2. **Capture.** The worker records ground-level egocentric capture — the
   camera held 6–12 inches off the ground, angled forward or up — as a photo
   (an object or place) or a short video (an action).
3. **Label.** The worker applies the six label dimensions described below.
4. **Judge.** A vision-language-model quality judge accepts or rejects each
   submission (gpt-6-astra via the Codex CLI, behind `backend/seeker/judge.py`).
5. **Record.** An accepted submission accrues a TEST-USDC payout (base rate ×
   level multiplier × label premium) off-chain and advances the worker's level;
   a media-policy violation triggers the two-strike bond ladder — first strike
   `warn` (bond intact), second strike `slash` (full bond drained on-chain to a
   penalty vault). Payouts settle on-chain in a batched transfer.

## Label dimensions

Six dimensions, drawn from a server-owned closed vocabulary (`GET /taxonomy`):

| Dimension   | Required | What it captures |
|-------------|----------|------------------|
| OBJECT      | yes      | bounding box(es) around the object |
| PLACE       | yes      | a single scene class |
| ACTION      | yes      | a video trim plus one tag |
| POSTURE     | yes      | the subject's pose (required in v2) |
| EXPRESSION  | no       | facial expression |
| ENVIRONMENT | no       | indoor/outdoor, time, weather, surface, light |

Four optional metadata tags round out a capture: **surface type**, **lighting**,
**weather**, and **ego-motion** (a static action shot is rejected outright — an
image would do).

## Progression

Five levels, gated by both a cumulative accepted-count and a rolling
acceptance rate over the last 50 judged submissions:

```
Scout → Regular → Veteran → Expert → Pathfinder
```

Every contributor is at least a Scout. The TEST-SKR bond requirement scales
down with level and is waived at Pathfinder.

## Tokens & settlement

- **TEST-USDC** — payroll. A devnet test token, never real USDC.
- **TEST-SKR** — the slashable quality bond, escrowed on-chain in a real
  staking contract. A devnet fixture mint.

Settlement is **real on-chain transfer**: the SKR bond escrows on-chain at
deposit, and accepted payouts transfer TEST-USDC from the treasury in a batched
settle (`POST /bond/settle`). A media-policy violation warns, and a second
violation slashes the entire bond to a penalty vault.

## The judge

The quality judge is a vision-language model behind a clean abstraction
(`backend/seeker/judge.py`), driven by `gpt-6-astra` via the Codex CLI. It is
bounded by a per-wallet daily cap and fails closed (503) when it cannot be
reached — an accepted upload must never settle silently.

## Status

October 12 2026:

- Deployed to **Solana devnet**; backend live at `https://capture.magnumopus.ai`.
- **119 backend tests** and **114 Android tests** pass.
- Everything here runs on **devnet test tokens**.

Not done / honest caveats:

- Liveness is an on-device motion challenge, not bank-grade anti-spoofing
  (device attestation is a roadmap item).
- Moderation (Sightengine nudity + face-age + genai) is fail-closed in code,
  not validated as a compliance claim.

## Repository layout

```
.
├── android/            Solana Seeker Mobile app (Kotlin / Gradle)
│   └── app/            capture, label, judge UI; unit tests under src/test
├── backend/            FastAPI service
│   ├── seeker/         Capture v2 API, taxonomy, judge, leveling, chain, DB
│   ├── migrations/     database migrations
│   └── tests/          backend test suite
├── programs/           Anchor workspaces
│   └── seeker-bounty/  on-chain settlement + SKR bond program
├── scripts/            devnet bootstrap, deploy, and demo helpers
└── .github/            CI workflows
```

## Quick start

Four commands from a fresh clone to a running backend (devnet, throwaway
dev-only keys — never the real operator/media/verifier secrets):

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

Expected output from `/health`:

```json
{"service":"seeker","network":"devnet","production_ready":false}
```

Notes:

- The backend listens on **port 8000**. The Android Capture v2 client defaults
  to `SEEKER_API_BASE=http://10.0.2.2:8001` (see `android/app/build.gradle.kts`),
  and the emulator reaches your machine via `10.0.2.2`, not `localhost`. To
  connect the app, either run the backend with `--port 8001`, or rebuild the
  app with `-PseekerApiBase=http://10.0.2.2:8000`.
- `dev_bootstrap.sh` generates a throwaway operator key, a throwaway media
  encryption key, and a freshly generated dev-only verifier keypair
  (`backend/verifier.dev.json`) and writes them to `backend/.env`. These are
  intentionally **not** the real verifier — the real key authorizes every
  attestation and is never committed. Anything that needs the real verifier
  on-chain will fail until you point `SEEKER_VERIFIER_KEY_FILE` at your own
  keypair.
- No Docker? Use SQLite instead — uncomment the
  `SEEKER_DATABASE_URL=sqlite:///./seeker.db` and `SEEKER_LOCAL_SQLITE=true`
  lines in `backend/.env` (or run
  `SEEKER_LOCAL_SQLITE=true SEEKER_DATABASE_URL=sqlite:///./seeker.db ./scripts/dev_bootstrap.sh`).
- The dependency set is tested on Python 3.11. If `python3` is a newer minor,
  pass `PYTHON=python3.11 ./scripts/dev_bootstrap.sh`.
- Media moderation (Sightengine/Hive) is unconfigured by default, so uploads
  reject — that is expected and safe. The API still starts and `/health` still
  responds.

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

Android (unit tests):

```bash
cd android && ./gradlew testDebugUnitTest
```

Gradle locates the SDK via `ANDROID_HOME` (or `android/local.properties`, which
is gitignored — never commit a machine path). To build an APK for the emulator:

```bash
cd android && ./gradlew assembleDebug
```

Remember the port note above: the app's Capture v2 client points at
`10.0.2.2:8001` by default while the backend serves on `8000`.
