# Tap Farm

A mobile-native data labeling network. Contributors label training data on their
phone and are paid to the wallet already built into it.

Built for [CLOCK IN](https://docs.solanamobile.com/hackathon/) — Solana Mobile ×
RadiantsDAO, September 8 – October 8 2026.

> **Status: week 1 of 4.** The claim path spike is built and the backend is
> tested; the labeling UI is not written yet. See [docs/SPIKE.md](docs/SPIKE.md)
> for exactly what works today and what does not.

## The idea

Data labeling is a real job that pays real money, and almost all of it runs
through web portals that settle in gift cards, PayPal, or nothing. Meanwhile the
Seeker ships with a hardware-backed wallet in every unit.

So: put the work on the phone, and pay to the wallet that is already there.

## Campaigns

Tap Farm is organized around **campaigns** — a labeling brief, a task type, a
dataset, and a reward rate. This is the core architectural decision, not a
roadmap item: the app renders whatever task type a campaign declares, so adding
a new kind of labeling work is a campaign definition rather than a new app.

| Campaign | Task type | Status |
|---|---|---|
| Image grid labeling | `tap_grid` | live |
| Robotics grasp annotation | `bounding_box` | queued |

Tap-grid ships first because it is fast to build and fast to demo. Bounding
boxes are the second campaign and map directly onto YOLO-format training data.

## How the payout works

Contributors accrue a balance as their labels are accepted, then claim it in one
transaction that **they** must sign:

```
  ┌─ create_idempotent_associated_token_account ── payer: contributor
  │
  └─ transfer_checked ───────────────────────────── authority: treasury

     fee payer: contributor   →   signs in the wallet via MWA
     token authority: treasury →  partial-signed server-side
```

The contributor is the fee payer, which makes them a required signer. This is
deliberate: a treasury that simply sent tokens to their address would need no
signature from them at all, and the wallet approval prompt would be decorative.
Here the transfer cannot land without it, and the tests assert that — the
transaction fails verification until the wallet signs.

Rewards are denominated in SKR. On devnet that is a mock mint created by
`scripts/bootstrap_devnet.sh`; on mainnet it is the canonical mint, reached
through the same code path and one config constant.

## Solana Mobile integration

- **Mobile Wallet Adapter** for authorization and for `signAndSendTransactions`.
  On a Seeker the wallet is backed by Seed Vault, so the signing keys stay in
  the secure element.
- **Any MWA-compatible wallet** works — Seeker is the target device, not a
  requirement.

A note on precision, because it is easy to get wrong: this app does not
integrate Seed Vault directly, and no dApp does. Seed Vault is key custody used
by *wallet* applications (`com.solanamobile:seedvault-wallet-sdk`). A dApp talks
to a wallet over MWA, and on a Seeker that wallet happens to be Seed
Vault-backed.

## Repo layout

```
android/    Kotlin + Jetpack Compose app, MWA integration
backend/    FastAPI + solders: campaigns, claim transaction construction
scripts/    Devnet bootstrap (treasury keypair, mock SKR mint)
docs/       Spike notes, platform roadmap
```

Transaction construction lives in the backend rather than the app on purpose:
it can be unit tested there instead of only being verifiable on a phone. The
app decodes base64 and hands bytes to the wallet.

## Anti-gaming

Labeling networks are only worth what their data quality is worth, so the
question "what stops someone scripting ten thousand submissions" has to have an
answer in the product, not the pitch.

**Gold-standard tasks:** the synthetic generator produces ground truth for free,
so tasks with known answers are seeded into every contributor's stream at an
undisclosed rate. Rolling accuracy against those gates claiming. Get them wrong
and you earn nothing, and you cannot tell which task was the check.

## Development

```bash
cd backend && pip install -r requirements.txt && pytest -q
cd android && ./gradlew installDebug -PtapfarmApiBase=http://<LAN-IP>:8000
```

Full setup, including devnet bootstrap: [docs/SPIKE.md](docs/SPIKE.md).
