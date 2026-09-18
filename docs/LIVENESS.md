# Liveness: the day-one decision

The build spec says to reuse OpenPass if it exposes a usable liveness SDK for
Android/Seeker, and to fall back to an on-device check if it does not — and to
settle that on day one rather than day twenty. This is the answer and the
evidence behind it.

## Decision: on-device fallback

**We build the on-device check.** No integration path to an "OpenPass" liveness
SDK was found, and the reasons matter more than the conclusion, because the
pitch currently rests on OpenPass being a real, named thing.

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

Not in the brief, and worth a decision before submission rather than during
Q&A. **SAS** (`attest.solana.com`) is Solana's own credential primitive —
schemas, credentials, attestations, an issuer/holder/verifier model, Rust and
TypeScript SDKs, `deriveAttestationPda`, with Civic and SumSub among its
partners. A Solana hackathon judge may well ask "why not SAS?".

The defensible answer, and the reason the custom program in this build is still
right: SAS issues credentials, but it does not hold a **bond** or have a path to
**slash** one, and the bond is the entire moat here — the claim is not "someone
attested this" but "someone attested this with money at risk". A bond, a
`status` that can move to `Challenged`, and a slash instruction have to live in
a program we own.

The cheap hedge, if there is time after the definition of done is met: also
emit an SAS attestation alongside ours, so the credential is portable in the
ecosystem's standard shape and the answer becomes "both" rather than "instead".
That is a stretch goal, listed here so it is a decision rather than an
oversight.

---

Sources: Solana Mobile docs index (`docs.solanamobile.com/llms.txt`), Solana
Attestation Service (`attest.solana.com`), Civic's product sunset notice.
