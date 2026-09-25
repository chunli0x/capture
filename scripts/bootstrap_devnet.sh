#!/usr/bin/env bash
# Bootstrap: treasury keypair and the mints - TAP, HUMAN, a USDC stand-in, and
# a local access-stake mint.
#
#   ./scripts/bootstrap_devnet.sh                     # devnet
#   CLUSTER=localhost ./scripts/bootstrap_devnet.sh   # solana-test-validator
#
# HUMAN is the attestation bond: the asset a slash may ever target. It is a
# separate mint from the access gate for the same reason the stake program
# takes two mints - so that "SKR is never slashed" is a fact about the system
# rather than a promise about our future conduct.
#
# USDC on devnet is a stand-in we mint, because payroll is a stablecoin and
# devnet has no USDC we control. On mainnet this slot holds the canonical USDC
# mint and the treasury holds a balance rather than mint authority. It is never
# shown to anyone as if it were real USDC.
#
# This script does NOT create the verifier keypair. That key authorizes every
# attestation; it is generated once, out of band, and installed on the backend
# host at backend/verifier.json with 0600. A bootstrap script that minted a
# fresh authority on every run would be the wrong shape entirely.
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
# Records what was created, so a re-run reuses the mints instead of minting a
# fresh pair every time and silently orphaning the previous ones.
STATE_FILE="$BACKEND_DIR/.bootstrap-state.json"
DECIMALS=6
TAP_SUPPLY=1000000
ACCESS_SUPPLY=1000
HUMAN_SUPPLY=1000000
USDC_SUPPLY=1000000
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

# Reads a previously recorded mint, but only if it still exists on this
# cluster - switching between localhost and devnet must not hand back an
# address that resolves to nothing.
recorded_mint() {
  local key="$1" mint
  [[ -f "$STATE_FILE" ]] || return 1
  mint="$(python3 -c "
import json, sys
try:
    state = json.load(open('$STATE_FILE'))
except Exception:
    sys.exit(1)
if state.get('cluster') != '$CLUSTER':
    sys.exit(1)
print(state.get('$key', ''))
" 2>/dev/null)" || return 1
  [[ -n "$mint" ]] || return 1
  solana -C "$CLI_CONFIG" account "$mint" >/dev/null 2>&1 || return 1
  echo "$mint"
}

# $1 = supply
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

if TAP_MINT="$(recorded_mint tap_mint)"; then
  echo "reusing TAP mint $TAP_MINT"
else
  echo "creating TAP mint..."
  TAP_MINT="$(create_mint "$TAP_SUPPLY")"
fi

if ACCESS_MINT="$(recorded_mint access_mint)"; then
  echo "reusing access-stake mint $ACCESS_MINT"
else
  echo "creating local access-stake mint (test fixture, not SKR)..."
  ACCESS_MINT="$(create_mint "$ACCESS_SUPPLY")"
fi

if HUMAN_MINT="$(recorded_mint human_mint)"; then
  echo "reusing HUMAN bond mint $HUMAN_MINT"
else
  echo "creating HUMAN mint (the slashable attestation bond)..."
  HUMAN_MINT="$(create_mint "$HUMAN_SUPPLY")"
fi

if USDC_MINT="$(recorded_mint usdc_mint)"; then
  echo "reusing USDC stand-in mint $USDC_MINT"
else
  echo "creating USDC stand-in mint (payroll fixture, not real USDC)..."
  USDC_MINT="$(create_mint "$USDC_SUPPLY")"
fi

python3 - "$STATE_FILE" "$CLUSTER" "$TAP_MINT" "$ACCESS_MINT" "$HUMAN_MINT" \
         "$USDC_MINT" "$TREASURY_PUBKEY" <<'PYEOF'
import json, sys
path, cluster, tap, access, human, usdc, treasury = sys.argv[1:8]
json.dump(
    {
        "cluster": cluster,
        "tap_mint": tap,
        "access_mint": access,
        "human_mint": human,
        "usdc_mint": usdc,
        "treasury": treasury,
    },
    open(path, "w"),
    indent=2,
)
PYEOF

cat <<EOF

==============================================================
  TAP mint      : $TAP_MINT
  HUMAN mint    : $HUMAN_MINT   (attestation bond)
  USDC mint     : $USDC_MINT   (payroll stand-in)
  access mint   : $ACCESS_MINT   (local test fixture)
  treasury      : $TREASURY_PUBKEY
  cluster       : $CLUSTER
==============================================================

Write backend/.env:

  TAPFARM_TAP_MINT=$TAP_MINT
  TAPFARM_TAP_DECIMALS=$DECIMALS
  TAPFARM_HUMAN_MINT=$HUMAN_MINT
  TAPFARM_USDC_MINT=$USDC_MINT
  TAPFARM_SKR_MINT=$ACCESS_MINT
  TAPFARM_TREASURY_KEYPAIR_PATH=$TREASURY

On mainnet, TAPFARM_SKR_MINT is the canonical SKR mint, TAPFARM_USDC_MINT is
the canonical USDC mint, and neither fixture is created at all.

Still needed before attestations can be minted, and not created here:

  backend/verifier.json   - the verifier signing key, installed out of band,
                            chmod 600. Its pubkey must equal
                            TAPFARM_VERIFIER_PUBKEY and the pubkey recorded
                            on-chain at initialize.

EOF
