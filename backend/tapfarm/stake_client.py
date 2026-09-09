"""Client for the tapfarm-stake program.

Instructions are encoded by hand rather than through an IDL client. The backend
needs exactly five of them, and Anchor's wire format is simple enough that
hand-encoding avoids a dependency whose version has to track the program's:

    data = sha256(b"global:<instruction_name>")[:8] + borsh(args)

Account metas must appear in the same order as the fields of the corresponding
`#[derive(Accounts)]` struct, so each builder below mirrors one struct and says
which.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.sysvar import RENT
from spl.token.constants import TOKEN_PROGRAM_ID

SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

CONFIG_SEED = b"config"
STAKE_SEED = b"stake"
VAULT_SEED = b"vault"

ACCOUNT_DISCRIMINATOR_LEN = 8


def instruction_discriminator(name: str) -> bytes:
    """Anchor's instruction discriminator: first 8 bytes of sha256("global:name")."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:ACCOUNT_DISCRIMINATOR_LEN]


def config_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([CONFIG_SEED], program_id)


def vault_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([VAULT_SEED], program_id)


def stake_pda(program_id: Pubkey, contributor: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([STAKE_SEED, bytes(contributor)], program_id)


def build_initialize(
    *,
    program_id: Pubkey,
    admin: Pubkey,
    skr_mint: Pubkey,
    min_stake: int,
    cooldown_seconds: int,
    slash_authority: Pubkey,
) -> Instruction:
    """Mirrors `Initialize`."""
    data = (
        instruction_discriminator("initialize")
        + struct.pack("<Q", min_stake)
        + struct.pack("<q", cooldown_seconds)
        + bytes(slash_authority)
    )
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(admin, is_signer=True, is_writable=True),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(vault_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(skr_mint, is_signer=False, is_writable=False),
            AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(RENT, is_signer=False, is_writable=False),
        ],
    )


def build_stake(
    *,
    program_id: Pubkey,
    contributor: Pubkey,
    contributor_tokens: Pubkey,
    skr_mint: Pubkey,
    amount: int,
) -> Instruction:
    """Mirrors `Stake`. The contributor signs, so staking is user-authorized."""
    data = instruction_discriminator("stake") + struct.pack("<Q", amount)
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(contributor, is_signer=True, is_writable=True),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
            AccountMeta(vault_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(contributor_tokens, is_signer=False, is_writable=True),
            AccountMeta(skr_mint, is_signer=False, is_writable=False),
            AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
    )


def build_request_unstake(
    *, program_id: Pubkey, contributor: Pubkey, amount: int
) -> Instruction:
    """Mirrors `ModifyStake`."""
    data = instruction_discriminator("request_unstake") + struct.pack("<Q", amount)
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(contributor, is_signer=True, is_writable=False),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=False),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
        ],
    )


def build_withdraw(
    *,
    program_id: Pubkey,
    contributor: Pubkey,
    contributor_tokens: Pubkey,
    skr_mint: Pubkey,
) -> Instruction:
    """Mirrors `Withdraw`."""
    return Instruction(
        program_id=program_id,
        data=instruction_discriminator("withdraw"),
        accounts=[
            AccountMeta(contributor, is_signer=True, is_writable=False),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
            AccountMeta(vault_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(contributor_tokens, is_signer=False, is_writable=True),
            AccountMeta(skr_mint, is_signer=False, is_writable=False),
            AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
    )


def build_slash(
    *,
    program_id: Pubkey,
    slash_authority: Pubkey,
    contributor: Pubkey,
    amount: int,
) -> Instruction:
    """Mirrors `Slash`. Only the configured slash authority may sign this."""
    data = instruction_discriminator("slash") + struct.pack("<Q", amount)
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(slash_authority, is_signer=True, is_writable=False),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
        ],
    )


@dataclass(frozen=True)
class Config:
    admin: Pubkey
    slash_authority: Pubkey
    skr_mint: Pubkey
    min_stake: int
    cooldown_seconds: int
    total_staked: int
    slashed_pool: int
    bump: int


@dataclass(frozen=True)
class StakeAccount:
    contributor: Pubkey
    amount: int
    staked_at: int
    unstake_requested_at: int
    unstake_amount: int
    bump: int

    def tier(self, min_stake: int) -> int:
        """Mirrors `logic::tier_for` in the program."""
        return 1 if min_stake > 0 and self.amount >= min_stake else 0


def parse_config(data: bytes) -> Config:
    body = data[ACCOUNT_DISCRIMINATOR_LEN:]
    admin, slash_authority, skr_mint = (
        Pubkey.from_bytes(body[0:32]),
        Pubkey.from_bytes(body[32:64]),
        Pubkey.from_bytes(body[64:96]),
    )
    min_stake, cooldown, total_staked, slashed_pool = struct.unpack_from(
        "<QqQQ", body, 96
    )
    return Config(
        admin=admin,
        slash_authority=slash_authority,
        skr_mint=skr_mint,
        min_stake=min_stake,
        cooldown_seconds=cooldown,
        total_staked=total_staked,
        slashed_pool=slashed_pool,
        bump=body[128],
    )


def parse_stake_account(data: bytes) -> StakeAccount:
    body = data[ACCOUNT_DISCRIMINATOR_LEN:]
    contributor = Pubkey.from_bytes(body[0:32])
    amount, staked_at, requested_at, unstake_amount = struct.unpack_from(
        "<QqqQ", body, 32
    )
    return StakeAccount(
        contributor=contributor,
        amount=amount,
        staked_at=staked_at,
        unstake_requested_at=requested_at,
        unstake_amount=unstake_amount,
        bump=body[64],
    )
