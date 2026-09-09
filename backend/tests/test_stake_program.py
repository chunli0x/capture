"""On-chain lifecycle tests for the tapfarm-stake program.

The pure decision logic is unit tested in Rust (`cargo test -p tapfarm-stake`).
These tests cover what those cannot: that the account constraints, PDA seeds,
token CPIs and signer checks behave against a real runtime.

Requires a validator with the program deployed:

    solana-test-validator --reset --quiet &
    CLUSTER=localhost ./scripts/bootstrap_devnet.sh
    cargo-build-sbf --arch v3     # v3 is the only deployable target: SIMD-0500
                                  # disables v0/v1/v2 deployment
    solana -C backend/.solana-cli.yml program deploy \
      --program-id programs/tapfarm-stake/program-keypair.json \
      target/deploy/tapfarm_stake.so

    cd backend && TAPFARM_E2E=1 TAPFARM_STAKE_PROGRAM=<program id> \
      TAPFARM_SKR_MINT=<mint> pytest tests/test_stake_program.py -v
"""

from __future__ import annotations

import json
import os
import pathlib
import time

import pytest
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from spl.token.instructions import (
    create_idempotent_associated_token_account,
    get_associated_token_address,
    transfer_checked,
)
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import TransferCheckedParams

from tapfarm.stake_client import (
    build_initialize,
    build_request_unstake,
    build_slash,
    build_stake,
    build_withdraw,
    config_pda,
    parse_config,
    parse_stake_account,
    stake_pda,
    vault_pda,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("TAPFARM_E2E") != "1",
        reason="set TAPFARM_E2E=1 with the program deployed to a validator",
    ),
    pytest.mark.asyncio,
]

DECIMALS = 6
MIN_STAKE = 50_000          # 0.05 SKR
COOLDOWN_SECONDS = 2        # short enough to wait out in a test
CONTRIBUTOR_SKR = 1_000_000  # 1 SKR
RPC_URL = os.environ.get("TAPFARM_RPC_URL", "http://localhost:8899")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set")
    return value


@pytest.fixture(scope="module")
def program_id() -> Pubkey:
    return Pubkey.from_string(_require_env("TAPFARM_STAKE_PROGRAM"))


@pytest.fixture(scope="module")
def mint() -> Pubkey:
    return Pubkey.from_string(_require_env("TAPFARM_SKR_MINT"))


@pytest.fixture(scope="module")
def treasury() -> Keypair:
    path = pathlib.Path(__file__).parent.parent / "treasury.json"
    if not path.exists():
        pytest.skip("run scripts/bootstrap_devnet.sh")
    return Keypair.from_bytes(bytes(json.loads(path.read_text())))


async def _send(
    rpc: AsyncClient, instructions: list[Instruction], payer: Keypair, *signers: Keypair
):
    blockhash = (await rpc.get_latest_blockhash()).value.blockhash
    tx = Transaction.new_unsigned(
        Message.new_with_blockhash(instructions, payer.pubkey(), blockhash)
    )
    unique = {payer.pubkey(): payer}
    for signer in signers:
        unique[signer.pubkey()] = signer
    tx.partial_sign(list(unique.values()), blockhash)
    result = await rpc.send_raw_transaction(bytes(tx))
    await rpc.confirm_transaction(result.value, commitment=Confirmed)
    return result.value


async def _token_balance(rpc: AsyncClient, account: Pubkey) -> int:
    info = await rpc.get_account_info(account, commitment=Confirmed)
    if info.value is None:
        return 0
    balance = await rpc.get_token_account_balance(account, commitment=Confirmed)
    return int(balance.value.amount)


async def _ensure_initialized(
    rpc: AsyncClient, program_id: Pubkey, treasury: Keypair, mint: Pubkey
):
    """Config is a singleton PDA, so initialize is idempotent by necessity."""
    config, _ = config_pda(program_id)
    if (await rpc.get_account_info(config, commitment=Confirmed)).value is not None:
        return
    await _send(
        rpc,
        [
            build_initialize(
                program_id=program_id,
                admin=treasury.pubkey(),
                skr_mint=mint,
                min_stake=MIN_STAKE,
                cooldown_seconds=COOLDOWN_SECONDS,
                slash_authority=treasury.pubkey(),
            )
        ],
        treasury,
    )


