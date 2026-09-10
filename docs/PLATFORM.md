# Platform roadmap

What Tap becomes after CLOCK IN. Deliberately out of hackathon scope — kept
here so the submission can be honest about the line between built and planned.

## Built for the hackathon

- Ghost-overlay campaign (`ghost_pose`): image-plane pose labeling with a
  synthetic golden set, a blind qualification gate, practice-only snap glow,
  and hidden golden items for drift detection

- Android app, MWA wallet connect, campaign-driven task rendering
- Tap-grid labeling campaign over a synthetic dataset
- Contributor-signed SKR claim on devnet
- On-chain two-token stake program (Anchor): slashable TAP bond, non-slashable
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

**One real mainnet SKR stake in the demo.** Everything else runs on devnet with
TAP; a single genuine mainnet SKR stake transaction shows the SKR integration is
real rather than simulated.

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
