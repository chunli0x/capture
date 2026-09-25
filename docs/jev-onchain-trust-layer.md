# On-Chain Trust Layer for Jev / Bittensor Judgments

Status: design spec, not implemented. Author: blockchain-dev.
Scope: how a Solana or EVM contract safely *consumes* a Jev-style probabilistic
judgment (whether produced by TypeSafe's hosted API or by a Bittensor subnet
serving Jev-shaped judgments as a market). This document assumes the reader
has read `DEMAND-SIDE.md` (the escalate-to-human router) — that spec is
the off-chain producer side; this is the on-chain consumer side.

**One-sentence thesis:** a judgment is a *signed opinion with a calibrated
confidence*, never a fact. Everything below is about not letting that
distinction get lost the moment it touches a token.

---

## 0. What "trust" even means here

A contract that acts on a Jev judgment is trusting three separate things that
are easy to conflate into one:

1. **The signer's identity** — that a specific known key produced this bytes.
   Cryptography solves this completely (ECDSA/ed25519 signature verify).
2. **The signer's honesty** — that the key-holder ran the judgment they claim
   to have run, on the input they claim, and reported the true output.
   Cryptography solves *none* of this. This is where slashing/staking lives.
3. **The judgment's correctness** — that Jev's probability was actually well
   calibrated for this input. Nothing on-chain can verify this. Not staking,
   not a Merkle proof, not a ZK proof of "I ran model X" (that only proves
   inference was run, not that the model is good). This has to be handled by
   never treating (3) as settled — see §3.

Every design below is explicit about which of these three it buys you and
which it doesn't.

---

## 1. Oracle pattern: getting a judgment on-chain

### 1.1 The three candidate designs

**A. Direct commit — hotkey signs each judgment individually**

The Bittensor miner (or the TypeSafe API relayer) signs a single judgment
payload with its hotkey and submits/relays it as a transaction, or a consumer
contract verifies the signature over calldata it received off-chain (EVM:
`ecrecover`; Solana: `ed25519_program` sysvar-verified instruction preceding
the consuming instruction in the same tx).

- Trust assumption: the consuming contract trusts *one specific hotkey* (or an
  N-of-M set of hotkeys it has hardcoded/configured) to both run inference
  honestly and not equivocate (sign two different answers for the same
  question and hand different answers to different consumers).
- Cost: one signature verification per judgment. Cheap on EVM (~3000 gas for
  ecrecover), cheap on Solana (ed25519 program, ~fixed cost, but consumes an
  extra instruction + the signed message must be duplicated in the tx).
  Cheap per-item, but **does not batch** — N judgments cost N verifications
  unless you move to (B).
- Fits: low-frequency, high-value judgments where you want the freshest
  possible answer and can afford a dedicated verify per action (e.g. one
  "should this specific bond release" call).

**B. Hotkey-signed Merkle root batch (recommended default)**

Off-chain aggregator collects K judgments over an interval (e.g. every
block-or-two, or every N judgments), builds a Merkle tree over
`hash(question_id, subject, answer_type, answer_value, confidence,
model_version, timestamp)` leaves, hotkey signs the root, and only the
**root + signature** goes on-chain (one small transaction). Any consumer who
wants to use judgment *i* submits a Merkle proof against the already-posted
root; the contract verifies proof + (once) the root's signature.

