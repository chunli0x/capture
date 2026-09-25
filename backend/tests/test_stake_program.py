"""On-chain lifecycle tests for the tapfarm-stake program.

Pure decision logic is unit tested in Rust (`cargo test -p tapfarm-stake`).
These cover what those cannot: account constraints, PDA seeds, token CPIs and
signer checks against a real runtime.

The property worth the most attention here is that **slashing cannot reach the
SKR stake**. HUMAN is our bond and is collateral we may burn; SKR is Solana
Mobile's and is not ours to confiscate. The program has no asset parameter on
`slash` at all, so this is structural rather than a matter of calling it
carefully - and the tests below try to break it anyway.

Requires a validator with the program deployed:

    solana-test-validator --reset --quiet &
    CLUSTER=localhost ./scripts/bootstrap_devnet.sh
    ./scripts/deploy_stake_program.sh

    cd backend && TAPFARM_E2E=1 TAPFARM_STAKE_PROGRAM=<program id> \
      TAPFARM_HUMAN_MINT=<tap mint> TAPFARM_SKR_MINT=<access mint> pytest -q
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
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    create_idempotent_associated_token_account,
    get_associated_token_address,
    transfer_checked,
)
from spl.token.models import TransferCheckedParams

from tapfarm.stake_client import (
    Asset,
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
MIN_HUMAN = 100_000        # 0.1 HUMAN
MIN_SKR = 1_000_000      # 1 SKR
COOLDOWN_SECONDS = 2     # short enough to wait out in a test
FUNDING = 10_000_000     # 10 tokens of each, per contributor
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
def human_mint() -> Pubkey:
    return Pubkey.from_string(_require_env("TAPFARM_HUMAN_MINT"))


@pytest.fixture(scope="module")
def skr_mint() -> Pubkey:
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
    return int((await rpc.get_token_account_balance(account, commitment=Confirmed)).value.amount)


async def _config(rpc: AsyncClient, program_id: Pubkey):
    account = (await rpc.get_account_info(config_pda(program_id)[0], commitment=Confirmed)).value
    return parse_config(bytes(account.data))


async def _stake_account(rpc: AsyncClient, program_id: Pubkey, contributor: Pubkey):
    pda, _ = stake_pda(program_id, contributor)
    account = (await rpc.get_account_info(pda, commitment=Confirmed)).value
    return parse_stake_account(bytes(account.data))


async def _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint):
    """Config is a singleton PDA, so initialize is idempotent by necessity."""
    if (await rpc.get_account_info(config_pda(program_id)[0], commitment=Confirmed)).value:
        return
    await _send(
        rpc,
        [
            build_initialize(
                program_id=program_id,
                admin=treasury.pubkey(),
                human_mint=human_mint,
                skr_mint=skr_mint,
                min_human_stake=MIN_HUMAN,
                min_skr_stake=MIN_SKR,
                cooldown_seconds=COOLDOWN_SECONDS,
                slash_authority=treasury.pubkey(),
            )
        ],
        treasury,
    )


async def _fund(rpc, treasury, contributor: Keypair, mint: Pubkey) -> Pubkey:
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
                    amount=FUNDING,
                    decimals=DECIMALS,
                )
            ),
        ],
        treasury,
    )
    return ata


async def _new_contributor(rpc, treasury, human_mint, skr_mint):
    contributor = Keypair()
    airdrop = await rpc.request_airdrop(contributor.pubkey(), 1_000_000_000)
    await rpc.confirm_transaction(airdrop.value, commitment=Confirmed)
    human_ata = await _fund(rpc, treasury, contributor, human_mint)
    skr_ata = await _fund(rpc, treasury, contributor, skr_mint)
    return contributor, human_ata, skr_ata


async def _stake(rpc, program_id, contributor, ata, mint, asset, amount):
    await _send(
        rpc,
        [
            build_stake(
                program_id=program_id,
                contributor=contributor.pubkey(),
                contributor_tokens=ata,
                mint=mint,
                asset=asset,
                amount=amount,
            )
        ],
        contributor,
    )


# -- staking ------------------------------------------------------------------

async def test_tap_and_skr_go_to_separate_vaults(program_id, human_mint, skr_mint, treasury):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)

        human_vault, _ = vault_pda(program_id, human_mint)
        skr_vault, _ = vault_pda(program_id, skr_mint)
        assert human_vault != skr_vault
        human_before = await _token_balance(rpc, human_vault)
        skr_before = await _token_balance(rpc, skr_vault)

        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN * 2)
        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR)

        assert await _token_balance(rpc, human_vault) == human_before + MIN_HUMAN * 2
        assert await _token_balance(rpc, skr_vault) == skr_before + MIN_SKR

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.amount == MIN_HUMAN * 2
        assert account.skr.amount == MIN_SKR
        assert account.tier(MIN_HUMAN) == 1
        assert account.referral_eligible(MIN_HUMAN, MIN_SKR)


async def test_staking_the_wrong_mint_for_an_asset_is_rejected(
    program_id, human_mint, skr_mint, treasury
):
    """Asset and mint must agree, or the vaults could be crossed."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, _ = await _new_contributor(rpc, treasury, human_mint, skr_mint)

        with pytest.raises(Exception):
            await _stake(
                rpc, program_id, contributor, human_ata, human_mint, Asset.SKR, MIN_HUMAN
            )


