"""Instruction builder for the `union-bond` program.

Mirrors `stake_client.py`: Anchor's wire format is an eight-byte discriminator
(`sha256("global:<name>")[:8]`) followed by borsh-encoded arguments, and the
account order is the field order of the instruction's `Accounts` struct. Both
are read out of `programs/union-bond/src/lib.rs` rather than inferred, and the
tests re-derive them independently.

## The shape of an attestation mint

One transaction carries two instructions:

1. `post_bond` here, escrowing HUMAN and creating the bond PDA.
2. SAS `create_attestation`, with its `nonce` set to that same bond PDA.

Doing both in one transaction is what keeps the credential and the bond
inseparable. Split across two, a crash between them leaves either a credential
with no stake behind it - the exact claim Union says it does not make - or a
stake with no credential to point at.

The human is the fee payer, as in `claim_tx.py`. That is not a cost-shifting
decision: it makes the wallet signature cryptographically load-bearing rather
than a formality, because the transaction cannot land without it.
"""

from __future__ import annotations

import enum
import hashlib
import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID

CONFIG_SEED = b"config"
BOND_SEED = b"bond"
VAULT_SEED = b"vault"
LIVENESS_SEED = b"liveness"

# Must match `MAX_TASK_ID_LEN` in the program. A PDA seed cannot exceed 32
# bytes, so a longer id would fail in the runtime with an opaque error.
MAX_TASK_ID_LEN = 32

SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")