async def _fund_contributor(
    rpc: AsyncClient, treasury: Keypair, mint: Pubkey
) -> tuple[Keypair, Pubkey]:
    contributor = Keypair()
    airdrop = await rpc.request_airdrop(contributor.pubkey(), 1_000_000_000)
    await rpc.confirm_transaction(airdrop.value, commitment=Confirmed)

    ata = get_associated_token_address(contributor.pubkey(), mint)
    await _send(
        rpc,
        [
            create_idempotent_associated_token_account(
                payer=treasury.pubkey(), owner=contributor.pubkey(), mint=mint
            ),
            transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=get_associated_token_address(treasury.pubkey(), mint),
                    mint=mint,
                    dest=ata,
                    owner=treasury.pubkey(),
                    amount=CONTRIBUTOR_SKR,
                    decimals=DECIMALS,
                )
            ),
        ],
        treasury,
    )
    return contributor, ata


async def test_stake_moves_tokens_into_the_vault_and_unlocks_the_tier(
    program_id, mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)

        vault, _ = vault_pda(program_id)
        vault_before = await _token_balance(rpc, vault)

        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE * 2,
                )
            ],
            contributor,
        )

        assert await _token_balance(rpc, vault) == vault_before + MIN_STAKE * 2
        assert await _token_balance(rpc, ata) == CONTRIBUTOR_SKR - MIN_STAKE * 2

        stake_pubkey, _ = stake_pda(program_id, contributor.pubkey())
        info = await rpc.get_account_info(stake_pubkey, commitment=Confirmed)
        account = parse_stake_account(bytes(info.value.data))
        assert account.contributor == contributor.pubkey()
        assert account.amount == MIN_STAKE * 2
        assert account.tier(MIN_STAKE) == 1


async def test_below_minimum_stake_stays_on_the_onboarding_tier(
    program_id, mint, treasury
):
    """Onboarding must work with no meaningful bond, or nobody can start."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)

        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE - 1,
                )
            ],
            contributor,
        )

        stake_pubkey, _ = stake_pda(program_id, contributor.pubkey())
        info = await rpc.get_account_info(stake_pubkey, commitment=Confirmed)
        assert parse_stake_account(bytes(info.value.data)).tier(MIN_STAKE) == 0


async def test_only_the_slash_authority_can_slash(program_id, mint, treasury):
    """The bond is worthless as a deterrent if anyone can burn it."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)
        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE,
                )
            ],
            contributor,
        )

        impostor = Keypair()
        airdrop = await rpc.request_airdrop(impostor.pubkey(), 1_000_000_000)
        await rpc.confirm_transaction(airdrop.value, commitment=Confirmed)

        with pytest.raises(Exception):
            await _send(
                rpc,
                [
                    build_slash(
                        program_id=program_id,
                        slash_authority=impostor.pubkey(),
                        contributor=contributor.pubkey(),
                        amount=MIN_STAKE,
                    )
                ],
                impostor,
            )

        # And the contributor cannot slash their own way out either.
        with pytest.raises(Exception):
            await _send(
                rpc,
                [
                    build_slash(
                        program_id=program_id,
                        slash_authority=contributor.pubkey(),
                        contributor=contributor.pubkey(),
                        amount=MIN_STAKE,
                    )
                ],
                contributor,
            )


