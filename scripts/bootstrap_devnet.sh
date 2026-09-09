#!/usr/bin/env bash
# Devnet bootstrap: treasury keypair + mock SKR mint + initial supply.
#
# Uses the Solana CLI rather than Python because solana-py 0.40+ dropped both
# its sync client and spl.token.client, so the Python route now means
# hand-rolling mint creation. The CLI writes keypairs as a JSON array of 64
# ints, which is exactly what solders' Keypair.from_bytes reads - no conversion.
#
# Prereqs: solana + spl-token CLI (https://solana.com/docs/intro/installation)
# Run from anywhere. Idempotent: re-running reuses an existing treasury.
#
#   ./scripts/bootstrap_devnet.sh              # devnet
#   CLUSTER=localhost ./scripts/bootstrap_devnet.sh   # solana-test-validator
#
# The local validator has no faucet rate limit and is the fastest way to
# exercise the whole claim path. Devnet airdrops are throttled per IP and fail
# routinely from shared or cloud addresses.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
TREASURY="$BACKEND_DIR/treasury.json"
CLI_CONFIG="$BACKEND_DIR/.solana-cli.yml"
DECIMALS=6
SUPPLY=10000
CLUSTER="${CLUSTER:-devnet}"

command -v solana >/dev/null    || { echo "solana CLI not found" >&2; exit 1; }
command -v spl-token >/dev/null || { echo "spl-token CLI not found" >&2; exit 1; }

if [[ -f "$TREASURY" ]]; then
  echo "reusing treasury at $TREASURY"
else
  solana-keygen new --no-bip39-passphrase --silent --outfile "$TREASURY"
  chmod 600 "$TREASURY"
  echo "created treasury at $TREASURY"
fi
TREASURY_PUBKEY="$(solana-keygen pubkey "$TREASURY")"

# A script-local CLI config, so bootstrapping never touches the developer's
# global ~/.config/solana default keypair or cluster. Every call below passes
# -C explicitly; spl-token needs a resolvable default signer even when the
# relevant keys are given as flags.
solana config set --config "$CLI_CONFIG" --url "$CLUSTER" --keypair "$TREASURY" >/dev/null
echo "treasury: $TREASURY_PUBKEY  (cluster: $CLUSTER)"

BALANCE="$(solana -C "$CLI_CONFIG" balance "$TREASURY_PUBKEY" | awk '{print $1}')"
if (( $(echo "$BALANCE < 0.5" | bc -l) )); then
  echo "airdropping 2 SOL..."
  solana -C "$CLI_CONFIG" airdrop 2 "$TREASURY_PUBKEY" >/dev/null || {
    echo "airdrop failed - fund $TREASURY_PUBKEY at https://faucet.solana.com," >&2
    echo "or re-run against a local validator: CLUSTER=localhost $0" >&2
    exit 1
  }
fi

echo "creating mock SKR mint..."
MINT="$(spl-token -C "$CLI_CONFIG" create-token \
          --decimals "$DECIMALS" \
          --mint-authority "$TREASURY_PUBKEY" \
          --output json \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["commandOutput"]["address"])')"

spl-token -C "$CLI_CONFIG" create-account "$MINT" >/dev/null
spl-token -C "$CLI_CONFIG" mint "$MINT" "$SUPPLY" >/dev/null

cat <<EOF

==============================================================
  mock SKR mint : $MINT
  treasury      : $TREASURY_PUBKEY
  supply        : $SUPPLY SKR ($DECIMALS decimals)
  cluster       : $CLUSTER
==============================================================

Write backend/.env:

  TAPFARM_SKR_MINT=$MINT
  TAPFARM_SKR_DECIMALS=$DECIMALS
  TAPFARM_TREASURY_KEYPAIR_PATH=$TREASURY

EOF