- Trust assumption: same as (A) re: the signer (one hotkey's honesty and
  non-equivocation) — but note the *equivocation surface actually gets
  cheaper to catch*: since the root is on-chain and public, if the signer
  serves two different Merkle proofs for the same leaf index/question_id with
  a different value, that's two different roots and both are directly
  comparable and provably contradictory (unlike (A) where you'd need to
  collect two separate off-chain signed messages to prove equivocation, but
  they're never brought together automatically).
- Cost: O(1) signature verify per batch, O(log K) proof verify per consumption
  — this is the standard oracle-batching trick (Chainlink OCR does the same
  shape: aggregate off-chain, one on-chain commit).
  This is the push-oracle pattern — aggregate off-chain, commit one root, verify
  per leaf on consumption — applied to judgments.
- Fits: the Bittensor-subnet case exactly, since a subnet naturally produces
  a *stream* of judgments and validators already aggregate/weight miner
  outputs off-chain before anything goes to chain.

**C. Optimistic (assertion + challenge window) instead of direct signature-only**

Same batch or per-item posting as (A)/(B), but the posted judgment is not
immediately usable — it sits in a challenge window (e.g. minutes to hours)
during which any bonded challenger can dispute it (see §2). Only after the
window closes with no successful challenge does the judgment become
"final" and spendable by a consuming contract. This is UMA's/Kleros' pattern
applied to judgments instead of prices.

- Trust assumption: shifts from "trust the signer" to "trust that someone
  economically motivated will actually watch and challenge bad judgments
  within the window." This is a *real* assumption, not a free upgrade — an
  optimistic oracle with no active watchers is exactly as trusted as (A), it
  just adds latency. It only pays off if disputing is genuinely
  crowd-checkable, which requires the judgment to be independently
  re-derivable — Jev returning no justification directly undermines this
  (see §2, this is the crux of the whole design problem).
- Cost: latency (the window), plus a bonded-dispute infrastructure (bond
  escrow, challenge resolution mechanism — arbitration, another judgment
  round, or a DAO vote).
- Fits: only high-value, non-latency-sensitive, and only if there's an
  independent way to check the judgment (see §2.2 for what that requires and
  why Jev by itself doesn't give you that).

### 1.2 Commit-reveal — does it apply here, and to what?

Commit-reveal in the oracle context normally guards against **front-running
the oracle's own answer** (MEV: seeing the price/answer before it's final and
trading ahead of it). For Jev judgments the analogous attack is: the *subject*
of a judgment (the human/agent being judged) learns the answer is coming and
acts on it before settlement (e.g. sees "grasp_failure: 0.91" about to post
and pulls funds before a bond gets challenged/slashed against them).

Design: the aggregator commits `hash(root)` first, waits a fixed number of
blocks/slots, then reveals `root + signature`. This buys you: the subject
cannot front-run *this specific judgment's on-chain arrival* because they
don't know the root's contents until reveal. It does **not** stop them
front-running the fact that a judgment is coming at all (they know their own
task outcome) — commit-reveal here protects the *content*, not the *event*.
Recommendation: use commit-reveal only when a consuming contract does a
"withdraw before verdict lands" race is the actual attack you're defending
(e.g. union-bond's `release()` after the challenge window — see §5), and skip
it for routing/advisory judgments where no funds move on the judgment alone.

### 1.3 Recommended default

**Batch Merkle root (B), signed by a designated key, consumed per-leaf by
whichever contract needs it, with the judgment treated as evidence that
feeds a human/policy decision (§3) rather than a self-executing trigger.**
Add commit-reveal (§1.2) only around specific instructions where a subject
could race the reveal to their advantage (identify per-integration, don't
apply it blanket). Do not build (C) unless you also build a real dispute
mechanism that can independently re-derive the judgment (§2.2) — otherwise
optimistic is (A) with worse latency and a false sense of security.

---

## 2. Slashing, disputes, challenges — what can actually be disputed

This is the sharp edge of the whole design. Jev returns **no justification**:
you get `{needs_human: {type: noul, noul: 0.93}}`, not "because grip torque
anomaly + prior success rate 0.62 → 0.93." That has direct consequences for
what a challenge mechanism can even be built around.

### 2.1 What you CANNOT dispute

- **"The probability is wrong."** There is no way to contest a calibrated
  confidence number in the abstract — 0.93 isn't "wrong" the way "2+2=5" is
  wrong; it's a distribution statement. You cannot re-run Jev deterministically
  to get a different, provably-more-correct number (the vendor's model is
  a black box, closed API, and calibration is admittedly *not universal*
  per the shared fact base — meaning even Jev's own maker doesn't claim
  the number means the same thing across all task types).
- **"The reasoning is unsound."** There's no reasoning artifact to inspect.
  Nothing to point at.
- **Statistical drift over time** is observable in aggregate (Jev says
  `needs_human=0.93` on 1000 near-identical inputs but humans overturn the
  implied decision 40% of the time) — but this is a *model quality* signal
  for retuning thresholds off-chain (exactly what `DEMAND-SIDE.md`
  already says: "tune against real agreement data"), not a per-judgment
  dispute a challenger can win in a single case.

### 2.2 What you CAN dispute — narrow the challenge to *inputs and process*, not *output*

Since the output can't be second-guessed, the entire dispute surface has to
live in things that are independently checkable:

1. **Wrong input / state manipulation** — the `state` payload handed to Jev
   didn't match reality (e.g. claimed `prior_success_rate: 0.62` when the
   real number was 0.15, or a doctored `error_flags`). This is disputable
   *if and only if* the state payload itself is committed on-chain (hash of
   the exact JSON that was sent, alongside the judgment) so a challenger can
   present the true state and show a mismatch. **Without this, there is
   nothing to challenge at all** — this is the single load-bearing design
   requirement: commit `hash(state_json)` as part of every judgment leaf.
2. **Signer equivocation** — the signer produced two different answers for
   the same `question_id` + `state_hash` (served contradictory judgments to
   different consumers, or double-signed after a bad-faith retry). Directly
   provable on-chain: two signed roots/leaves for the same key, contradicting.
   This is the strongest, cleanest slashable offense in this whole system —
   it needs zero reasoning about Jev's internals.
3. **Stale/wrong model version** — the judgment claims `model_version: jev-v3`
   but the signer's registered/attested model hash doesn't match what was
   actually served (if this is even checkable — TypeSafe's API is closed, so
   for the hosted-API case you cannot prove this; for the Bittensor-subnet
   case, where miners run known model weights and validators can consensus-
   check output distributions across miners, this becomes checkable via
   validator disagreement/outlier detection, which is the subnet's job, not
   this contract's).
4. **Signer failed to sign at all / censorship** — the aggregator refuses to
   include a submitted judgment in any batch. Disputable via a liveness/
   inclusion proof requirement (a submitter can force-include via an L1
   fallback path after a timeout — same pattern as an L2 forced-inclusion
   queue) rather than a "wrongness" dispute.
5. **Consensus disagreement in the Bittensor case** — if the subnet has
   multiple miners answering the same question, wide disagreement across
   miners (e.g. one says 0.93, another says 0.12) is itself a disputable/
   slashable signal *for the outlier* under the subnet's own weight-setting
   mechanism (this is exactly what Bittensor consensus/Yuma is for) — but
   that dispute happens at the subnet layer, before the judgment is even
   posted on the target chain. By the time a root reaches an EVM/Solana
   consumer, treat "the subnet already reached rough consensus" as itself
   a trust input, and require the batch to carry a consensus-weight, not
   just one miner's raw answer.

### 2.3 Concrete dispute/slash mechanism

- **What's staked**: the signer's own bond (a slashable stake token — TAP-
  equivalent, or the subnet's own dTAO/alpha stake for a Bittensor miner).
- **Challenge window**: fixed duration after a root posts (e.g. matching
  union-bond's existing `challenge_window_seconds` pattern — reuse it).
- **Challenge = commit an `evidence_hash`** exactly like `union-bond::challenge`
  already does — an off-chain-resolved dispute, on-chain state transition
  only. The evidence for a judgment-challenge is one of: (a) the true state
  payload proving a state-hash mismatch, (b) two conflicting signed leaves
  for the same question, (c) a subnet consensus report showing this miner
  as a statistical outlier beyond a threshold.
- **Resolution**: for (a)/(b) resolution can be **fully on-chain and
  automatic** — the state hash mismatch or the two conflicting signatures
  are self-proving; a permissionless `resolve_challenge_by_proof` instruction
  can slash immediately once the proof verifies, no human judge needed. For
  (c) resolution needs an external arbiter (the subnet's own validator set,
  or Union's `slash_authority` acting on a report) because "outlier beyond
  threshold" is a judgment call, not a pure function of on-chain data —
  don't pretend otherwise.
- **What slashing buys you**: it does not make Jev's judgments correct. It
  makes *lying about what was sent or what was signed* expensive. That is
  the entire ceiling of what an on-chain slashing mechanism can do against
  a no-justification oracle. Say this explicitly to anyone consuming this
  design — slashing is a deterrent against **misrepresentation**, not
  against **being wrong**.

### 2.4 Concrete attack vectors against the dispute design itself

- **Griefing via cheap challenges**: if `challenge` has no bond requirement,
  anyone can freeze every judgment forever. Mitigation: require a challenge
  bond (union-bond doesn't currently require one on `challenge` — flag this
  as a gap to fix before wiring judgments in, since a judgment-challenge
  needs the same protection as a bond-challenge).
- **Nothing-at-stake for the aggregator between batches**: if the signer's
  bond is small relative to the value the batch gates, misrepresenting the
  state hash for a high-value judgment and eating the slash is profitable.
  Mitigation: bond must scale with the maximum value a single batch can
  authorize downstream, or cap per-batch authorized value.
- **Selective non-inclusion (censorship) is not "wrong," so it's not
  slashable under §2.2 unless you add the liveness requirement in (2.2.4)
  explicitly** — otherwise an aggregator can quietly drop unfavorable
  judgments with zero consequence.
- **State-hash gaming**: if the `state` payload is attacker-influenced (e.g.
  an agent that controls its own `prior_success_rate` field before handing
  it to Jev), disputing "the state hash matches what was sent" proves
  nothing about whether the state was *honestly constructed upstream*. This
  pushes the trust boundary one level back — the on-chain layer can only
  ever verify "the signer didn't change the input after receiving it," never
  "the input was true." Document this boundary loudly; it's routinely where
  these systems get exploited (garbage in, cryptographically-attested out).

---

## 3. The honest boundary — what MUST stay off-chain

This is not a nice-to-have, it's the core safety property of the whole
system, and it should be enforced structurally, not by convention:

- **Jev's output is admissible evidence, never a self-executing trigger for
  anything irreversible or high-value** (fund release beyond a bonded
  challenge-window amount, permanent reputation/ban decisions, anything
  affecting a human's livelihood or safety). The existing `10-jev-
  integration.md` design already gets this right for the off-chain router
  ("Jev decides *when* to escalate, never the outcome"); the on-chain layer
  must preserve the same split, not regress it just because a signature
  makes the number look authoritative.
- **Structural enforcement, concretely**: no instruction should accept a
  Jev judgment as its *sole* authorization for a state-changing, value-
  moving action. Every consuming instruction should require the judgment
  AND (a human/keeper signer whose only job is to confirm the judgment was
  read, or (b) a hard policy check — e.g. "only auto-slash if judgment
  confidence > 0.98 AND amount < $X AND a 24h window with no challenge has
  passed" — i.e. policy is a second independent gate, not a rubber stamp).
  This mirrors why `union_bond::slash` requires going through `Challenged`
  first rather than allowing `Attested → Slashed` directly (see the existing
  `may_transition` table) — the same "can't skip the human gate" shape,
  applied one level up to the judgment itself.
- **Calibration is explicitly not universal** (shared fact base) — a
  contract must not treat "0.93" as meaning the same thing across different
  `task_type`s or even across model versions. Any threshold used on-chain
  (like the `>0.70` escalate rule in `DEMAND-SIDE.md`) must be
  tagged with the exact `model_version` + `task_type` it was tuned against,
  and a version bump on the signer side should require a corresponding
  threshold review, not silent reuse of old thresholds against a new model.
- **What this means practically for Union**: a Jev/Bittensor judgment batch
  can plug into `union-bond` as the thing that **opens or closes a
  challenge window faster** (e.g. "Jev flags this attestation as
  needs_human > 0.9" → auto-open a `Challenge` state so a human has to look
  before the bond auto-releases) — a judgment as an *accelerant on the human
  loop*, never as a replacement `slash` authority. Do not wire a Jev batch
  directly to `slash` or `release`. Wire it to `challenge` (a reversible,
  disputable state) at most.

---

## 4. Key custody

Three distinct keys, do not conflate them:

| Key | Role | Compromise blast radius | Storage |
|---|---|---|---|
| **Bittensor coldkey** | Owns the miner/validator's stake and identity on the subnet; controls registration, weight-setting rights, withdrawal of stake. | Total — loses the stake, can be deregistered, subnet identity stolen. This is the "everything" key. | Offline / hardware wallet / multisig. Never touches an online process. |
| **Bittensor hotkey** | Signs judgments and subnet-level messages (weight votes, axon responses); the thing that would also sign judgment batches if reused for that purpose. | Bounded to whatever the hotkey is authorized to do on the subnet (submit judgments, set weights) — does **not** control the stake itself, but a compromised hotkey can still get the miner slashed via bad behavior, and if reused as the on-chain signer, can post fraudulent judgment batches up to the signer's authorized scope. | Hot, on the serving machine, by necessity (needs to sign quickly, ~70-500ms path). Rotatable without moving stake. |
| **Relayer / batch-signing key (separate from both)** | Recommended: a *third*, dedicated key that only signs the Merkle roots/batches submitted to the target chain (EVM/Solana). Not the Bittensor hotkey itself. | Bounded to "can post a fraudulent batch," same ceiling as hotkey compromise, but crucially **does not touch subnet stake or weight-setting at all** — compromising it doesn't let an attacker deregister the miner or steal Bittensor-side stake, and rotating it doesn't require any Bittensor-side re-registration. | Hot key, but isolated: separate HSM/KMS, separate machine/process from subnet weight-setting, minimal permission scope (can only sign batch roots, nothing else). |

**Why a separate relayer key and not the raw hotkey**: reusing the Bittensor
hotkey as the direct on-chain signer couples two blast radii that don't need
to be coupled — a hotkey compromise then means both "bad weights on the
subnet" and "fraudulent judgments accepted by every EVM/Solana consumer,"
and rotating the on-chain trust anchor (e.g. after a suspected leak) then
forces a subnet-side hotkey rotation too, which has its own cost/disruption.
Splitting them means the on-chain consumers' trust root (relayer pubkey) can
be rotated independently and fast, without touching the subnet identity.

**Rotation mechanism**: mirror what `union_bond::update_authorities` already
does — an `Option<Pubkey>` per role, admin-gated, emits an event, no
migration of existing state needed. Extend this pattern: add a
`judgment_signer: Pubkey` (or `Vec<Pubkey>` for N-of-M) field to whatever
config account consumes judgment batches, rotatable the same way. Keep a
**grace period** on rotation — old signer still valid for judgments with
`timestamp < rotation_time + grace`, so in-flight batches signed just before
rotation don't get silently orphaned.

**Compromise response runbook** (write this down before it's needed):
1. Detect (equivocation proof surfaces, off-chain monitoring flags anomalous
   judgment patterns, or the relayer operator reports key loss).
2. Admin calls `update_authorities`-equivalent to swap `judgment_signer` to
   a fresh key immediately — this is the fast, cheap mitigation.
3. Any batches signed by the old key after the suspected compromise time get
   challenged (§2) and, if state-hash mismatches are found, slashed.
4. Bittensor-side: if the hotkey itself (not just the relayer key) was the
   one compromised, additionally rotate the hotkey and, if stake is at risk,
   move via the coldkey to a fresh hotkey registration — slower, more
   disruptive, exactly why it should never be the same key as (3).

---

## 5. Concrete integration with Union's Solana programs

Reviewed: `/home/hermes/tap-ci/programs/union-bond/src/lib.rs` and
`tapfarm-stake/src/lib.rs` (Anchor, devnet-deployed, `slash`/`challenge`
implemented but unwired per the module docs — "nothing here says a false
attestation has ever actually been punished").

### 5.1 Where a judgment batch plugs in

Add a **new, small program** (`jev-oracle` or fold into `union-bond` as a
new account type — recommend a separate program: keeps `union-bond`'s audited
surface untouched and makes the oracle swappable per the caveat in
`DEMAND-SIDE.md`, "keep the escalation logic behind a thin
interface"). Shape:

```rust
// New program: jev-oracle

pub const ORACLE_CONFIG_SEED: &[u8] = b"oracle_config";
pub const BATCH_SEED: &[u8] = b"judgment_batch";

#[account]
#[derive(InitSpace)]
pub struct OracleConfig {
    pub admin: Pubkey,
    pub judgment_signer: Pubkey,   // the relayer key from §4, rotatable
    pub prev_signer: Pubkey,       // grace-period fallback, see §4
    pub prev_signer_valid_until: i64,
    pub min_challenge_bond: u64,   // fixes the griefing gap noted in §2.4
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct JudgmentBatch {
    pub merkle_root: [u8; 32],
    pub posted_at: i64,
    pub model_version: [u8; 8],     // fixed-width tag, e.g. b"jev-v3\0\0"
    pub batch_id: u64,              // monotonic, prevents replay/reorder confusion
    pub status: BatchStatus,        // Posted -> Challenged -> (Resolved | Slashed)
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum BatchStatus { Posted, Challenged, Resolved, Slashed }

// one instruction: post a signed batch (verifies an ed25519-program
// instruction that precedes this one in the same tx, checking the pubkey
// matches OracleConfig.judgment_signer or prev_signer-within-grace)
pub fn post_judgment_batch(ctx: Context<PostBatch>, root: [u8;32], model_version: [u8;8], batch_id: u64) -> Result<()>

// per-consumer: verify one leaf against an already-posted root
pub fn verify_leaf(
    root: [u8; 32],
    proof: Vec<[u8; 32]>,
    leaf: JudgmentLeaf, // { question_id, subject: Pubkey, state_hash: [u8;32], answer_type, answer_value, confidence_bps: u16 }
) -> Result<bool>  // a library fn other programs' CPI into, or inline via a shared crate

// challenge a batch with an evidence hash (state-hash mismatch or
// equivocation proof), same shape as union_bond::challenge
pub fn challenge_batch(ctx: Context<ChallengeBatch>, batch_id: u64, evidence_hash: [u8;32]) -> Result<()>

// self-proving resolution paths (see §2.3): anyone can call, no human needed,
// if the proof actually verifies
pub fn resolve_equivocation(ctx: Context<...>, leaf_a: JudgmentLeaf, proof_a: Vec<[u8;32]>, root_a: [u8;32],
                                                leaf_b: JudgmentLeaf, proof_b: Vec<[u8;32]>, root_b: [u8;32]) -> Result<()>
// checks: same question_id + state_hash, different answer_value, both proofs
// verify against their respective (both already-posted, both signed) roots
// -> mark both batches Slashed, emit event, slash_authority's downstream
// slash() call is a separate follow-up ix (keep this program token-agnostic;
// let union-bond/tapfarm-stake own the actual token movement)
```

### 5.2 How `union-bond` consumes it (no change to `union-bond`'s core, one new CPI-callable path)

- **Do not** add a Jev-authorized path to `slash` or `release`. Per §3, wire
  a judgment result to `challenge` only:
  - New instruction on `union-bond`, `challenge_from_judgment`, that is
    identical to the existing `challenge` except the signer is the
    `jev-oracle` program (via CPI) instead of `slash_authority` directly,
    and it additionally stores the `JudgmentBatch` pubkey + leaf index it
    acted on in the `evidence_hash` slot (hash of the leaf, not raw
    evidence, keeping `union-bond`'s existing "commitment, not the evidence"
    design intact).
  - This means: a `needs_human`/`is_risky` Noul from a judgment batch about a
    specific bond's task can *open* a challenge automatically — flip
    `Attested -> Challenged` — which **blocks `release()`** (per the existing
    `may_transition`/`releasable` logic, a `Challenged` bond never releases
    by waiting) and forces a human through `dismiss_challenge` or `slash`.
    This is a real, useful, and safe use of the judgment: it can only ever
    make the system *more* conservative (block an auto-release), never
    directly move funds.
  - `slash()` stays exactly as-is: only `slash_authority` (a human/multisig
    per the existing design) can call it, judgment or no judgment. The
    judgment is context they can look at off-chain when deciding to call it,
    exactly like `evidence_hash` already invites them to.

### 5.3 `tapfarm-stake` integration

Same shape: `tapfarm_stake::slash` is called by `slash_authority`, doc'd as
scored by `tapfarm/scoring.py` "which is the oracle here." A judgment batch
can *feed* that scoring pipeline (an input signal to the off-chain quality
score) but should not get a direct on-chain call path into `slash` — the
existing design already has exactly one designated oracle (the scoring
script) authorizing the one instruction that moves money; adding a second,
parallel authorization path (Jev) undermines the "who can slash" invariant
the review already hardened. If Jev-derived signals should influence slashing,
they go into `scoring.py`'s inputs off-chain, not around it on-chain.

### 5.4 Net new surface, summarized

- +1 new program (`jev-oracle`): config, batch posting, per-leaf verify,
  equivocation-resolution, challenge-with-bond.
- +1 new instruction on `union-bond` (`challenge_from_judgment`), CPI-gated
  to the oracle program, reusing the existing `Challenge` account shape.
- 0 changes to `slash`, `release`, or `tapfarm-stake` — judgments never get
  a direct value-moving path, by construction.

---

## 6. Latency reality: 70-500ms inference vs. async settlement

Jev's inference latency (70-500ms) is irrelevant to on-chain timing — it's
swamped by everything downstream:

- Batch aggregation window (design choice: seconds to minutes, trades
  latency for cheaper per-judgment settlement cost).
- Transaction inclusion: Solana ~400ms-a few seconds practical finality;
  EVM L1 ~12s+ block time, L2s vary; either way, orders of magnitude past
  Jev's own compute time.
- The challenge window itself (§2.3) is intentionally minutes-to-hours.

So the correct mental model is **three separate clocks that must not be
conflated**:

```
t0            t0+70-500ms        t0+batch_window        t0+inclusion        t0+challenge_window
Jev call ──► judgment ready ──► included in batch ──► root posted ──► judgment "final" & usable
             (off-chain,          (off-chain                (on-chain,          (on-chain, only
              synchronous)         aggregator)                 tx confirmed)     if using pattern C,
                                                                                   or immediately if
                                                                                   using B without an
                                                                                   extra window — see below)
```

### 6.1 The async flow, concretely

1. **Synchronous leg** (0-500ms): agent/consumer calls Jev, gets a typed
   answer + confidence back in-process. This is exactly the existing
   `DEMAND-SIDE.md` flow — nothing changes here, this leg never
   touches a chain and shouldn't. Decisions that don't need on-chain
   settlement (e.g. "should the agent proceed or escalate") stay entirely in
   this leg, at Jev's native speed.
2. **Commitment leg** (async, seconds-to-minutes): only judgments that *will*
   need to be referenced on-chain (e.g. "this specific task's outcome feeds
   a bond's challenge state") get queued into the aggregator's next batch.
   The consumer does **not** block waiting for this — the agent proceeds
   with its off-chain decision immediately (leg 1), and the on-chain
   consequence (opening a challenge, adjusting a score) lands later,
   asynchronously, whenever the batch posts.
3. **Settlement leg** (on-chain, its own latency): batch root posts, any
   consumer contract that cares calls its consuming instruction
   (`verify_leaf` + `challenge_from_judgment` etc.) whenever convenient —
   this is pull, not push; nothing forces immediate consumption. Design
   consuming instructions to be **idempotent and order-independent**: a
   `challenge_from_judgment` call for a leaf that already resulted in a
   challenge should no-op or explicitly reject rather than double-transition,
   the same way `may_transition` already rejects illegal transitions.
4. **No consuming instruction should ever assume "the on-chain state reflects
   the judgment within X ms of the Jev call"** — treat the gap between (1)
   and (3) as unbounded from the contract's point of view. Anything that
   needs the judgment fast (e.g. blocking a specific transaction before it
   lands) has to use the direct-commit path (§1.1 A) at the cost of one
   signature verify per use, accepting the higher per-item cost for lower
   latency — this is the actual latency/cost tradeoff, and it should be
   picked per integration, not assumed globally.

### 6.2 Attack surface created by the async gap

- **Stale-judgment reuse**: an old, still-technically-valid-signature leaf
  gets submitted against current state long after the judgment was made
  (e.g. task state changed, but the leaf's implied claim no longer applies).
  Mitigation: every leaf carries `posted_at`/`batch_id`, and consuming
  instructions must check a max-staleness bound (the standard
  "always check staleness, fail closed" rule for price oracles — apply
  identically here).
- **Race between leg 1 (off-chain decision) and leg 3 (on-chain settlement)**:
  the agent already acted on the judgment (leg 1) before the on-chain
  challenge opens (leg 3) — meaning a bad actor who knows a damning judgment
  is coming has the entire batch-window + inclusion time to act first (e.g.
  request `release()` before `challenge_from_judgment` lands). Mitigation:
  this is exactly why `union-bond`'s `challenge_window_seconds` exists
  *independent* of the judgment pipeline — a bond is never releasable until
  its own window passes regardless of whether a judgment ever shows up, so
  the fix is "make the batch-window + inclusion time comfortably shorter
  than the bond's own challenge window," not any change to the judgment
  pipeline itself. State this dependency explicitly in config: batch
  aggregation interval must be << `challenge_window_seconds`.
- **Batch-window griefing**: an aggregator can strategically delay including
  a specific unfavorable judgment in any batch (soft censorship, cheaper than
  outright dropping it since it's not provably excluded from *any* batch,
  just delayed). Mitigation: same liveness/forced-inclusion idea as §2.4 —
  a submitter can escalate to a fallback direct-commit path (§1.1 A) if their
  judgment hasn't appeared in a batch within a bounded number of intervals.

---

## Summary table

| Question | Answer |
|---|---|
| Oracle pattern | Hotkey/relayer-signed Merkle batch (pull), commit-reveal only where front-running the reveal is a real threat |
| Can you dispute Jev's output? | No. You can only dispute the input (state hash mismatch) or the signer's behavior (equivocation, censorship) |
| Who signs on-chain | A dedicated relayer key, never the Bittensor hotkey directly, never the coldkey |
| What can a judgment authorize | Opening a challenge / raising a score signal. Never a direct slash or fund release |
| Where does it plug into Union | New `jev-oracle` program + one new `challenge_from_judgment` ix on `union-bond`; zero changes to `slash`/`release` |
| Latency model | Jev's 70-500ms is irrelevant; design around batch-window + inclusion + challenge-window, and keep batch-window << challenge-window |