async def test_slash_reduces_the_bond_and_credits_the_reward_pool(
    program_id, mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)
        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE * 4,
                )
            ],
            contributor,
        )

        config, _ = config_pda(program_id)
        before = parse_config(
            bytes((await rpc.get_account_info(config, commitment=Confirmed)).value.data)
        )

        await _send(
            rpc,
            [
                build_slash(
                    program_id=program_id,
                    slash_authority=treasury.pubkey(),
                    contributor=contributor.pubkey(),
                    amount=MIN_STAKE,
                )
            ],
            treasury,
        )

        after = parse_config(
            bytes((await rpc.get_account_info(config, commitment=Confirmed)).value.data)
        )
        assert after.slashed_pool == before.slashed_pool + MIN_STAKE
        assert after.total_staked == before.total_staked - MIN_STAKE

        stake_pubkey, _ = stake_pda(program_id, contributor.pubkey())
        account = parse_stake_account(
            bytes((await rpc.get_account_info(stake_pubkey, commitment=Confirmed)).value.data)
        )
        assert account.amount == MIN_STAKE * 3


async def test_slash_is_capped_at_the_whole_bond(program_id, mint, treasury):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)
        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE,
                )
            ],
            contributor,
        )

        await _send(
            rpc,
            [
                build_slash(
                    program_id=program_id,
                    slash_authority=treasury.pubkey(),
                    contributor=contributor.pubkey(),
                    amount=MIN_STAKE * 100,
                )
            ],
            treasury,
        )

        stake_pubkey, _ = stake_pda(program_id, contributor.pubkey())
        account = parse_stake_account(
            bytes((await rpc.get_account_info(stake_pubkey, commitment=Confirmed)).value.data)
        )
        assert account.amount == 0


async def test_withdraw_requires_a_request_and_respects_the_cooldown(
    program_id, mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)
        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE * 2,
                )
            ],
            contributor,
        )

        withdraw = build_withdraw(
            program_id=program_id,
            contributor=contributor.pubkey(),
            contributor_tokens=ata,
            skr_mint=mint,
        )

        # No request yet.
        with pytest.raises(Exception):
            await _send(rpc, [withdraw], contributor)

        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    amount=MIN_STAKE * 2,
                )
            ],
            contributor,
        )

        # Requesting must NOT reduce the bond - that is what keeps it slashable
        # during the cooldown.
        stake_pubkey, _ = stake_pda(program_id, contributor.pubkey())
        account = parse_stake_account(
            bytes((await rpc.get_account_info(stake_pubkey, commitment=Confirmed)).value.data)
        )
        assert account.amount == MIN_STAKE * 2
        assert account.unstake_amount == MIN_STAKE * 2
        assert account.unstake_requested_at > 0

        # Cooldown still active.
        with pytest.raises(Exception):
            await _send(rpc, [withdraw], contributor)

        time.sleep(COOLDOWN_SECONDS + 1)

        before = await _token_balance(rpc, ata)
        await _send(rpc, [withdraw], contributor)
        assert await _token_balance(rpc, ata) == before + MIN_STAKE * 2

        account = parse_stake_account(
            bytes((await rpc.get_account_info(stake_pubkey, commitment=Confirmed)).value.data)
        )
        assert account.amount == 0
        assert account.unstake_requested_at == 0


async def test_a_slash_during_cooldown_reduces_the_payout(program_id, mint, treasury):
    """The security property the cooldown exists for.

    A contributor cannot submit garbage, request an exit, and walk away with the
    whole bond before their accuracy is scored.
    """
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, mint)
        contributor, ata = await _fund_contributor(rpc, treasury, mint)
        await _send(
            rpc,
            [
                build_stake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                    amount=MIN_STAKE * 4,
                )
            ],
            contributor,
        )
        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    amount=MIN_STAKE * 4,
                )
            ],
            contributor,
        )

        # Scored as a bad actor while exiting: three quarters burned.
        await _send(
            rpc,
            [
                build_slash(
                    program_id=program_id,
                    slash_authority=treasury.pubkey(),
                    contributor=contributor.pubkey(),
                    amount=MIN_STAKE * 3,
                )
            ],
            treasury,
        )

        time.sleep(COOLDOWN_SECONDS + 1)

        before = await _token_balance(rpc, ata)
        await _send(
            rpc,
            [
                build_withdraw(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=ata,
                    skr_mint=mint,
                )
            ],
            contributor,
        )
        # Requested 4x, but only 1x survived the slash.
        assert await _token_balance(rpc, ata) == before + MIN_STAKE
