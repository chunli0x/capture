"""The SAS wire format, pinned by re-parsing it the way the program does.

These tests are deliberately written as a *mirror* of the deployed program's
parsing logic rather than as assertions about byte strings we produced. A test
that only checks our encoder against itself would pass just as happily if both
sides were wrong; re-implementing the reader from the program source and
feeding it our writer's output is what makes it evidence.

The reference for each mirror below is the Rust in
`program/src/processor/*.rs` and `program/src/state/attestation.rs`.
"""

from __future__ import annotations

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from tapfarm.sas import (
    CLIP_JUDGMENT_FIELDS,
    CLIP_JUDGMENT_LAYOUT,
    CLIP_JUDGMENT_SCHEMA_NAME,
    CREDENTIAL_NAME,
    IX_CREATE_ATTESTATION,
    IX_CREATE_CREDENTIAL,
    IX_CREATE_SCHEMA,
    SAS_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    ClipJudgmentClaim,
    SchemaDataType,
    create_attestation_ix,
    create_credential_ix,
    create_schema_ix,
    derive_attestation,
    derive_credential,
    derive_schema,
)


def _key() -> Pubkey:
    return Keypair().pubkey()


# --- mirrors of the program's parsers -------------------------------------


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return int.from_bytes(data[offset : offset + 4], "little"), offset + 4


def parse_create_credential(data: bytes) -> dict:
    """Mirror of `create_credential.rs::process_instruction_data`."""
    assert data[0] == IX_CREATE_CREDENTIAL
    body, offset = data[1:], 0
    name_len, offset = _read_u32(body, offset)
    name = body[offset : offset + name_len].decode("utf-8")
    offset += name_len
    signers_len, offset = _read_u32(body, offset)
    signers = []
    for _ in range(signers_len):
        signers.append(Pubkey(body[offset : offset + 32]))
        offset += 32
    assert offset == len(body), "trailing bytes the program would not consume"
    return {"name": name, "signers": signers}


def parse_create_schema(data: bytes) -> dict:
    """Mirror of `create_schema.rs::process_instruction_data`."""
    assert data[0] == IX_CREATE_SCHEMA
    body, offset = data[1:], 0
    name_len, offset = _read_u32(body, offset)
    name = body[offset : offset + name_len].decode("utf-8")
    offset += name_len
    desc_len, offset = _read_u32(body, offset)
    description = body[offset : offset + desc_len].decode("utf-8")
    offset += desc_len
    layout_len, offset = _read_u32(body, offset)
    layout = list(body[offset : offset + layout_len])
    offset += layout_len
    count, offset = _read_u32(body, offset)
    field_names = []
    for _ in range(count):
        field_len, offset = _read_u32(body, offset)
        field_names.append(body[offset : offset + field_len].decode("utf-8"))
        offset += field_len
    assert offset == len(body)
    return {
        "name": name,
        "description": description,
        "layout": layout,
        "field_names": field_names,
    }


def parse_create_attestation(data: bytes) -> dict:
    """Mirror of `create_attestation.rs::process_instruction_data`."""
    assert data[0] == IX_CREATE_ATTESTATION
    body, offset = data[1:], 0
    nonce = Pubkey(body[offset : offset + 32])
    offset += 32
    data_len, offset = _read_u32(body, offset)
    schema_data = body[offset : offset + data_len]
    offset += data_len
    expiry = int.from_bytes(body[offset : offset + 8], "little", signed=True)
    offset += 8
    assert offset == len(body)
    return {"nonce": nonce, "data": schema_data, "expiry": expiry}


_FIXED_WIDTH = {
    SchemaDataType.U64: 8,
    SchemaDataType.I64: 8,
}
_VEC_ELEMENT_WIDTH = {
    SchemaDataType.STRING: 1,
    SchemaDataType.VEC_U8: 1,
}


def validate_data(layout: list[int], data: bytes) -> bool:
    """Mirror of `Attestation::validate_data`.

    The program walks the layout accumulating offsets and requires the total to
    land exactly on the end of the data. Anything else is rejected.
    """
    offset = 0
    for tag in layout:
        kind = SchemaDataType(tag)
        if kind in _FIXED_WIDTH:
            offset += _FIXED_WIDTH[kind]
        else:
            if offset + 4 > len(data):
                return False
            count = int.from_bytes(data[offset : offset + 4], "little")
            offset += 4 + count * _VEC_ELEMENT_WIDTH[kind]
    return offset == len(data)


