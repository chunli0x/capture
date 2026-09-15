#!/usr/bin/env bash
# Build and deploy the tapfarm-stake program.
#
#   ./scripts/deploy_stake_program.sh            # localhost (test validator)
#   CLUSTER=devnet ./scripts/deploy_stake_program.sh
#
# Two things here are not obvious and both cost a debugging cycle:
#
# 1. --arch v3 is mandatory. SIMD-0500 (active) disables deployment of SBPF
#    v0, v1 and v2, and cargo-build-sbf still defaults to v0. Deploying a v0
#    binary fails with "Detected sbpf_version required by the executable which
#    are not enabled" plus a generic "invalid account data for instruction",
#    which does not point at the arch at all.
#
# 2. cargo does not treat --arch as a reason to rebuild. Changing it without
#    removing the .so leaves the previous binary in target/deploy, so the
#    deploy keeps failing with the same error while the flag looks correct.
#    Verify with: readelf -h target/deploy/tapfarm_stake.so | grep Flags
#    which should report "CPU Version: 3".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_CONFIG="$ROOT/backend/.solana-cli.yml"
KEYPAIR="$ROOT/programs/tapfarm-stake/program-keypair.json"
SO="$ROOT/target/deploy/tapfarm_stake.so"
CLUSTER="${CLUSTER:-localhost}"

command -v cargo-build-sbf >/dev/null || { echo "cargo-build-sbf not found (install the Solana CLI)" >&2; exit 1; }
[[ -f "$KEYPAIR" ]] || { echo "missing program keypair at $KEYPAIR" >&2; exit 1; }
[[ -f "$CLI_CONFIG" ]] || { echo "run scripts/bootstrap_devnet.sh first" >&2; exit 1; }

solana config set --config "$CLI_CONFIG" --url "$CLUSTER" >/dev/null

echo "building (sbpf v3)..."
rm -f "$SO"
touch "$ROOT/programs/tapfarm-stake/src/lib.rs"
(cd "$ROOT" && cargo-build-sbf --arch v3)

VERSION="$(readelf -h "$SO" | grep -oP 'CPU Version: \K\d+')"
[[ "$VERSION" == "3" ]] || { echo "expected sbpf v3, got v$VERSION" >&2; exit 1; }
echo "verified sbpf v$VERSION"

# Orphaned buffers from a failed deploy hold real SOL; reclaim before retrying.
solana -C "$CLI_CONFIG" program close --buffers --bypass-warning >/dev/null 2>&1 || true

PROGRAM_ID="$(solana-keygen pubkey "$KEYPAIR")"

# Re-running is an upgrade in place, not a no-op: the program id is fixed by the
# keypair, so existing config and stake PDAs survive. Worth saying out loud,
# because "deploy" reads like it might create a second copy.
if solana -C "$CLI_CONFIG" program show "$PROGRAM_ID" >/dev/null 2>&1; then
  echo "program $PROGRAM_ID already deployed - upgrading in place"
fi

solana -C "$CLI_CONFIG" program deploy --program-id "$KEYPAIR" "$SO"

cat <<EOF

deployed $PROGRAM_ID to $CLUSTER

Run the on-chain tests:

  cd backend && TAPFARM_E2E=1 \\
    TAPFARM_STAKE_PROGRAM=$PROGRAM_ID \\
    TAPFARM_TAP_MINT=<tap mint> TAPFARM_SKR_MINT=<access mint> pytest -q

EOF