async def test_skr_alone_does_not_unlock_the_work_tier(
    program_id, human_mint, skr_mint, treasury
):
    """Holding SKR says nothing about label quality."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, _, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)

        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR * 5)

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.tier(MIN_HUMAN) == 0
        assert not account.referral_eligible(MIN_HUMAN, MIN_SKR)


async def test_referral_needs_the_slashable_bond_too(
    program_id, human_mint, skr_mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)

        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN - 1)
        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert not account.referral_eligible(MIN_HUMAN, MIN_SKR)

        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, 1)
        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.referral_eligible(MIN_HUMAN, MIN_SKR)


# -- slashing -----------------------------------------------------------------

async def test_slashing_never_touches_the_skr_stake(
    program_id, human_mint, skr_mint, treasury
):
    """The core guarantee of the two-token split.

    SKR is not ours to confiscate, so even a maximal slash by the real
    authority must leave the SKR position and vault untouched.
    """
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)

        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN * 4)
        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR * 3)

        skr_vault, _ = vault_pda(program_id, skr_mint)
        skr_vault_before = await _token_balance(rpc, skr_vault)

        await _send(
            rpc,
            [
                build_slash(
                    program_id=program_id,
                    slash_authority=treasury.pubkey(),
                    contributor=contributor.pubkey(),
                    amount=MIN_HUMAN * 1_000,  # far more than the HUMAN bond
                )
            ],
            treasury,
        )

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.amount == 0, "HUMAN bond should be fully burned"
        assert account.skr.amount == MIN_SKR * 3, "SKR must survive untouched"
        assert await _token_balance(rpc, skr_vault) == skr_vault_before


async def test_only_the_slash_authority_can_slash(program_id, human_mint, skr_mint, treasury):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, _ = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN)

        impostor = Keypair()
        airdrop = await rpc.request_airdrop(impostor.pubkey(), 1_000_000_000)
        await rpc.confirm_transaction(airdrop.value, commitment=Confirmed)

        for signer in (impostor, contributor):
            with pytest.raises(Exception):
                await _send(
                    rpc,
                    [
                        build_slash(
                            program_id=program_id,
                            slash_authority=signer.pubkey(),
                            contributor=contributor.pubkey(),
                            amount=MIN_HUMAN,
                        )
                    ],
                    signer,
                )


async def test_slash_credits_the_reward_pool(program_id, human_mint, skr_mint, treasury):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, _ = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN * 4)

        before = await _config(rpc, program_id)
        await _send(
            rpc,
            [
                build_slash(
                    program_id=program_id,
                    slash_authority=treasury.pubkey(),
                    contributor=contributor.pubkey(),
                    amount=MIN_HUMAN,
                )
            ],
            treasury,
        )
        after = await _config(rpc, program_id)

        assert after.slashed_pool == before.slashed_pool + MIN_HUMAN
        assert after.total_human_staked == before.total_human_staked - MIN_HUMAN
        assert after.total_skr_staked == before.total_skr_staked

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.amount == MIN_HUMAN * 3


# -- unstaking ----------------------------------------------------------------

async def test_withdraw_requires_a_request_and_respects_the_cooldown(
    program_id, human_mint, skr_mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, _ = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN * 2)

        withdraw = build_withdraw(
            program_id=program_id,
            contributor=contributor.pubkey(),
            contributor_tokens=human_ata,
            mint=human_mint,
            asset=Asset.HUMAN,
        )

        with pytest.raises(Exception):  # no request yet
            await _send(rpc, [withdraw], contributor)

        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    asset=Asset.HUMAN,
                    amount=MIN_HUMAN * 2,
                )
            ],
            contributor,
        )

        # Requesting must NOT reduce the bond - that is what keeps it slashable
        # during the cooldown.
        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.amount == MIN_HUMAN * 2
        assert account.human.unstake_amount == MIN_HUMAN * 2
        assert account.human.unstake_requested_at > 0

        with pytest.raises(Exception):  # cooldown still active
            await _send(rpc, [withdraw], contributor)

        time.sleep(COOLDOWN_SECONDS + 1)

        before = await _token_balance(rpc, human_ata)
        await _send(rpc, [withdraw], contributor)
        assert await _token_balance(rpc, human_ata) == before + MIN_HUMAN * 2

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.amount == 0
        assert account.human.unstake_requested_at == 0


async def test_a_slash_during_cooldown_reduces_the_payout(
    program_id, human_mint, skr_mint, treasury
):
    """The security property the cooldown exists for."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, _ = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN * 4)

        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    asset=Asset.HUMAN,
                    amount=MIN_HUMAN * 4,
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
                    amount=MIN_HUMAN * 3,
                )
            ],
            treasury,
        )

        time.sleep(COOLDOWN_SECONDS + 1)

        before = await _token_balance(rpc, human_ata)
        await _send(
            rpc,
            [
                build_withdraw(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=human_ata,
                    mint=human_mint,
                    asset=Asset.HUMAN,
                )
            ],
            contributor,
        )
        # Requested 4x, but only 1x survived the slash.
        assert await _token_balance(rpc, human_ata) == before + MIN_HUMAN


