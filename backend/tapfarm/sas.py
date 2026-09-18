"""A minimal client for the Solana Attestation Service.

SAS ships clients for Rust and TypeScript; this backend is Python, so the
instruction encoding is hand-built here the same way `claim_tx.py` hand-builds
SPL transfers. That is not as fragile as it sounds - the wire format is a
one-byte discriminator followed by length-prefixed fields - but it is code
written against a program we do not control, so every field below was read out
of the deployed program's source rather than inferred from documentation, and
the tests pin the layout by re-parsing exactly as the program does.

Union's split (see docs/ATTESTATION.md): SAS issues the credential, which is
verifier-signed because `create_attestation` refuses any signer that is not on
the credential's `authorized_signers` list. Our own program holds the HUMAN
bond, the status, and the slash path, none of which SAS has. The two records
join through the attestation's `nonce`, which we set to our bond PDA.

Deliberately not covered here: the tokenized variant (discriminator 10) needs
Token-2022 mint and ATA accounts and belongs with the code that actually mints
the credential; and `close_attestation` (7), which is revocation and should not
be a one-liner anyone can call by accident.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

# Verified executable on devnet and mainnet-beta.
SAS_PROGRAM_ID = Pubkey.from_string("22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

CREDENTIAL_SEED = b"credential"
SCHEMA_SEED = b"schema"
ATTESTATION_SEED = b"attestation"

# The program's entrypoint splits the first byte and matches on it.
IX_CREATE_CREDENTIAL = 0
IX_CREATE_SCHEMA = 1
IX_CREATE_ATTESTATION = 6

# Schemas are created at version 1; the program hardcodes `let version = &[1]`
# and puts that byte in the PDA seeds.
SCHEMA_VERSION = 1

# Never expires. The program treats 0 as "no expiry" and otherwise rejects any
# timestamp already in the past.
NO_EXPIRY = 0


class SchemaDataType(enum.IntEnum):
    """The subset of the program's type tags we encode.

    The full enum is wider; these are the ones the Union schema uses. The
    values are positional in the program's `SchemaDataTypes`, so they are
    pinned by test rather than trusted.
    """

    U64 = 3
    I64 = 8
    STRING = 12
    VEC_U8 = 13


# --- encoding -------------------------------------------------------------
#
# Every variable-length field is a u32 little-endian count followed by the
# elements. For String and Vec<u8> the count is a byte count; for Vec<Pubkey>
# in `create_credential` it is an element count.


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _bytes_field(raw: bytes) -> bytes:
    return _u32(len(raw)) + raw


def _string_field(text: str) -> bytes:
    return _bytes_field(text.encode("utf-8"))


def _pubkey_vec(keys: list[Pubkey]) -> bytes:
    return _u32(len(keys)) + b"".join(bytes(k) for k in keys)


# --- PDAs -----------------------------------------------------------------


def derive_credential(authority: Pubkey, name: str) -> tuple[Pubkey, int]:
    """`["credential", authority, name]`.

    The authority is *in the seeds*, which is why SAS has no initialize to
    front-run: a different authority is simply a different account rather than
    a race for the same one.
    """
    return Pubkey.find_program_address(
        [CREDENTIAL_SEED, bytes(authority), name.encode("utf-8")], SAS_PROGRAM_ID
    )


def derive_schema(
    credential: Pubkey, name: str, version: int = SCHEMA_VERSION
) -> tuple[Pubkey, int]:
    """`["schema", credential, name, version]` with version as a single byte."""
    return Pubkey.find_program_address(
        [SCHEMA_SEED, bytes(credential), name.encode("utf-8"), bytes([version])],
        SAS_PROGRAM_ID,
    )


def derive_attestation(
    credential: Pubkey, schema: Pubkey, nonce: Pubkey
) -> tuple[Pubkey, int]:
    """`["attestation", credential, schema, nonce]`.

    We pass our bond PDA as the nonce. That is what makes the credential
    unforgeably per-`[human, task_id]`: the bond PDA is derived from those two,
    so a second attestation for the same pair would collide with an account
    that already exists, and `create_attestation` creates rather than writes.
    """
    return Pubkey.find_program_address(
        [ATTESTATION_SEED, bytes(credential), bytes(schema), bytes(nonce)],
        SAS_PROGRAM_ID,
    )


# --- instructions ---------------------------------------------------------


def create_credential_ix(
    *,
    payer: Pubkey,
    authority: Pubkey,
    name: str,
    authorized_signers: list[Pubkey],
) -> Instruction:
    """Create the issuer credential. Run once, by the admin, not per attestation.

    `authorized_signers` is the verifier set. It is rotatable afterwards via
    `change_authorized_signers`, which is the review's `update_authorities`
    finding already answered on this side of the system.
    """
    credential, _ = derive_credential(authority, name)
    data = (
        bytes([IX_CREATE_CREDENTIAL])
        + _string_field(name)
        + _pubkey_vec(authorized_signers)
    )
    return Instruction(
        program_id=SAS_PROGRAM_ID,
        accounts=[
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(credential, is_signer=False, is_writable=True),
            AccountMeta(authority, is_signer=True, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=data,
    )


def create_schema_ix(
    *,
    payer: Pubkey,
    authority: Pubkey,
    credential: Pubkey,
    name: str,
    description: str,
    layout: list[SchemaDataType],
    field_names: list[str],
) -> Instruction:
    """Create the schema an attestation's data must conform to.

    `layout` and `field_names` are parallel: the program validates stored data
    against `layout` by walking it and requiring the offsets to land exactly on
    the end of the data, so a mismatch is rejected on-chain rather than stored
    and discovered later.
    """
    if len(layout) != len(field_names):
        raise ValueError(
            f"layout has {len(layout)} types but {len(field_names)} field names; "
            "they describe the same fields and must correspond one to one"
        )

    schema, _ = derive_schema(credential, name)
    packed_names = _u32(len(field_names)) + b"".join(
        _string_field(n) for n in field_names
    )
    data = (
        bytes([IX_CREATE_SCHEMA])
        + _string_field(name)
        + _string_field(description)
        + _bytes_field(bytes(int(t) for t in layout))
        + packed_names
    )
    return Instruction(
        program_id=SAS_PROGRAM_ID,
        accounts=[
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(authority, is_signer=True, is_writable=False),
            AccountMeta(credential, is_signer=False, is_writable=False),
            AccountMeta(schema, is_signer=False, is_writable=True),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=data,
    )


def create_attestation_ix(
    *,
    payer: Pubkey,
    authorized_signer: Pubkey,
    credential: Pubkey,
    schema: Pubkey,
    nonce: Pubkey,
    schema_data: bytes,
    expiry: int = NO_EXPIRY,
) -> Instruction:
    """Issue the credential. `authorized_signer` is the verifier and must sign.

    Note which account is *absent*: the human. SAS records what an authorized
    issuer asserts, and does not require the subject to have signed anything.
    That is exactly why the liveness binding cannot live here - our own program
    is what makes the human's MWA signature a precondition.
    """
    attestation, _ = derive_attestation(credential, schema, nonce)
    data = (
        bytes([IX_CREATE_ATTESTATION])
        + bytes(nonce)
        + _bytes_field(schema_data)
        + expiry.to_bytes(8, "little", signed=True)
    )
    return Instruction(
        program_id=SAS_PROGRAM_ID,
        accounts=[
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(authorized_signer, is_signer=True, is_writable=False),
            AccountMeta(credential, is_signer=False, is_writable=False),
            AccountMeta(schema, is_signer=False, is_writable=False),
            AccountMeta(attestation, is_signer=False, is_writable=True),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=data,
    )


# --- the Union schema -----------------------------------------------------

CREDENTIAL_NAME = "union"
CLIP_JUDGMENT_SCHEMA_NAME = "clip-judgment"
CLIP_JUDGMENT_DESCRIPTION = (
    "A verified human completed a clip-judgment task, with a HUMAN bond staked "
    "behind the claim. Liveness and grading were performed off-chain by the "
    "named verifier."
)

CLIP_JUDGMENT_FIELDS = ["task_id", "liveness_proof_hash", "bond_amount", "attested_at"]
CLIP_JUDGMENT_LAYOUT = [
    SchemaDataType.STRING,
    SchemaDataType.VEC_U8,
    SchemaDataType.U64,
    SchemaDataType.I64,
]


@dataclass(frozen=True)
class ClipJudgmentClaim:
    """What the credential asserts, and nothing more.

    Deliberately absent: the answer the human gave. The credential says a human
    did the task under a bond - it is not a channel for the task output, which
    is the distinction the whole pivot rests on.
    """

    task_id: str
    liveness_proof_hash: bytes
    bond_amount: int
    attested_at: int

    def encode(self) -> bytes:
        if self.bond_amount < 0:
            raise ValueError("bond_amount is a u64 and cannot be negative")
        return (
            _string_field(self.task_id)
            + _bytes_field(self.liveness_proof_hash)
            + self.bond_amount.to_bytes(8, "little")
            + self.attested_at.to_bytes(8, "little", signed=True)
        )
