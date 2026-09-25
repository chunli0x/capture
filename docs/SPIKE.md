# Week 1 spike — MWA claim path

**Goal:** prove a contributor can claim SKR to their own wallet with a
transaction they are cryptographically required to sign, on real hardware,
before any feature work depends on it.

This is scheduled first because it is the only part of Union that cannot be
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
pytest -q                       # 247 passed, 12 skipped; no network needed
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

## Verification status

**The claim path is proven on-chain.** `backend/tests/test_e2e_claim.py` submits
the real claim transaction to a validator and asserts SKR lands in the
contributor's token account. It is skipped by default so the suite stays
offline; run it with a local validator:

```bash
solana-test-validator --reset --quiet &
CLUSTER=localhost ./scripts/bootstrap_devnet.sh
cd backend && TAPFARM_E2E=1 TAPFARM_RPC_URL=http://localhost:8899 \
  TAPFARM_SKR_MINT=<mint from bootstrap> pytest -q
```

**The stake program is proven on-chain too.** `backend/tests/test_stake_program.py`
exercises stake, slash, cooldown and withdraw against the deployed program,
including that only the slash authority can slash and that a slash during
cooldown reduces the payout.

Totals: **21** Rust logic tests (`cargo test -p tapfarm-stake --lib`), and
**165 passed / 12 skipped** from a plain `pytest -q` — the skips being the
on-chain tests, which run and pass (**177 passed**) once a validator is up and
the program is deployed. Prefer the local validator over
devnet: no faucet rate limit, and devnet airdrops fail routinely from shared or
cloud IPs.

**The app compiles.** `./gradlew assembleDebug` produces a 13 MB
`ai.loosh.tapfarm` debug APK against compileSdk 37.

**Still unverified: the on-device MWA handshake.** Everything up to and
including transaction construction and submission is tested, but no wallet has
authorized this app yet. That is what the Seeker run is for, and it is the one
remaining unknown in the claim path.

## Toolchain notes

Several of these cost a build cycle to discover, so they are written down.

**compileSdk 37 and AGP 9 are not optional.** mobile-wallet-adapter 2.2.0
requires consumers to compile against API 37 or later, and androidx.core 1.19
requires AGP 9.1+. The versions that work: AGP 9.4.0, Kotlin 2.4.20, Gradle
9.7.1, compose-bom 2026.08.00.

**The SDK platform package is `platforms;android-37.0`,** not `android-37` -
Android platforms are minor-versioned now, so `sdkmanager --install
"platforms;android-37"` fails with "Failed to find package".

**AGP 9 breaks two things in any pre-9 build file.** The
`org.jetbrains.kotlin.android` plugin must be *removed* (AGP 9 has built-in
Kotlin support and fails the build if it is applied), and the `kotlinOptions`
block no longer exists - `jvmTarget` moves to a top-level `kotlin {
compilerOptions { } }` block.

**MWA 2.2.0 API details** that differ from what the older docs suggest:

- `ConnectionIdentity(identityUri, iconUri, identityName)` - the parameter is
  `iconUri`, not `iconRelativeUri`.
- `connect()` returns `TransactionResult<Unit>`, so the account does *not* come
  from the payload. `TransactionResult.Success` carries a separate `authResult`,
  and the public key is `authResult.accounts.first().publicKey` (a `ByteArray`).
- `TransactionResult.Failure` exposes both `message` and `e`.
- `signAndSendTransactions(arrayOf(txBytes))` returns a result whose
  `signatures` is `Array<ByteArray>`.

**solana-py 0.40 removed a lot.** No sync `Client`, no `spl.token.client`, and
`solana.rpc.types.TxOpts` is gone. `simulate_transaction` accepts only
`VersionedTransaction`, and `send_transaction` likewise - legacy transactions go
through `send_raw_transaction(bytes(tx))`.

**Set `commitment=Confirmed` on the RPC client.** `send_raw_transaction` runs
preflight at the client's commitment, and the default is *finalized*. On a fresh
validator a just-airdropped account is confirmed but not finalized, so preflight
simulates against a bank where it does not exist and fails with "Attempt to
debit an account but found no record of a prior credit" - which reads like a
funding bug and is not one. This cost the most time of anything here.


## Stake program notes

`programs/tapfarm-stake` is deployed and its lifecycle is tested against a live
runtime. Build and deploy with `./scripts/deploy_stake_program.sh`.

**The program keypair is not in the repo.** It controls both the program address
and its upgrade authority, so `programs/*/program-keypair.json` is gitignored.
To deploy from a fresh clone, generate one and point the code at it:

```bash
solana-keygen new --no-bip39-passphrase -o programs/tapfarm-stake/program-keypair.json
solana-keygen pubkey programs/tapfarm-stake/program-keypair.json
# then update declare_id!() in programs/tapfarm-stake/src/lib.rs
# and [programs.localnet] in Anchor.toml
```

**`--arch v3` is mandatory.** SIMD-0500 is active and disables deployment of
SBPF v0, v1 and v2, while `cargo-build-sbf` still defaults to v0. A v0 binary
fails to deploy with "Detected sbpf_version required by the executable which are
not enabled" followed by a generic "invalid account data for instruction" -
which does not point at the architecture at all.

**cargo does not rebuild when `--arch` changes.** Passing a different `--arch`
without removing `target/deploy/tapfarm_stake.so` silently redeploys the
previous binary, so the same error repeats while the flag looks correct. This
sent me chasing the wrong cause through four deploy attempts. Verify:

```bash
readelf -h target/deploy/tapfarm_stake.so | grep Flags   # want "CPU Version: 3"
```

**Failed deploys leave buffer accounts holding real SOL.** Reclaim with
`solana -C backend/.solana-cli.yml program close --buffers --bypass-warning`
before retrying, or the next attempt fails on insufficient funds and looks like
a different problem.

**Anchor 1.x changed `CpiContext`.** It takes the program id as a `Pubkey` now,
not an `AccountInfo` - so `CpiContext::new(ctx.accounts.token_program.key(), ..)`
rather than `.to_account_info()`. Note the crate is at 1.2.0; guides written
against the 0.29/0.31 line will not compile.

**Config is a singleton PDA** (seeds `[b"config"]`), so `initialize` can only
run once per deployment and the on-chain tests treat it as idempotent. If
`min_human_stake`, `min_skr_stake` or `cooldown_seconds` need to vary per test,
that is the constraint to change first.

**Vaults are per-mint** (seeds `[b"vault", mint]`), so HUMAN and SKR are held in
separate token accounts and `stake`/`withdraw` validate that the passed mint
matches the asset. `slash` takes no asset at all - the only slashable stake is
HUMAN.

## Deliberately not in the spike

Task serving, the labeling UI, gold-standard verification, SQLite persistence,
and the accuracy dashboard. `POST /spike/grant` credits tasks without solving
any, purely so the claim path can be exercised today. It is deleted in week 2.

One known rough edge: `/claim/prepare` zeroes the contributor's balance
optimistically, so a declined wallet approval loses the credit. Week 2 moves
this behind a claim record keyed on the transaction signature so an unsubmitted
claim can be reopened.
