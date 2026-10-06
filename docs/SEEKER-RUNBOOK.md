# Object pilot operator guide

Status: development branch. No live deployment or real-token payment is claimed.
Read `SEEKER-PHASE-1.md` and ADR 0001 before starting. The Seeker service is
separate from the existing `tapfarm.main:app`; never expose the legacy reward
API as a Seeker authentication or settlement endpoint.

## Environment and dependencies

Python 3.11+, PostgreSQL 17, Rust/Anchor 1.2, Agave build tools and Android SDK 37.
Install `backend/requirements-seeker.txt`. All `SEEKER_*` secrets below must be
in a secret manager or an untracked environment file, never in the app or git.

| Variable | Required value |
| --- | --- |
| `SEEKER_DATABASE_URL` | Dedicated `postgresql+psycopg://…` database |
| `SEEKER_DOMAIN` | Your sign-in domain, shown in the signed challenge |
| `SEEKER_OPERATOR_KEY` | Random secret, at least 32 characters |
| `SEEKER_MEDIA_KEY` | Base64 of 32 independent random bytes; back up separately from DB |
| `SEEKER_CLUSTER` | `devnet` (or explicit loopback-only `localnet`) |
| `SEEKER_RPC_URL` | RPC for that cluster; devnet genesis is verified |
| `SEEKER_PROGRAM_ID` | Deployed Seeker program ID |
| `SEEKER_USDC_MINT` | Disposable 6-decimal TEST-USDC mint |
| `SEEKER_SKR_MINT` | Separate disposable TEST-SKR mint |
| `SEEKER_MIN_BOND` | Positive TEST-SKR base units; same value as program config |
| `SEEKER_VERIFIER_KEY_FILE` | Operator-held Solana verifier keypair JSON path |
| `SEEKER_SIGHTENGINE_USER`, `SEEKER_SIGHTENGINE_SECRET` | Enabled face-age API credentials |
| `SEEKER_HIVE_KEY` | Enabled **Combined CSAM** project key, not a generic moderation key |

A missing moderation credential or incomplete response blocks uploads. Test
doubles are dependency-injected by tests only; there is no environment flag to
make production return PASS or simulate payments.

For an explicitly local test adapter, set `SEEKER_LOCAL_SQLITE=true` and use a
file-backed SQLite URL. SQLite serializes transactions with BEGIN IMMEDIATE.
Deployment uses PostgreSQL row locks and uniqueness constraints. Do not run
multiple services with separate SQLite files and expect shared balances.

```sh
cd backend
python -m pip install -r requirements-seeker.txt
python -m seeker.migrate
uvicorn seeker.api:production_app --factory --host 127.0.0.1 --port 8001
```

Use a TLS reverse proxy, 15 MiB body limit, upload/concurrency limits and request
rate limits. Do not trust arbitrary X-Forwarded-For headers. The application's
unauthenticated challenge limit uses the actual peer IP. Exclude bearer tokens,
operator headers, raw provider responses and image bodies from access logs.

## Program deployment boundary

The committed program ID is a development identity, **not a deployed address**.
Generate an operator-owned program keypair; update `declare_id!`, Anchor.toml,
the test fixture and environment together. Never reuse real asset mints.
`cargo build-sbf --manifest-path programs/seeker-bounty/Cargo.toml` builds the
program. Initializing config requires the program's upgrade authority, so an
arbitrary first caller cannot claim it. Config is immutable in this version.
Changing verifier/mints requires a separately reviewed program migration.

`python ../scripts/seeker_initialize.py --help` describes the explicit config
initialization command after deployment. It supports only devnet/localnet.
Do not deploy to mainnet. The program itself cannot observe a network's name;
network checks are in the operator/client boundary, not a magical on-chain flag.

The verifier co-signs only immutable, moderated, independently reviewed work.
Protect this signing key: it is a trusted eligibility authority, not a proof
of cloud moderation or unique humanity enforced directly by Solana.

## Pilot operation

1. Create wallets for requester, worker and two independent reviewers. An
   operator must verify which test participant controls each wallet before
   granting worker/reviewer capabilities through `POST /operator/enroll` with
   `X-Operator-Key`. Every participant separately signs in through MWA.
