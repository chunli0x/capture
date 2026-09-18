# Solana Attestation Service: yes, and here is the split

**Short answer: use it.** SAS is real, live, and implements the exact trust
model the build spec locked in. But it does not hold a bond and cannot slash
one, and the bond is the whole product — so it replaces part of the planned
work, not all of it.

## What was verified, not assumed

- **Program ID `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG`.**
- **Deployed and executable on devnet *and* mainnet-beta**, checked by
  `getAccountInfo` against both clusters. Owner is the upgradeable BPF loader.
- Published by the Solana Foundation, with Civic and SumSub among the named
  issuers.

## Why it fits: it already is the verifier-signed design

Locked decision #5 says the attestation must be verifier-signed rather than a
bare client hash. SAS enforces precisely that, in a Foundation-maintained
program:

- A **Credential** account holds an `authority` and a list of
  `authorized_signers`.
- `create_attestation` calls `verify_signer(authorized_signer)` and then
  `credential.validate_authorized_signer(...)`. An attestation that our
  verifier did not sign cannot exist.
- The stored `Attestation` records the `signer` pubkey, so a third party reads
  *which* authorized key vouched for it.

That is the honest v1 trust boundary we were going to hand-build, already
written and already deployed.

## What SAS hands us for free from the security review

Three of the blockchain-dev findings stop being our code to get right, at
least on the attestation side:

| Review finding | SAS answer |
|---|---|
| Gate `initialize` — anyone could become admin | The Credential PDA is `["credential", authority, name]`. The authority is *in the seed*, so there is no race to become admin — a different authority is simply a different account. Strictly better than a hardcoded deployer key. |
| Add `update_authorities` — the single authority cannot rotate | `change_authorized_signers` exists, gated by the credential authority. |
| Replay / uniqueness | The attestation PDA is `["attestation", credential, schema, nonce]` and `init`s once, so a duplicate is rejected by account creation. |

Plus two things the brief did not ask for and we would not have built:
`expiry` validation, and `is_paused` on a schema so a compromised task type can
be switched off without touching deployed accounts.

## The one that sells the demo: tokenized attestations

`create_tokenized_attestation` mints a **Token-2022** credential with the
**NonTransferable** and **PermanentDelegate** extensions. That is a soulbound
credential that appears in the holder's own wallet, and that the issuer can
still burn via the permanent delegate.

For a demo whose money shot is "the portable credential", a credential the
judge can see *in their wallet* — in the ecosystem's standard shape, not our
bespoke account — is a materially better ending than a custom account we read
back through our own endpoint.

## What SAS does not do, and therefore what we still build

This is the part that matters, because it is why the custom program survives:

1. **No bond.** SAS has no concept of stake. It cannot escrow HUMAN.
2. **No slash.** There is no instruction that takes someone's tokens. Our claim
   is not "someone attested this", it is "someone attested this with money at
   risk" — that difference is the entire moat and it has to live in a program
   we own.
3. **No update.** The instruction set is create / close, with no mutate. So the
   `status` transition the review asked for (`Attested → Challenged → Slashed`)
   cannot be an in-place edit of a SAS attestation. Status lives in our
   account; SAS's own revocation is `close_attestation`.
4. **The human does not sign.** `create_attestation` takes `payer` and
   `authorized_signer` only. Our design binds the liveness proof through the
   human's MWA signature, and that binding has to be enforced by our program —
   SAS would happily record an attestation the human never touched.

## The split

**Our program (`programs/attestation/`)** — the bond layer:
HUMAN escrow, `status`, evidence-hash commitment, the slash instruction
(implemented and tested, not backend-wired, per the brief), and enforcement
that the human signed over the liveness-proof hash.

**SAS** — the credential layer: one Credential for Clock In whose authorized
signer is our verifier, one Schema for `clip_judgment`, and a tokenized
attestation per completed task.

**The join:** SAS's attestation PDA takes a `nonce` pubkey, documented as
"randomly generated OR associated with a User's wallet". We set
`nonce = our bond PDA, derived from [human, task_id]`. That gives the
`[human, task_id]` derivation the review asked for, makes cross-user collision
impossible, and makes each record point at the other: the SAS credential names
the bond account, and the bond account names the credential.

## Costs and risks, stated plainly

- **Integration work is real but small.** Clients ship for Rust and TypeScript
  only; our backend is Python. The instruction encoding is a `u8` tag plus
  length-prefixed fields, which is the same hand-encoding we already do for SPL
  instructions — not a blocker, but it is new code with its own tests.
- **The deployed program may not equal this repo's `main`.** Verify against
  devnet by round-tripping a real `create_credential` before building on the
  struct layouts read here.
- **It is a live dependency on an upgradeable program** we do not control. That
  is a reasonable trade for a Foundation standard, and worth saying out loud
  rather than discovering in Q&A.
- **It is young** (74 stars at time of reading). Foundation-published and on
  mainnet, but not battle-hardened infrastructure.

## What this does to the pitch

It turns the weakest Q&A answer into one of the strongest. "Why didn't you use
SAS?" becomes: *we did — Clock In issues a standard SAS credential, and adds
the thing SAS deliberately leaves out, which is a bond behind the claim.*
Slide 8's SKR argument gets sharper too: the stake is the part of this system
that no existing attestation primitive provides.
