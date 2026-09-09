# Platform roadmap

What Tap Farm becomes after CLOCK IN. Deliberately out of hackathon scope — kept
here so the submission can be honest about the line between built and planned.

## Built for the hackathon

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

## Next, roughly in order

1. Per-contributor PDA reward vaults (Anchor)
2. Bounding-box campaign — robotics grasp annotation
4. Cross-contributor agreement scoring alongside gold-standard checks
5. dApp Store publishing
6. Buyer-facing campaign creation API
