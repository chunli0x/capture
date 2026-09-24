# Liveness: the day-one decision

The build spec says to reuse OpenPass if it exposes a usable liveness SDK for
Android/Seeker, and to fall back to an on-device check if it does not — and to
settle that on day one rather than day twenty. This is the answer and the
evidence behind it.

## Decision: on-device, with a motion challenge

**Ratified in the build spec (locked decision #1).** The liveness check runs
entirely on the device: Google ML Kit Face Detection plus a motion challenge
(blink, or turn the head), or an open-source on-device anti-spoofing model.
Paid SDKs (iProov, FaceTec, Banuba) are out - cost and integration weight for
no demo benefit. OpenPass is not blocked on; it has no public liveness SDK.

**The honest bar, stated in the spec and worth repeating wherever it is
claimed: "a live person performed a motion challenge". Not bank-grade
anti-spoofing.**

## What was searched, and what came back

Solana Mobile's own documentation index (`docs.solanamobile.com/llms.txt`)
lists the SDKs they ship: React Native, Web, Kotlin/Android, Flutter, Unity,
Unreal, and the Mobile CLI. The identity-adjacent surfaces documented are:

- **Seed Vault** — hardware key custody. Key management, not identity, and a
  dApp never touches it directly (it signs over MWA). This repo already says so.
- **Seeker Genesis Token** — an NFT marking a verified device owner. Device
  provenance, not a liveness check on a person.
- **Seeker Connect** — connecting to a certified device's own wallet.

There is no documented liveness, biometric, face, or proof-of-personhood SDK,
and no product under the name OpenPass in the Solana Mobile developer docs or
in general search. That is not proof it does not exist — an unreleased or
partner-gated SDK would look exactly like this — but it is enough to stop
planning around it.

The nearest real precedent went the other way: **Civic Pass** did offer liveness
(video selfie, FaceTec-backed) and uniqueness on Solana, and Civic **sunset the
Liveness and Uniqueness products on 31 July 2025**. So the obvious "just reuse a
Solana-native liveness pass" path is not merely undocumented, it was retired.

## Consequences for the pitch, not just the build

Independently confirmed by the PM: nothing public on the Solana Mobile org.
Two things follow, and both are the PM's call, not a build decision:

1. **The deck's central comparison is against a product we cannot point at.**
   Slide 3 and Q&A #1 are built on "OpenPass proves identity, we prove work",
   and the strategy doc asserts "OpenPass is Solana's own identity layer on the
   Seeker secure enclave." If a judge knows the ecosystem and OpenPass is not a
   shipped, named Solana Mobile product, that is a credibility hit in the exact
   moment the deck was designed to win. The differentiation argument itself is
   sound and survives a rename — it works verbatim against **Worldcoin/World**,
   and against Civic as the Solana-native example that existed and was retired.
2. **"We could run on top of OpenPass" should not be said** until someone can
   name the integration.

## The passive check, added alongside the motion challenge

The motion challenge closes the still-image attack and nothing else. A **video
replay** of the right person blinking satisfies it, because the motion really
is there. So a second, passive check runs beside it, and both must pass.

**Model:** `litert-community/Silent-Face-Anti-Spoofing-LiteRT` — MiniFASNetV2
at the 2.7 crop scale, Apache-2.0, verified before use (1,850,744 bytes,
sha256 `4ff758f4…08e1b2`, `TFL3` magic) and shipped in
`android/app/src/main/assets/silentface.tflite`. Input `[1,3,80,80]` NCHW,
**BGR**, `x/255`, from a crop ~2.7× the face box; output is a 3-way softmax
where class 1 is live.

Everything decidable is a pure function with tests — crop geometry, channel
order, tensor layout, normalisation, the output reading, and the fusion
policy. Each of those can be wrong in a way that still produces a
correctly-shaped tensor the model will happily score, where the only symptom
is a classifier that appears to guess.

**When the model will not load**, on an accelerator that cannot compile the
graph or a device missing the native library, it fails *visibly*: the passive
check is marked `unavailable` and that value is folded into the liveness proof
hash. A session where only the motion challenge ran therefore produces a
different proof from one where both did, so an attestation records which
checks actually happened rather than implying both. Failing closed would brick
liveness on that device; failing open silently while still saying "human
confirmed" is the dishonest option and the easier one to ship by accident.

**What it still does not buy.** The upstream project ensembles two MiniFASNets
(crop scales 2.7 and 4.0) plus a face-quality gate; this ships one of them, so
expect it to be weaker than the paper. And the server still cannot see the
sensor — a modified build can report success without opening the camera.
Device attestation remains the only answer to that, and remains out of scope.

**Untuned.** `LIVE_THRESHOLD` is 0.70 and `minLiveFrames` is 5. Both are first
guesses and are the numbers most likely to be wrong; they need real spoof
attempts on a real device.

## What the on-device check actually claims

The honest framing, carried over from this repo's existing discipline:

- The camera check runs on the device. The face does not leave the phone; what
  leaves is a hash committed into the signed attestation.
- It raises the cost of faking. It is not a cryptographic proof of humanness,
  and no on-device model can be one — a rooted phone can feed a synthetic
  camera stream, and we should say so if asked rather than be caught by it.
- The chain records that **our verifier** vouched for a liveness result. It does
  not record that liveness was proven. That is why the attestation is
  verifier-signed: it makes the trust boundary explicit instead of implying the
  chain checked something it cannot check.

## Related finding: Solana Attestation Service

Not in the brief, and it turned out to matter: **SAS is real, deployed on
devnet and mainnet, and already implements the verifier-signed trust model**
locked decision #5 describes. It replaces part of the planned attestation
program and sharpens the pitch.

See `docs/ATTESTATION.md` for the verification and the build split.

---

Sources: Solana Mobile docs index (`docs.solanamobile.com/llms.txt`), Solana
Attestation Service (`attest.solana.com`), Civic's product sunset notice.
