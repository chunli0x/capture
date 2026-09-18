"""Round-trip the SAS instructions against the real deployed program.

`test_sas.py` proves our encoder agrees with a reader written from the SAS
repository's source. That is not the same as agreeing with the bytecode running
on devnet: the program is upgradeable, and the deployed version may be ahead of
or behind the source we read. This test closes that gap by submitting a real
`create_credential` and reading the account back.

Until this has been run once, treat `sas.py` as verified against source only -
docs/ATTESTATION.md says so explicitly.

Skipped unless a validator is reachable. To run it against a local validator
carrying the real SAS bytecode, clone the deployed program:

    solana-test-validator --reset --quiet \
      --clone 22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG --url devnet &
    cd backend && TAPFARM_E2E=1 TAPFARM_RPC_URL=http://localhost:8899 \
      pytest tests/test_e2e_sas.py -v

Or against devnet directly, with a funded payer:

    TAPFARM_E2E=1 TAPFARM_RPC_URL=https://api.devnet.solana.com \
      TAPFARM_E2E_PAYER=/path/to/funded.json pytest tests/test_e2e_sas.py -v

A local validator is preferable for the same reason as the claim test: devnet
airdrops fail routinely from shared or cloud IPs, which is exactly what
happened when this test was written, and why it ships unrun.
"""

from __future__ import annotations

import json
import os
import pathlib
import secrets

import pytest
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from tapfarm.sas import (
    SAS_PROGRAM_ID,
    create_credential_ix,
    derive_credential,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("TAPFARM_E2E") != "1",
        reason="set TAPFARM_E2E=1 with a reachable validator to run",
    ),
    pytest.mark.asyncio,
]

PAYER_LAMPORTS = 1_000_000_000


def _rpc_url() -> str:
    return os.environ.get("TAPFARM_RPC_URL", "http://localhost:8899")


async def _funded_payer(rpc: AsyncClient) -> Keypair:
    """A payer with lamports, however this environment can provide one."""
    supplied = os.environ.get("TAPFARM_E2E_PAYER")
    if supplied:
        payer = Keypair.from_bytes(bytes(json.loads(pathlib.Path(supplied).read_text())))
        if (await rpc.get_balance(payer.pubkey())).value == 0:
            pytest.skip(f"payer {payer.pubkey()} has no lamports")
        return payer

    payer = Keypair()
    try:
        sig = (await rpc.request_airdrop(payer.pubkey(), PAYER_LAMPORTS)).value
        await rpc.confirm_transaction(sig, commitment=Confirmed)
    except Exception as exc:  # noqa: BLE001 - faucet failure is a skip, not a bug
        pytest.skip(f"airdrop unavailable ({exc}); set TAPFARM_E2E_PAYER to a funded key")
    return payer


def _parse_credential(raw: bytes) -> dict:
    """Mirror of `Credential::try_from_bytes`, after the discriminator byte.

    Layout: authority(32) | name_len(u32) | name | signers_len(u32) | 32*n
    """
    offset = 1  # account discriminator
    authority = Pubkey(raw[offset : offset + 32])
    offset += 32
    name_len = int.from_bytes(raw[offset : offset + 4], "little")
    offset += 4
    name = raw[offset : offset + name_len].decode("utf-8")
    offset += name_len
    count = int.from_bytes(raw[offset : offset + 4], "little")
    offset += 4
    signers = [
        Pubkey(raw[offset + i * 32 : offset + (i + 1) * 32]) for i in range(count)
    ]
    return {"authority": authority, "name": name, "signers": signers}


async def test_create_credential_is_accepted_by_the_deployed_program():
    """The instruction we build is executable, not merely well-formed."""
    async with AsyncClient(_rpc_url(), commitment=Confirmed) as rpc:
        info = (await rpc.get_account_info(SAS_PROGRAM_ID)).value
        if info is None or not info.executable:
            pytest.skip(
                f"SAS program {SAS_PROGRAM_ID} is not on {_rpc_url()}; clone it with "
                "--clone 22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG --url devnet"
            )

        payer = await _funded_payer(rpc)
        verifier = Keypair().pubkey()
        # Unique per run: a credential PDA init's once and the account persists.
        name = f"union-e2e-{secrets.token_hex(4)}"

        ix = create_credential_ix(
            payer=payer.pubkey(),
            authority=payer.pubkey(),
            name=name,
            authorized_signers=[verifier],
        )
        blockhash = (await rpc.get_latest_blockhash()).value.blockhash
        tx = Transaction(
            [payer], Message.new_with_blockhash([ix], payer.pubkey(), blockhash), blockhash
        )
        sig = (await rpc.send_raw_transaction(bytes(tx))).value
        await rpc.confirm_transaction(sig, commitment=Confirmed)

        credential, _ = derive_credential(payer.pubkey(), name)
        account = (await rpc.get_account_info(credential)).value
        assert account is not None, "credential PDA was not created"
        assert Pubkey.from_bytes(bytes(account.owner)) == SAS_PROGRAM_ID

        stored = _parse_credential(bytes(account.data))
        assert stored["authority"] == payer.pubkey()
        assert stored["name"] == name
        assert stored["signers"] == [verifier], (
            "the deployed program stored a different signer set than we sent; "
            "the on-chain layout has diverged from the source sas.py was built from"
        )
