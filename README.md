# Capture

**Ground truth, from the ground up.**

Capture is a mobile data-labeling bounty network. Anyone with a phone can prove they are human, capture ground-level egocentric footage of the physical world — a photo or short video shot six to twelve inches off the ground, angled forward or up — and label it against a structured taxonomy in exchange for USDC. Requesters post bounties for labeled ground-truth media; two independent reviewers must agree on the label before anyone is paid, and settlement happens exactly once on-chain. It is built for the CLOCK IN hackathon (Solana Mobile × RadiantsDAO, September 8 – October 8 2026).

## How it works

The loop has five steps:

1. **Prove human.** A worker proves they are a human operator using a Solana Attestation Service credential, an on-device liveness check, and explicit operator enrollment. 
2. **Capture.** The worker records ground-level egocentric capture: the camera held 6–12 inches off the ground, angled forward or up, as a photo (an object or place) or a short video (an action).
3. **Label.** The worker applies the six label dimensions described below.
4. **Review.** Two independent reviewers label the same media blind. Agreement (object IoU ≥ 0.7) unlocks eligibility; disagreement is "disputed" and pays nobody.
5. **Settle.** The requester accepts, and the bounty settles exactly once on-chain. The worker is paid in USDC, backed by a slashable SKR bond.

## Label dimensions

Three primary dimensions:

- **OBJECT** — draw a bounding box around the object.
- **PLACE** — a single scene class.
- **ACTION** — a video trim plus one tag.

Three optional secondary tags:

- **FACIAL EXPRESSION**
- **BODY LANGUAGE**
- **ENVIRONMENT** — indoor/outdoor, time, weather, surface, light.

## Tokens

Two assets, two jobs. 

- **USDC** - all bounties are paid in USDC.
- **SKR** - a worker stakes SKR against the quality of their labels.


## Status

October 8 2026:

- Deployed to **Solana devnet**; backend live.
- **556 backend tests** and **98 Android tests** pass.
- Everything here runs on **devnet test tokens** 

What is **not** done:

- **Slashing is implemented but not enforced** — there is no backend trigger that burns a bond yet.
- **Moderation is a live-validated pilot, not a compliance claim.** CSAM and minor-face screening (Hive + Sightengine) is fail-closed in code, but it has not been validated as compliance.
- **On-device MWA signing is unverified on physical Solana Seeker Mobile hardware.** It passes in CI, but the hardware-backed wallet handshake is the one open item.

## Repository layout

```
.
├── android/            Solana Seeker Mobile app (Kotlin / Gradle)
│   └── app/            capture, label, review UI; unit tests under src/test
├── backend/            FastAPI service
│   ├── seeker/         API, taxonomy, media, chain, DB, migrations
│   ├── migrations/     database migrations
│   └── tests/          backend test suite
├── programs/           Anchor workspaces
│   └── seeker-bounty/  on-chain bounty settlement + SKR bond program
├── docs/               phase docs, runbook, verification notes
├── scripts/            devnet bootstrap, deploy, and demo helpers
└── .github/            CI workflows
```

## Build & run

Backend:

```bash
cd backend && pip install -r requirements-seeker.txt && python -m seeker.migrate && uvicorn seeker.api:production_app --factory
```

Android (unit tests):

```bash
ANDROID_HOME=/home/hermes/android-sdk ./gradlew testDebugUnitTest
```

## Docs

- [SEEKER-PHASE-1.md](docs/SEEKER-PHASE-1.md)
- [SEEKER-PHASE-2.md](docs/SEEKER-PHASE-2.md)
- [SEEKER-RUNBOOK.md](docs/SEEKER-RUNBOOK.md)
