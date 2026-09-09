# Week 1 spike — MWA claim path

**Goal:** prove a contributor can claim SKR to their own wallet with a
transaction they are cryptographically required to sign, on real hardware,
before any feature work depends on it.

This is scheduled first because it is the only part of Tap Farm that cannot be
worked around. If MWA does not behave on the Seeker, everything downstream
changes — and the time to discover that is day 2, not day 28.

## What the claim transaction actually does

One transaction, two required signers:

| Signer | Role | Signs where |
|---|---|---|
| Contributor | Fee payer | In the wallet, via MWA |
| Treasury | SPL token authority | Server-side, before sending to the app |

Instructions:

1. `create_idempotent_associated_token_account` — payer: **contributor**
2. `transfer_checked` — authority: **treasury**

Making the contributor the fee payer is the whole point. A treasury that simply
sent tokens to a contributor's address would need no signature from them, which
would make the wallet approval prompt decorative — a real transaction that does
nothing. Here the transfer cannot land without their signature.

`backend/tests/test_claim_tx.py` asserts this structurally: `tx.verify()`
**raises** before the wallet signs and **passes** after. If someone later
refactors the payout into a plain server-side transfer, those tests fail.

`transfer_checked` rather than `transfer` so the mint and decimals are validated
on-chain. `create_idempotent_...` so the first claim and the fiftieth take the
same code path.

## Running it

### 1. Devnet bootstrap (needs the Solana CLI)

```bash
./scripts/bootstrap_devnet.sh
```

Creates `backend/treasury.json`, mints 10,000 mock SKR, and prints the `.env`
lines to add. Idempotent. If the airdrop is rate-limited, fund the printed
address at <https://faucet.solana.com> and re-run.

> Uses the CLI rather than Python because solana-py 0.40 removed both its sync
> client and `spl.token.client`, so the Python route now means hand-rolling mint
> creation. The CLI writes keypairs in the JSON int-array format `solders`
> reads, so no conversion is needed.

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 16 tests, no network needed
uvicorn tapfarm.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` matters: the Seeker needs to reach your machine over the LAN.

### 3. App

```bash
cd android
./gradlew installDebug -PtapfarmApiBase=http://<your-LAN-IP>:8000
```

The Seeker cannot reach your laptop's `localhost`, so pass the LAN IP. The
default (`10.0.2.2`) is the emulator's host alias.

Then: **Connect wallet** → **Credit 6 test tasks** → **Claim to wallet**. A
devnet signature means the spike passed.

## Known unknowns

Two things are unverified, both flagged honestly rather than papered over.

**The Kotlin has not been compiled.** This repo's CI container is firewalled off
from `dl.google.com`, so the Android SDK cannot be installed and no build has
run. The backend is fully tested; the app is not. Dependency versions were
resolved against Maven Central (MWA `2.2.0` is current stable), but the MWA call
sites are written from the documented 2.x API and may need small adjustments
against the official sample at
<https://github.com/solana-mobile/mobile-wallet-adapter>. The three places most
likely to need a touch-up:

- `MobileWalletAdapter(connectionIdentity = ConnectionIdentity(...))` construction
- the `TransactionResult` subtype names in `SpikeViewModel`
- `signAndSendTransactions(...)` inside the `adapter.transact { }` scope

**AGP 8.7.3 / Kotlin 2.0.21** are a deliberately conservative pair, not the
newest. Android Studio will likely offer to upgrade AGP; accepting is fine.

## Deliberately not in the spike

Task serving, the labeling UI, gold-standard verification, SQLite persistence,
and the accuracy dashboard. `POST /spike/grant` credits tasks without solving
any, purely so the claim path can be exercised today. It is deleted in week 2.

One known rough edge: `/claim/prepare` zeroes the contributor's balance
optimistically, so a declined wallet approval loses the credit. Week 2 moves
this behind a claim record keyed on the transaction signature so an unsubmitted
claim can be reopened.
