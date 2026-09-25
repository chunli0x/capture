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

from enum import IntEnum

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.sysvar import RENT
from spl.token.constants import TOKEN_PROGRAM_ID

SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

CONFIG_SEED = b"config"
STAKE_SEED = b"stake"
VAULT_SEED = b"vault"

ACCOUNT_DISCRIMINATOR_LEN = 8


class Asset(IntEnum):
    """Mirrors the program's `Asset` enum; borsh encodes it as one byte.

    TAP is the slashable bond, SKR the non-slashable access stake.
    """

    TAP = 0
    SKR = 1


def instruction_discriminator(name: str) -> bytes:
    """Anchor's instruction discriminator: first 8 bytes of sha256("global:name")."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:ACCOUNT_DISCRIMINATOR_LEN]


def config_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([CONFIG_SEED], program_id)


def vault_pda(program_id: Pubkey, mint: Pubkey) -> tuple[Pubkey, int]:
    """Vaults are per-mint, so TAP and SKR are held in separate accounts."""
    return Pubkey.find_program_address([VAULT_SEED, bytes(mint)], program_id)


def stake_pda(program_id: Pubkey, contributor: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([STAKE_SEED, bytes(contributor)], program_id)


def build_initialize(
    *,
    program_id: Pubkey,
    admin: Pubkey,
    tap_mint: Pubkey,
    skr_mint: Pubkey,
    min_tap_stake: int,
    min_skr_stake: int,
    cooldown_seconds: int,
    slash_authority: Pubkey,
) -> Instruction:
    """Mirrors `Initialize`. Creates both vaults."""
    data = (
        instruction_discriminator("initialize")
        + struct.pack("<Q", min_tap_stake)
        + struct.pack("<Q", min_skr_stake)
        + struct.pack("<q", cooldown_seconds)
        + bytes(slash_authority)
    )
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(admin, is_signer=True, is_writable=True),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(vault_pda(program_id, tap_mint)[0], is_signer=False, is_writable=True),
            AccountMeta(vault_pda(program_id, skr_mint)[0], is_signer=False, is_writable=True),
            AccountMeta(tap_mint, is_signer=False, is_writable=False),
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
    mint: Pubkey,
    asset: Asset,
    amount: int,
) -> Instruction:
    """Mirrors `Stake`. The contributor signs, so staking is user-authorized."""
    data = (
        instruction_discriminator("stake")
        + bytes([int(asset)])
        + struct.pack("<Q", amount)
    )
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[
            AccountMeta(contributor, is_signer=True, is_writable=True),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
            AccountMeta(vault_pda(program_id, mint)[0], is_signer=False, is_writable=True),
            AccountMeta(contributor_tokens, is_signer=False, is_writable=True),
            AccountMeta(mint, is_signer=False, is_writable=False),
            AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
    )


def build_request_unstake(
    *, program_id: Pubkey, contributor: Pubkey, asset: Asset, amount: int
) -> Instruction:
    """Mirrors `ModifyStake`."""
    data = (
        instruction_discriminator("request_unstake")
        + bytes([int(asset)])
        + struct.pack("<Q", amount)
    )
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
    mint: Pubkey,
    asset: Asset,
) -> Instruction:
    """Mirrors `Withdraw`."""
    return Instruction(
        program_id=program_id,
        data=instruction_discriminator("withdraw") + bytes([int(asset)]),
        accounts=[
            AccountMeta(contributor, is_signer=True, is_writable=False),
            AccountMeta(config_pda(program_id)[0], is_signer=False, is_writable=True),
            AccountMeta(
                stake_pda(program_id, contributor)[0], is_signer=False, is_writable=True
            ),
            AccountMeta(vault_pda(program_id, mint)[0], is_signer=False, is_writable=True),
            AccountMeta(contributor_tokens, is_signer=False, is_writable=True),
            AccountMeta(mint, is_signer=False, is_writable=False),
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
    """Mirrors `Slash`. Only the configured slash authority may sign this.

    There is no asset parameter: the program only ever slashes TAP. SKR is not
    ours to confiscate, and leaving it off the interface makes that structural.
    """
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
    tap_mint: Pubkey
    skr_mint: Pubkey
    min_tap_stake: int
    min_skr_stake: int
    cooldown_seconds: int
    total_tap_staked: int
    total_skr_staked: int
    slashed_pool: int
    bump: int


@dataclass(frozen=True)
class Position:
    amount: int
    unstake_amount: int
    unstake_requested_at: int


@dataclass(frozen=True)
class StakeAccount:
    contributor: Pubkey
    tap: Position
    skr: Position
    staked_at: int
    bump: int

    def position(self, asset: Asset) -> Position:
        return self.tap if asset is Asset.TAP else self.skr

    def tier(self, min_tap_stake: int) -> int:
        """Mirrors `logic::tier_for`. Keyed on the slashable bond only."""
        return 1 if min_tap_stake > 0 and self.tap.amount >= min_tap_stake else 0

    def referral_eligible(self, min_tap_stake: int, min_skr_stake: int) -> bool:
        """Mirrors `logic::referral_eligible`. Requires both stakes."""
        return (
            self.tier(min_tap_stake) == 1
            and min_skr_stake > 0
            and self.skr.amount >= min_skr_stake
        )


# Borsh layouts. Field order must track the program's account structs exactly;
# a mismatch here decodes as plausible-looking nonsense rather than an error.
_CONFIG_LAYOUT = "<QQqQQQ"  # after four pubkeys
_POSITION_LAYOUT = "<QQq"
_POSITION_SIZE = struct.calcsize(_POSITION_LAYOUT)


def parse_config(data: bytes) -> Config:
    body = data[ACCOUNT_DISCRIMINATOR_LEN:]
    admin = Pubkey.from_bytes(body[0:32])
    slash_authority = Pubkey.from_bytes(body[32:64])
    tap_mint = Pubkey.from_bytes(body[64:96])
    skr_mint = Pubkey.from_bytes(body[96:128])
    (
        min_tap_stake,
        min_skr_stake,
        cooldown_seconds,
        total_tap_staked,
        total_skr_staked,
        slashed_pool,
    ) = struct.unpack_from(_CONFIG_LAYOUT, body, 128)
    return Config(
        admin=admin,
        slash_authority=slash_authority,
        tap_mint=tap_mint,
        skr_mint=skr_mint,
        min_tap_stake=min_tap_stake,
        min_skr_stake=min_skr_stake,
        cooldown_seconds=cooldown_seconds,
        total_tap_staked=total_tap_staked,
        total_skr_staked=total_skr_staked,
        slashed_pool=slashed_pool,
        bump=body[128 + struct.calcsize(_CONFIG_LAYOUT)],
    )


def _parse_position(body: bytes, offset: int) -> Position:
    amount, unstake_amount, requested_at = struct.unpack_from(
        _POSITION_LAYOUT, body, offset
    )
    return Position(
        amount=amount,
        unstake_amount=unstake_amount,
        unstake_requested_at=requested_at,
    )


def parse_stake_account(data: bytes) -> StakeAccount:
    body = data[ACCOUNT_DISCRIMINATOR_LEN:]
    contributor = Pubkey.from_bytes(body[0:32])
    tap = _parse_position(body, 32)
    skr = _parse_position(body, 32 + _POSITION_SIZE)
    tail = 32 + 2 * _POSITION_SIZE
    (staked_at,) = struct.unpack_from("<q", body, tail)
    return StakeAccount(
        contributor=contributor,
        tap=tap,
        skr=skr,
        staked_at=staked_at,
        bump=body[tail + 8],
    )