# --- the tests ------------------------------------------------------------


class TestCreateCredential:
    def test_round_trips_through_the_programs_parser(self):
        authority, payer = _key(), _key()
        verifier = _key()

        ix = create_credential_ix(
            payer=payer,
            authority=authority,
            name=CREDENTIAL_NAME,
            authorized_signers=[verifier],
        )
        parsed = parse_create_credential(bytes(ix.data))

        assert parsed["name"] == CREDENTIAL_NAME
        assert parsed["signers"] == [verifier]

    def test_several_signers_survive_the_round_trip(self):
        """Rotation means more than one key is live at once during a handover."""
        signers = [_key() for _ in range(3)]
        ix = create_credential_ix(
            payer=_key(), authority=_key(), name="union", authorized_signers=signers
        )
        assert parse_create_credential(bytes(ix.data))["signers"] == signers

    def test_account_order_and_signer_flags_match_the_program(self):
        authority, payer = _key(), _key()
        ix = create_credential_ix(
            payer=payer, authority=authority, name="union", authorized_signers=[_key()]
        )
        credential, _ = derive_credential(authority, "union")

        assert [m.pubkey for m in ix.accounts] == [
            payer,
            credential,
            authority,
            SYSTEM_PROGRAM_ID,
        ]
        assert [m.is_signer for m in ix.accounts] == [True, False, True, False]
        assert [m.is_writable for m in ix.accounts] == [True, True, False, False]
        assert ix.program_id == SAS_PROGRAM_ID


class TestCreateSchema:
    def test_round_trips_with_the_union_schema(self):
        credential, _ = derive_credential(_key(), CREDENTIAL_NAME)
        ix = create_schema_ix(
            payer=_key(),
            authority=_key(),
            credential=credential,
            name=CLIP_JUDGMENT_SCHEMA_NAME,
            description="desc",
            layout=CLIP_JUDGMENT_LAYOUT,
            field_names=CLIP_JUDGMENT_FIELDS,
        )
        parsed = parse_create_schema(bytes(ix.data))

        assert parsed["name"] == CLIP_JUDGMENT_SCHEMA_NAME
        assert parsed["layout"] == [int(t) for t in CLIP_JUDGMENT_LAYOUT]
        assert parsed["field_names"] == CLIP_JUDGMENT_FIELDS

    def test_layout_and_field_names_must_correspond(self):
        """Caught here rather than as a silent mislabelling on-chain."""
        with pytest.raises(ValueError, match="one to one"):
            create_schema_ix(
                payer=_key(),
                authority=_key(),
                credential=_key(),
                name="s",
                description="d",
                layout=CLIP_JUDGMENT_LAYOUT,
                field_names=["only_one"],
            )

    def test_non_ascii_description_is_length_prefixed_in_bytes_not_characters(self):
        """A char count would desynchronise the parser on any non-ASCII text."""
        description = "clip judgment — “phone or wallet”"
        ix = create_schema_ix(
            payer=_key(),
            authority=_key(),
            credential=_key(),
            name="s",
            description=description,
            layout=[SchemaDataType.U64],
            field_names=["n"],
        )
        assert parse_create_schema(bytes(ix.data))["description"] == description


class TestCreateAttestation:
    def test_round_trips_including_the_nonce_and_expiry(self):
        credential, schema, nonce = _key(), _key(), _key()
        claim = ClipJudgmentClaim(
            task_id="phone-or-wallet#441",
            liveness_proof_hash=b"\x11" * 32,
            bond_amount=100_000_000,
            attested_at=1_789_000_000,
        )

        ix = create_attestation_ix(
            payer=_key(),
            authorized_signer=_key(),
            credential=credential,
            schema=schema,
            nonce=nonce,
            schema_data=claim.encode(),
        )
        parsed = parse_create_attestation(bytes(ix.data))

        assert parsed["nonce"] == nonce
        assert parsed["data"] == claim.encode()
        assert parsed["expiry"] == 0

    def test_the_verifier_is_the_only_required_signer_besides_the_payer(self):
        """The human is absent by design - SAS does not require the subject.

        Pinned as a test because it is the reason the liveness binding has to
        live in our own program, and a future edit that quietly added the human
        here would make it look solved when it is not.
        """
        payer, verifier, human = _key(), _key(), _key()
        ix = create_attestation_ix(
            payer=payer,
            authorized_signer=verifier,
            credential=_key(),
            schema=_key(),
            nonce=_key(),
            schema_data=b"",
        )

        signers = [m.pubkey for m in ix.accounts if m.is_signer]
        assert signers == [payer, verifier]
        assert human not in [m.pubkey for m in ix.accounts]

    def test_attestation_account_is_the_derived_pda(self):
        credential, schema, nonce = _key(), _key(), _key()
        ix = create_attestation_ix(
            payer=_key(),
            authorized_signer=_key(),
            credential=credential,
            schema=schema,
            nonce=nonce,
            schema_data=b"",
        )
        expected, _ = derive_attestation(credential, schema, nonce)
        assert ix.accounts[4].pubkey == expected
        assert ix.accounts[4].is_writable is True


