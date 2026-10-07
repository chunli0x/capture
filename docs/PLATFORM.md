# Platform roadmap

What Union becomes after CLOCK IN. Deliberately out of hackathon scope — kept
here so the submission can be honest about the line between built and planned.

## Built for the hackathon

- Ghost-overlay campaign (`ghost_pose`): image-plane pose labeling with a
  synthetic golden set, a blind qualification gate, practice-only snap glow,
  and hidden golden items for drift detection

- Android app, MWA wallet connect, campaign-driven task rendering
- Tap-grid labeling campaign over a synthetic dataset
- Contributor-signed SKR claim on devnet
- On-chain two-token stake program (Anchor): slashable HUMAN bond, non-slashable
  SKR access stake, per-mint vaults, cooldown and slashing
- Gold-standard accuracy gating, wired as the slashing oracle
- Referral accounting funded from platform margin, depth one, gated on both
  stakes and on the referrer's own accuracy record
- Model accuracy curve trained on contributor labels

## Not built, and why

**Buyer marketplace.** No buyers exist in a four-week window, and a marketplace
with no demand side is a mock with extra screens. Campaigns are currently seeded
by us; the campaign abstraction is what a buyer-facing API would write into.

**On-chain reward escrow.** The claim is a two-signer transaction against a
treasury, not a per-contributor PDA vault. A minimal Anchor program with
per-contributor vaults would make accrual trust-minimized rather than
custodial — the natural next step, and the reason the payout path was built
around a real signed transaction instead of a server-side transfer.

**Bittensor subnet.** The original concept had contributors' labels feeding a
miner/validator training competition. It is a genuinely different project and
does not fit in the same month as a mobile app.

**iOS.** MWA is Android-native and Seeker is Android.

## Decided, not yet built

Most of these came out of a seven-role code review. None blocks the demo; all of
them would have to exist before the system held anything of value. They are
listed rather than quietly implied to work, because the gap between
"implemented" and "wired up" is exactly where a reader would otherwise be
misled.

**One real mainnet SKR stake in the demo.** Everything else runs on devnet with
HUMAN and a USDC stand-in; a single genuine mainnet SKR stake transaction shows
the SKR integration is real rather than simulated.

**Caller authentication.** Every endpoint takes a contributor pubkey as a plain
string and trusts it. Anyone can name someone else's wallet: drain a victim's
balance into a claim transaction only that victim can actually submit (griefing
rather than theft, but still destructive), or front-run a referral registration.
The fix is a signed nonce or challenge per request, proving the caller holds the
key they are claiming to be. Nothing here should hold real value until it
exists.

**`initialize()` access control.** The stake program's initializer has no admin
constraint, so on a fresh deployment whoever calls it first becomes the slash
authority and sets both mints. Either bake the admin pubkey into the program or
bundle initialization into the deploy transaction.

**The slashing loop.** `slash` is implemented, tested on-chain, and reachable
only by the configured authority - and **no running code calls it**. Rolling
gold-standard accuracy is computed on every submission but never triggers a
burn, and there is no instruction to pay `slashed_pool` back out to honest
contributors. Two pieces are missing: a backend trigger, and a
rewards-distribution instruction. Until both land, slashed HUMAN would simply
sit in the vault.

**Tier wiring.** `GOLD_RATE_BY_TIER` says a bonded contributor is verified at 5%
instead of 20%, and the stake program can report the tier - but `next_task` is
always called with tier 0, so the reduced rate never fires. The fix mirrors what
referral eligibility already does: read the position through `stake_reader`.

**Config updates and authority rotation.** `Config` is write-once. There is no
instruction to rotate the slash authority or change `min_human_stake`,
`min_skr_stake` or the cooldown, so a compromised authority key cannot be
replaced without redeploying to a new program id.

**Persistence.** Task balances, accuracy history, qualification state and the
referral graph are all in memory. A restart wipes them - which also resets the
anti-sybil record, making probation re-runnable at will. SQLite behind the
existing interfaces is the next step; the interfaces were written to survive it.

**Concurrency beyond the claim path.** The claim read-and-debit is now atomic
under a per-contributor lock, but the task and referral stores are otherwise
unguarded and several routes run in the threadpool. Concurrent submissions can
still lose an update. The same per-contributor lock should extend to them.

**A flag path for a real blind set.** Flagging is refused during qualification,
because the blind set is fixed-size and skipping would let someone reroll until
it was easy. That is safe only because the golden set is synthetic and always
contains its object. A blind set drawn from real buyer imagery would need a flag
that pulls a replacement from a reserve pool.

**Release signing and cleartext.** The release build is debug-signed and the
manifest allows cleartext traffic for the local dev backend. Both are fine for a
devnet demo and both must change before any public build.

**Backend hosting.** There is no Dockerfile or deployment target. The demo runs
the API locally over the LAN via `./scripts/run_demo.sh` (documented in the
README's "Seeing it run"); anything judges install needs a real host. Decision
for this submission: ship the one-command local path, not a hosted API.

## Ghost overlay, v2

**True 3D pose.** v1 records a 2D similarity transform - x, y, roll, apparent
scale. Pitch, yaw and physical depth need a mesh renderer (SceneView or
Filament) plus camera intrinsics, and a flat sprite cannot express them. Until
that exists, calling it 6D would be an overclaim.

**A physical scale.** Today scale is unitless and unscored. Given the object's
physical width and the camera's focal length it becomes real depth
(`z = f * physical_size / apparent_px`), at which point it can earn its own
error metric and enter the gate.

**Normalised error.** Pixels are resolution- and distance-dependent, so 15px
means different things in different frames. Production wants error normalised
by object size, plus a pixel-to-mm calibration path.

**Symmetry-aware roll.** Every current object has a visible roll feature. A
rotationally symmetric object needs a symmetry-aware metric or a roll-free task
type.

**Threshold validation.** 15px / 10 degrees / 90% is a guess. Run fresh users
through the golden set and expect to land nearer 25px / 15 degrees / 80-85%.

## Next, roughly in order

1. Per-contributor PDA reward vaults (Anchor)
2. Bounding-box campaign — robotics grasp annotation
4. Cross-contributor agreement scoring alongside gold-standard checks
5. dApp Store publishing
6. Buyer-facing campaign creation API
