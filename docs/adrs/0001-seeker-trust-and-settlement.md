# ADR 0001: Seeker trust and settlement boundaries

Status: accepted, 2026-10-05.
Decision owner: Lisa Cheng; approved in the review/proceed exchange.

The approved contract is [SEEKER-PHASE-1.md](../SEEKER-PHASE-1.md).
It replaces the uploaded brief's conflicting stack, model, moderation,
consensus and settlement examples for phase 1.

Identity is a signed wallet session; eligibility is a separately authorized
registration. Fresh liveness hashes and SAS credentials alone do not prove
one-person-one-account. Every write authorizes the authenticated resource owner.

Moderation verdicts authorize one immutable content version. Bounty content
cannot be replaced after approval, review or acceptance. A private quarantine
is distinct from approved media, with bounded size and automatic cleanup.

Independent annotations refer to the same media coordinate frame. Consensus
is a quality gate, not permission to move money. Requester acceptance and
the program's immutable recipient/amount decide USDC settlement. No off-chain
prepare operation consumes earnings. SKR is held separately and not slashed
for honest disagreement.

Source/static, local, CI, deployed and provider evidence must be distinguished
in the delivery receipt. Configuration cannot silently enable a demo PASS,
simulated payment or arbitrary identity path in production.

Consequence: the new ASGI app and new escrow program establish a separate
boundary from the legacy Union demo. Database and on-chain operations use
idempotent, reconcilable transitions rather than one fragile dual write.
