# Tap Farm

A mobile-native data labeling network. Contributors label training data on their
phone and are paid to the wallet already built into it.

Built for [CLOCK IN](https://docs.solanamobile.com/hackathon/) — Solana Mobile ×
RadiantsDAO, September 8 – October 8 2026.

> **Status: week 2 of 4.** Task serving, the labeling UI, the contributor-signed
> claim, the two-token stake program and referral accounting are built, and
> everything on-chain is proven against a live validator. 198 tests pass. The
> on-device MWA handshake is the open item. See [docs/SPIKE.md](docs/SPIKE.md)
> for the full ledger of what is proven and what is not.

## Tokens

Two tokens, two jobs. The split is not cosmetic — it decides what we are allowed
to destroy.

**TAP** is ours: what contributors earn, and the **slashable** quality bond. Get
gold-standard tasks wrong often enough and part of your TAP bond is burned into
the campaign reward pool.

**SKR** is Solana Mobile's. We never mint it and we never burn it. It is a
**non-slashable** access stake: locking real SKR signals platform commitment and
unlocks referral earnings. `slash` has no asset parameter at all, so SKR being
untouchable is a property of the program's interface rather than of calling it
carefully — and `test_slashing_never_touches_the_skr_stake` tries a maximal
slash to prove it.

Because SKR does not exist on devnet, the bootstrap script creates a plain local
mint to occupy the access-stake slot in tests. It is a test fixture, is never
shown to a user as SKR, and on mainnet that slot holds the canonical SKR mint —
the program cannot tell the difference, which is the point.

### The numbers

| | Default | Why |
|---|---|---|
| Reward per task | 0.01 TAP | 100 tasks to a whole token — visible movement, not dust |
| Minimum TAP bond | 0.1 TAP (~10 tasks) | Demo-tuned. In production a bond must exceed what a burst of bad labeling extracts before the accuracy window catches it |
| Minimum SKR stake | 1 SKR | A commitment signal, not collateral — only has to be inconvenient to fake at scale |
| Unstake cooldown | 24h | Long enough to score a bad actor before they exit, short enough not to feel punitive |
| Platform fee | 20% of task value | Our margin |
| Referral share | 10% of that fee (2% of task value) | **Paid from our margin, never from the referee** |

That last row is the whole difference between a referral bonus and a pyramid, so
`Settings.referral_reward` caps the payout at the platform fee structurally
rather than trusting configuration discipline.

## Referrals

A referrer earns a share of **the platform's margin** on work their referees
complete. The referee's earnings are never touched — a referred contributor is
never worse off for having been referred.

"Earn a percentage of the people you recruit" describes both a normal referral
programme and a pyramid; which one it is depends on whose money it comes from.
Four rules keep this one on the right side:

- **Depth one.** Only the direct referrer is paid. Chains earn nothing past the
  first hop, so there is no downline — and a downline is what makes a pyramid.
- **No self-referral, no mutual referral.** A wallet cannot refer itself, and
  two wallets cannot refer each other and skim the fee twice for the same work.
- **Both stakes required.** A referrer needs a slashable TAP bond and the SKR
  access stake, so they have something at risk if the people they bring in
  produce garbage.
- **No pure recruiters.** Referral earnings are gated behind the same accuracy
  check as everything else, so a wallet that has never passed probation cannot
  withdraw them. You have to be a working contributor to collect for bringing
  others in.

On sybils: nothing stops one person opening two wallets, and that is not
detectable from an address. The defence is economic. A referral only pays when
the referee *earns*, and earning requires passing gold-standard accuracy — so a
fake referee that does not label correctly produces nothing to take a share of.
To farm referrals you have to do real verified work, at which point you are a
contributor and the 2% is an ordinary acquisition cost.

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

![Sample tap-grid tasks](docs/img/sample_tasks.png)

Sample tasks with ground truth ringed in green. Distractors always include a
near-miss sharing the target's shape and one sharing its colour, so checking a
single attribute gets the answer wrong. Objects never straddle a cell border:
ambiguous tasks would poison gold-standard scoring and punish honest
contributors.

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

Rewards are denominated in TAP, created by `scripts/bootstrap_devnet.sh`. TAP is
ours on every cluster, so the devnet mint is the real token rather than a
stand-in for someone else's.

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
backend/
  tapfarm/generator/     Synthetic scene generation, dataset + YOLO labels
  tapfarm/scoring.py     Gold-standard grading, claim eligibility
  tapfarm/claim_tx.py    Two-signer claim transaction
  tapfarm/stake_client.py Instruction builders for the stake program
  tapfarm/referrals.py   Referral graph, accrual and balances
  tapfarm/stake_reader.py Cached on-chain stake lookups for eligibility
programs/
  tapfarm-stake/         Anchor program: TAP bond, SKR access stake, slashing
scripts/    Devnet bootstrap and program deploy
docs/       Spike notes, platform roadmap
```

Build the dataset:

```bash
cd backend
python -m tapfarm.generator.dataset --out data/tapgrid --count 10000
```

One generator serves both campaigns and the accuracy-curve model: tap-grid
answers for `img-grid-v1`, and YOLO-format boxes for `robotics-bbox-v1` and
model training. Because scenes are built from known ground truth, the
annotations are exact and cost nothing.

Transaction construction lives in the backend rather than the app on purpose:
it can be unit tested there instead of only being verifiable on a phone. The
app decodes base64 and hands bytes to the wallet.

## Anti-gaming

Labeling networks are only worth what their data quality is worth, so the
question "what stops someone scripting ten thousand submissions" has to have an
answer in the product, not the pitch.

**Gold-standard tasks.** The synthetic generator produces ground truth for
free, so tasks with known answers are seeded into every contributor's stream at
an undisclosed rate. Rolling accuracy against those gates claiming, and you
cannot tell which task was the check.

Three rules do the work, each specified by a test in
`backend/tests/test_scoring.py`:

- **Exact-set grading.** No partial credit, because partial credit rewards
  tapping every cell — recall goes to 1.0 for free. With 9 cells there are 512
  possible subsets, so guessing is not a strategy.
- **Probation before payout.** Rolling accuracy alone lets a fresh wallet claim
  after one lucky answer, which makes sybils cheap. Ten verification tasks are
  required before any claim, and unverified tasks do not count toward it.
- **A bounded accuracy window.** Only recent results count, so a contributor
  who was accurate and then starts scripting loses eligibility rather than
  coasting on history.

**The TAP bond.** Detection alone is a treadmill — a scripter whose accuracy
collapses just funds a new wallet. Staking TAP puts something at risk: the
rolling accuracy above is the slashing oracle, and falling below threshold burns
part of the bond into the campaign reward pool, so honest labelers are paid out
of dishonest ones. See **Tokens** above for why the bond is TAP and why SKR is
never slashed.

## Development

```bash
cd backend && pip install -r requirements.txt
python -m tapfarm.generator.dataset --out data/tapgrid --count 10000
pytest -q                                                    # 165, offline
cargo test -p tapfarm-stake --lib                            # 21, program logic
uvicorn tapfarm.main:app --host 0.0.0.0 --port 8000

cd android && ./gradlew installDebug -PtapfarmApiBase=http://<LAN-IP>:8000
```

`--host 0.0.0.0` matters: the phone reaches the backend over the LAN, not
localhost.

The on-chain tests (177 with a validator) need one running:

```bash
solana-test-validator --reset --quiet &
CLUSTER=localhost ./scripts/bootstrap_devnet.sh
./scripts/deploy_stake_program.sh
```

Toolchain floors worth knowing before you build: **compileSdk 37 and AGP 9**,
because mobile-wallet-adapter 2.2.0 requires API 37+ and androidx.core 1.19
requires AGP 9.1+. Verified against AGP 9.4.0 / Kotlin 2.4.20 / Gradle 9.7.1.

Full setup, the on-chain test, and the toolchain gotchas that cost build cycles:
[docs/SPIKE.md](docs/SPIKE.md).