class TestSchemaDataAgreesWithLayout:
    def test_encoded_claim_validates_against_the_declared_layout(self):
        """The on-chain check our data has to survive."""
        claim = ClipJudgmentClaim(
            task_id="phone-or-wallet#441",
            liveness_proof_hash=b"\xab" * 32,
            bond_amount=100_000_000,
            attested_at=1_789_000_000,
        )
        layout = [int(t) for t in CLIP_JUDGMENT_LAYOUT]
        assert validate_data(layout, claim.encode()) is True

    def test_empty_hash_and_zero_bond_still_validate(self):
        claim = ClipJudgmentClaim(
            task_id="", liveness_proof_hash=b"", bond_amount=0, attested_at=0
        )
        assert validate_data([int(t) for t in CLIP_JUDGMENT_LAYOUT], claim.encode())

    def test_a_truncated_payload_is_rejected(self):
        claim = ClipJudgmentClaim(
            task_id="t", liveness_proof_hash=b"\x01", bond_amount=1, attested_at=1
        )
        layout = [int(t) for t in CLIP_JUDGMENT_LAYOUT]
        assert validate_data(layout, claim.encode()[:-1]) is False

    def test_trailing_bytes_are_rejected(self):
        claim = ClipJudgmentClaim(
            task_id="t", liveness_proof_hash=b"\x01", bond_amount=1, attested_at=1
        )
        layout = [int(t) for t in CLIP_JUDGMENT_LAYOUT]
        assert validate_data(layout, claim.encode() + b"\x00") is False

    def test_negative_bond_is_refused_before_it_can_wrap(self):
        claim = ClipJudgmentClaim(
            task_id="t", liveness_proof_hash=b"", bond_amount=-1, attested_at=0
        )
        with pytest.raises(ValueError, match="cannot be negative"):
            claim.encode()

    def test_negative_timestamps_are_encodable(self):
        """attested_at is an i64 in the layout; it must sign-extend, not raise."""
        claim = ClipJudgmentClaim(
            task_id="t", liveness_proof_hash=b"", bond_amount=0, attested_at=-1
        )
        assert validate_data([int(t) for t in CLIP_JUDGMENT_LAYOUT], claim.encode())

    def test_the_claim_carries_no_task_answer(self):
        """The credential attests that work happened, not what the answer was."""
        assert "answer" not in CLIP_JUDGMENT_FIELDS
        assert set(CLIP_JUDGMENT_FIELDS) == {
            "task_id",
            "liveness_proof_hash",
            "bond_amount",
            "attested_at",
        }


class TestPdaDerivation:
    def test_derivations_are_deterministic(self):
        authority = _key()
        assert derive_credential(authority, "union") == derive_credential(
            authority, "union"
        )

    def test_a_different_authority_is_a_different_credential(self):
        """Why SAS has no initialize to front-run."""
        assert derive_credential(_key(), "union")[0] != derive_credential(
            _key(), "union"
        )[0]

    def test_schema_version_changes_the_address(self):
        credential = _key()
        assert (
            derive_schema(credential, "clip-judgment", 1)[0]
            != derive_schema(credential, "clip-judgment", 2)[0]
        )

    def test_a_different_nonce_is_a_different_attestation(self):
        """The nonce is our bond PDA, so this is per-[human, task_id] identity."""
        credential, schema = _key(), _key()
        assert (
            derive_attestation(credential, schema, _key())[0]
            != derive_attestation(credential, schema, _key())[0]
        )

    def test_all_pdas_belong_to_the_sas_program(self):
        credential, _ = derive_credential(_key(), "union")
        schema, _ = derive_schema(credential, "clip-judgment")
        attestation, _ = derive_attestation(credential, schema, _key())
        for pda in (credential, schema, attestation):
            assert pda.is_on_curve() is False