2. Supply test SOL and the disposable test tokens. The worker deposits the
   configured TEST-SKR minimum; withdrawal requires no pending fulfillments
   and a 24-hour cooldown from the most recent deposit. No automatic slashing.
3. The requester creates a draft, then signs funding for `reward × slots`.
   Only a finalized matching transaction opens the bounty.
4. A worker reserves a 20-minute capture slot. JPEG/PNG only, 32 pixels minimum
   per side, at most 12 million pixels and 15 MiB before and after re-encoding.
   The server strips metadata, scans canonical PNG bytes, then encrypts approved
   bytes using AES-256-GCM. Failed media remains only in bounded request memory;
   it is never written to an approved object store. Approved pilot media is
   encrypted in PostgreSQL, not publicly addressable or signed-upload writable.
5. Capture and draw normalized xywh boxes manually. Image and submitted labels
   are immutable. The upload retry returns the same content hash. Per-bounty
   SHA-256/dHash checks reject duplicates/near duplicates without bond penalties.
6. Two enrolled reviewers label that exact image without seeing the author or
   each other's labels. Every box must have a one-to-one same-category match
   at IoU ≥ 0.7 in all three pairs. Disagreement stops at `disputed`; it pays
   nobody. Enrollment limits identity abuse; it does not solve Sybil resistance.
7. The worker registers eligible work with both worker and verifier signatures.
   This reserves one reward on chain and locks a bond liability. The requester
   inspects the photo and labels, then explicitly accepts and pays that one
   submission, or rejects with zero payment. No timeout auto-acceptance exists.
8. After the deadline, expire each pending fulfillment to unlock its bond.
   Refund returns only escrow not reserved by pending fulfillments; it may be
   retried after remaining pending work expires. Rejected/expired slots are
   consumed, not resold. A bounty cannot pay more than its funded slot count.

Preparation does not send a transaction, consume credit, or record payment.
Use `/transactions/{id}/confirm` with its wallet-returned signature. If the
callback was lost, use `/reconcile` to inspect the most recent 100 transactions
on that PDA, or provide the original signature. Confirmation checks successful
finalization, real signatures and the exact prepared message. Old attempts are
retained across restarts; repeat confirmation has no financial side effect.

## Android

The launcher opens the Kotlin/Compose Seeker pilot. The legacy demo screens
remain in source. Build with `-PseekerApiBase=https://your-pilot-server`.
HTTP is enabled only by the debug manifest. Release builds are not debug-signed.
Bearer sessions remain in memory; closing the app requires signing in again,
while claims, work and transaction recovery remain durable on the server.

The box editor uses the approved image's actual aspect ratio, supports reverse
drags, undo, category selection and coordinate entry. No model creates labels.
Camera capture, MWA signing, cancellation, account switching, and interrupted
upload/confirmation must be checked on a real Seeker before a participant pilot.

## Known limits and decisions still needed

- Not a production unique-human identity system; operator enrollment is explicit.
  Sybil resistance is the existing SAS credential + local liveness + operator
  enrollment. Over-18 is a self-attested signed claim (declaration, not proof);
  this is a hackathon pilot with no hard age verification in scope.
- Face rejection is a conservative object-pilot filter, not a guarantee of no
  minors. dHash can reject visually simple unrelated pictures; no slashing.
- Hive/Sightengine thresholds need live benign fixtures and approved operational
  policy. The parsers follow the documented Combined API/face-age responses;
  schema drift, failures and missing fields fail closed.
- Media license, consent terms, retention/deletion and reporting/escalation
  obligations need an approved policy before collecting participant content.
  This code does not grant a training license or invent legal compliance.
- Approved media remains encrypted until the operator applies an agreed
  deletion policy. Keep the test population and dataset bounded. This version
  has no automatic retention job, commercial reviewer payouts, sponsored bonds,
  honeypots, fraud arbitration/slashing, places, video/actions or keypoint jobs.
- Automated review proves neither runtime transfer safety nor hardware behavior.
  See the verification receipt for the checks actually run.

## Source contracts consulted

- https://docs.thehive.ai/reference/csam-detection-combined-api-reference
- https://sightengine.com/docs/face-age-minor-detection
- https://docs.solanamobile.com/android-native/using_mobile_wallet_adapter
- https://www.anchor-lang.com/docs/references/account-constraints
