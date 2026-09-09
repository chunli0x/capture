#!/usr/bin/env bash
# Devnet bootstrap: treasury keypair + mock SKR mint + initial supply.
#
# Uses the Solana CLI rather than Python because solana-py 0.40+ dropped both
# its sync client and spl.token.client, so the Python route now means
# hand-rolling mint creation. The CLI writes keypairs as a JSON array of 64
# ints, which is exactly what solders' Keypair.from_bytes reads - no conversion.
#
# Prereqs: solana + spl-token CLI (https://solana.com/docs/intro/installation)
# Run from the repo root. Idempotent: re-running reuses an existing treasury.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
TREASURY="$BACKEND_DIR/treasury.json"
DECIMALS=6
SUPPLY=10000

command -v solana >/dev/null    || { echo "solana CLI not found" >&2; exit 1; }
command -v spl-token >/dev/null || { echo "spl-token CLI not found" >&2; exit 1; }

solana config set --url devnet >/dev/null

if [[ -f "$TREASURY" ]]; then
  echo "reusing treasury at $TREASURY"
else
  solana-keygen new --no-bip39-passphrase --silent --outfile "$TREASURY"
  chmod 600 "$TREASURY"
  echo "created treasury at $TREASURY"
fi
TREASURY_PUBKEY="$(solana-keygen pubkey "$TREASURY")"
echo "treasury: $TREASURY_PUBKEY"

# Devnet airdrops are rate-limited. If this fails, fund the address above at
# https://faucet.solana.com and re-run.
BALANCE="$(solana balance "$TREASURY_PUBKEY" | awk '{print $1}')"
if (( $(echo "$BALANCE < 0.5" | bc -l) )); then
  echo "airdropping 2 SOL..."
  solana airdrop 2 "$TREASURY_PUBKEY" || {
    echo "airdrop failed - fund $TREASURY_PUBKEY at https://faucet.solana.com, then re-run" >&2
    exit 1
  }
fi

echo "creating mock SKR mint..."
MINT="$(spl-token create-token \
          --decimals "$DECIMALS" \
          --fee-payer "$TREASURY" \
          --mint-authority "$TREASURY_PUBKEY" \
          --output json | python3 -c 'import json,sys; print(json.load(sys.stdin)["commandOutput"]["address"])')"

spl-token create-account "$MINT" --fee-payer "$TREASURY" --owner "$TREASURY_PUBKEY" >/dev/null
spl-token mint "$MINT" "$SUPPLY" \
  --mint-authority "$TREASURY" --fee-payer "$TREASURY" >/dev/null

cat <<EOF

==============================================================
  mock SKR mint : $MINT
  treasury      : $TREASURY_PUBKEY
  supply        : $SUPPLY SKR ($DECIMALS decimals)
==============================================================

Write backend/.env:

  TAPFARM_SKR_MINT=$MINT
  TAPFARM_SKR_DECIMALS=$DECIMALS
  TAPFARM_TREASURY_KEYPAIR_PATH=$TREASURY

EOF
