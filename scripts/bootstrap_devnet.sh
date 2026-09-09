#!/usr/bin/env bash
# Bootstrap: treasury keypair, the TAP mint, and a local access-stake mint.
#
#   ./scripts/bootstrap_devnet.sh                     # devnet
#   CLUSTER=localhost ./scripts/bootstrap_devnet.sh   # solana-test-validator
#
# TAP is ours on every cluster - it is what contributors earn and the bond they
# post - so minting it here is the real thing, not a stand-in.
#
# SKR is Solana Mobile's and does not exist on devnet. We deliberately do not
# mint anything called SKR: putting a counterfeit of someone else's token in
# front of judges is not a disclaimer problem, it is a don't. But the stake
# program takes two mints at initialize, so this script also creates a plain
# local mint to occupy the access-stake slot in tests. It is a test fixture, is
# never shown to a user as SKR, and on mainnet that slot holds the canonical SKR
# mint instead - the program cannot tell the difference, which is the point.
#
# Prereqs: solana + spl-token CLI (https://solana.com/docs/intro/installation)
# Idempotent: re-running reuses an existing treasury.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
TREASURY="$BACKEND_DIR/treasury.json"
CLI_CONFIG="$BACKEND_DIR/.solana-cli.yml"
DECIMALS=6
TAP_SUPPLY=1000000
ACCESS_SUPPLY=1000
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
if (( $(echo "$BALANCE < 2" | bc -l) )); then
  echo "airdropping 2 SOL..."
  solana -C "$CLI_CONFIG" airdrop 2 >/dev/null || {
    echo "airdrop failed - fund $TREASURY_PUBKEY at https://faucet.solana.com," >&2
    echo "or re-run against a local validator: CLUSTER=localhost $0" >&2
    exit 1
  }
fi

# $1 = human label, $2 = supply
create_mint() {
  local supply="$1" mint
  mint="$(spl-token -C "$CLI_CONFIG" create-token \
            --decimals "$DECIMALS" \
            --mint-authority "$TREASURY_PUBKEY" \
            --output json \
          | python3 -c 'import json,sys; print(json.load(sys.stdin)["commandOutput"]["address"])')"
  spl-token -C "$CLI_CONFIG" create-account "$mint" >/dev/null
  spl-token -C "$CLI_CONFIG" mint "$mint" "$supply" >/dev/null
  echo "$mint"
}

echo "creating TAP mint..."
TAP_MINT="$(create_mint "$TAP_SUPPLY")"

echo "creating local access-stake mint (test fixture, not SKR)..."
ACCESS_MINT="$(create_mint "$ACCESS_SUPPLY")"

cat <<EOF

==============================================================
  TAP mint      : $TAP_MINT
  access mint   : $ACCESS_MINT   (local test fixture)
  treasury      : $TREASURY_PUBKEY
  cluster       : $CLUSTER
==============================================================

Write backend/.env:

  TAPFARM_TAP_MINT=$TAP_MINT
  TAPFARM_TAP_DECIMALS=$DECIMALS
  TAPFARM_SKR_MINT=$ACCESS_MINT
  TAPFARM_TREASURY_KEYPAIR_PATH=$TREASURY

On mainnet, TAPFARM_SKR_MINT is the canonical SKR mint and this fixture is
not created at all.

EOF