def instruction_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def derive_config(program_id: Pubkey, human_mint: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([CONFIG_SEED, bytes(human_mint)], program_id)


def derive_vault(program_id: Pubkey, human_mint: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([VAULT_SEED, bytes(human_mint)], program_id)


def derive_bond(
    program_id: Pubkey, human: Pubkey, task_id: str
) -> tuple[Pubkey, int]:
    """`["bond", human, task_id]`.

    Both the human and the task are in the seeds, so one contributor cannot
    collide with another's bond and cannot post two bonds for the same task -
    the second `init` fails against an account that already exists.

    This address is also what we hand SAS as its attestation `nonce`, which is
    how the credential and the bond name each other.
    """
    _require_task_id(task_id)
    return Pubkey.find_program_address(
        [BOND_SEED, bytes(human), task_id.encode("utf-8")], program_id
    )


def derive_liveness_receipt(
    program_id: Pubkey, liveness_proof_hash: bytes
) -> tuple[Pubkey, int]:
    """`["liveness", hash]` - the replay guard.

    Nothing reads this account. It exists so that a second `post_bond` with a
    hash already spent collides at account creation, which is a guarantee the
    runtime enforces rather than one our code has to remember to check.
    """
    _require_hash(liveness_proof_hash)
    return Pubkey.find_program_address(
        [LIVENESS_SEED, liveness_proof_hash], program_id
    )


def _require_task_id(task_id: str) -> None:
    encoded = task_id.encode("utf-8")
    if not encoded:
        raise ValueError("task_id must not be empty")
    if len(encoded) > MAX_TASK_ID_LEN:
        raise ValueError(
            f"task_id is {len(encoded)} bytes, over the {MAX_TASK_ID_LEN}-byte "
            "PDA seed limit (measured in bytes, not characters)"
        )


def _require_hash(value: bytes) -> None:
    if len(value) != 32:
        raise ValueError(f"liveness proof hash must be 32 bytes, got {len(value)}")
    if value == bytes(32):
        raise ValueError("liveness proof hash must not be all zeroes")


def post_bond_ix(
    *,
    program_id: Pubkey,
    payer: Pubkey,
    human: Pubkey,
    verifier: Pubkey,
    human_mint: Pubkey,
    human_tokens: Pubkey,
    task_id: str,
    liveness_proof_hash: bytes,
    amount: int,
) -> Instruction:
    """Escrow a bond behind one attestation. Human and verifier both sign."""
    if amount <= 0:
        raise ValueError("bond amount must be positive")
    _require_task_id(task_id)
    _require_hash(liveness_proof_hash)

    config, _ = derive_config(program_id, human_mint)
    vault, _ = derive_vault(program_id, human_mint)
    bond, _ = derive_bond(program_id, human, task_id)
    receipt, _ = derive_liveness_receipt(program_id, liveness_proof_hash)

    encoded_task = task_id.encode("utf-8")
    data = (
        instruction_discriminator("post_bond")
        + struct.pack("<I", len(encoded_task))
        + encoded_task
        + liveness_proof_hash
        + struct.pack("<Q", amount)
    )

    return Instruction(
        program_id=program_id,
        accounts=[
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(human, is_signer=True, is_writable=False),
            AccountMeta(verifier, is_signer=True, is_writable=False),
            AccountMeta(config, is_signer=False, is_writable=True),
            AccountMeta(bond, is_signer=False, is_writable=True),
            AccountMeta(receipt, is_signer=False, is_writable=True),
            AccountMeta(vault, is_signer=False, is_writable=True),
            AccountMeta(human_tokens, is_signer=False, is_writable=True),
            AccountMeta(human_mint, is_signer=False, is_writable=False),
            AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(RENT_SYSVAR_ID, is_signer=False, is_writable=False),
        ],
        data=data,
    )


# --- reading a bond back ----------------------------------------------------


class BondStatus(enum.IntEnum):
    """Mirrors the program's `BondStatus`. Borsh encodes an enum as its index."""

    ATTESTED = 0
    CHALLENGED = 1
    SLASHED = 2
    RELEASED = 3

    @property
    def label(self) -> str:
        return self.name.capitalize()


@dataclass(frozen=True)
class BondRecord:
    """A bond as stored on-chain."""

    human: Pubkey
    task_id: str
    liveness_proof_hash: bytes
    amount: int
    status: BondStatus
    evidence_hash: bytes
    attested_at: int
    verifier: Pubkey

    @property
    def challenged(self) -> bool:
        return self.status is BondStatus.CHALLENGED


def decode_bond(data: bytes) -> BondRecord:
    """Decode a `Bond` account.

    Hand-decoded for the same reason the instructions are hand-encoded: there
    is no Python Anchor client here. The field order is the struct's
    declaration order, which is what borsh follows.

    Strict about trailing bytes. Anchor allocates `INIT_SPACE` and a `String`
    field is allocated at its maximum, so a short task_id leaves slack - the
    check below accounts for that rather than demanding an exact length, but
    still refuses anything that ends early.
    """
    if len(data) < 8:
        raise ValueError("account data is too short to hold a discriminator")

    offset = 8  # account discriminator
    human = Pubkey(data[offset : offset + 32])
    offset += 32

    task_len = int.from_bytes(data[offset : offset + 4], "little")
    offset += 4
    if task_len > MAX_TASK_ID_LEN:
        raise ValueError(f"task_id claims {task_len} bytes, over the seed limit")
    task_id = data[offset : offset + task_len].decode("utf-8")
    offset += task_len

    liveness_proof_hash = bytes(data[offset : offset + 32])
    offset += 32
    amount = int.from_bytes(data[offset : offset + 8], "little")
    offset += 8

    raw_status = data[offset]
    offset += 1
    try:
        status = BondStatus(raw_status)
    except ValueError as exc:
        raise ValueError(
            f"unknown bond status {raw_status}; this client is older than the "
            "deployed program"
        ) from exc

    evidence_hash = bytes(data[offset : offset + 32])
    offset += 32
    attested_at = int.from_bytes(data[offset : offset + 8], "little", signed=True)
    offset += 8
    verifier = Pubkey(data[offset : offset + 32])
    offset += 32

    if offset > len(data):
        raise ValueError("account data ended before the record did")

    return BondRecord(
        human=human,
        task_id=task_id,
        liveness_proof_hash=liveness_proof_hash,
        amount=amount,
        status=status,
        evidence_hash=evidence_hash,
        attested_at=attested_at,
        verifier=verifier,
    )