async def test_skr_can_be_withdrawn_after_cooldown(program_id, human_mint, skr_mint, treasury):
    """SKR is a commitment, not a lock-in: it comes back out."""
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, _, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR * 2)

        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    asset=Asset.SKR,
                    amount=MIN_SKR * 2,
                )
            ],
            contributor,
        )
        time.sleep(COOLDOWN_SECONDS + 1)

        before = await _token_balance(rpc, skr_ata)
        await _send(
            rpc,
            [
                build_withdraw(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    contributor_tokens=skr_ata,
                    mint=skr_mint,
                    asset=Asset.SKR,
                )
            ],
            contributor,
        )
        assert await _token_balance(rpc, skr_ata) == before + MIN_SKR * 2


async def test_unstaking_one_asset_leaves_the_other_pending_state_alone(
    program_id, human_mint, skr_mint, treasury
):
    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:
        await _ensure_initialized(rpc, program_id, treasury, human_mint, skr_mint)
        contributor, human_ata, skr_ata = await _new_contributor(rpc, treasury, human_mint, skr_mint)
        await _stake(rpc, program_id, contributor, human_ata, human_mint, Asset.HUMAN, MIN_HUMAN)
        await _stake(rpc, program_id, contributor, skr_ata, skr_mint, Asset.SKR, MIN_SKR)

        await _send(
            rpc,
            [
                build_request_unstake(
                    program_id=program_id,
                    contributor=contributor.pubkey(),
                    asset=Asset.HUMAN,
                    amount=MIN_HUMAN,
                )
            ],
            contributor,
        )

        account = await _stake_account(rpc, program_id, contributor.pubkey())
        assert account.human.unstake_requested_at > 0
        assert account.skr.unstake_requested_at == 0
        assert account.skr.unstake_amount == 0
