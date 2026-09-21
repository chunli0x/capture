"""The union-bond wire format, re-derived rather than copied.

Same discipline as test_sas.py: the discriminator and account order are
computed here from the program's own rules, so a test passing means our
encoder agrees with the program rather than with itself.
"""

from __future__ import annotations

import hashlib
import struct

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from tapfarm.bond_client import (
    BOND_SEED,
    CONFIG_SEED,
    LIVENESS_SEED,
    MAX_TASK_ID_LEN,
    VAULT_SEED,
    derive_bond,
    derive_config,
    derive_liveness_receipt,
    derive_vault,
    instruction_discriminator,
    post_bond_ix,
)

PROGRAM = Pubkey.from_string("BondDfbRr6dZ4TYr6yBSAqWnJb1zpCPtkTqTH1HNMz6a")
HASH = bytes(range(32))


def _key() -> Pubkey:
    return Keypair().pubkey()


def _ix(**overrides):
    args = dict(
        program_id=PROGRAM,
        payer=_key(),
        human=_key(),
        verifier=_key(),
        human_mint=_key(),
        human_tokens=_key(),
        task_id="qualify-0007",
        liveness_proof_hash=HASH,
        amount=100_000,
    )
    args.update(overrides)
    return post_bond_ix(**args)


class TestDiscriminator:
    def test_matches_anchors_rule(self):
        assert (
            instruction_discriminator("post_bond")
            == hashlib.sha256(b"global:post_bond").digest()[:8]
        )

    def test_the_instruction_data_starts_with_it(self):
        assert bytes(_ix().data)[:8] == instruction_discriminator("post_bond")


class TestArgumentEncoding:
    def test_args_decode_the_way_the_program_reads_them(self):
        ix = _ix(task_id="live-0042", amount=250_000)
        data = bytes(ix.data)[8:]
        length = struct.unpack_from("<I", data, 0)[0]
        assert length == len("live-0042")
        assert data[4 : 4 + length].decode() == "live-0042"
        offset = 4 + length
        assert data[offset : offset + 32] == HASH
        assert struct.unpack_from("<Q", data, offset + 32)[0] == 250_000
        assert offset + 40 == len(data), "no trailing bytes"

    def test_task_id_length_is_bytes_not_characters(self):
        """A 16-character multibyte id is 32 bytes: right at the seed limit."""
        ix = _ix(task_id="é" * 16)
        data = bytes(ix.data)[8:]
        assert struct.unpack_from("<I", data, 0)[0] == 32

    def test_a_task_id_over_the_seed_limit_is_refused(self):
        with pytest.raises(ValueError, match="PDA seed limit"):
            _ix(task_id="x" * (MAX_TASK_ID_LEN + 1))

    def test_a_multibyte_task_id_over_the_limit_is_refused(self):
        with pytest.raises(ValueError, match="PDA seed limit"):
            _ix(task_id="é" * 17)

    def test_an_empty_task_id_is_refused(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _ix(task_id="")

    def test_a_zero_bond_is_refused(self):
        with pytest.raises(ValueError, match="must be positive"):
            _ix(amount=0)

    def test_a_short_hash_is_refused(self):
        with pytest.raises(ValueError, match="32 bytes"):
            _ix(liveness_proof_hash=b"\x01" * 16)

    def test_an_all_zero_hash_is_refused(self):
        """The program rejects it too; failing here names the problem."""
        with pytest.raises(ValueError, match="all zeroes"):
            _ix(liveness_proof_hash=bytes(32))


class TestAccounts:
    def test_order_and_flags_match_the_programs_context(self):
        payer, human, verifier = _key(), _key(), _key()
        mint, tokens = _key(), _key()
        ix = _ix(
            payer=payer, human=human, verifier=verifier,
            human_mint=mint, human_tokens=tokens,
        )
        keys = [m.pubkey for m in ix.accounts]
        assert keys[0] == payer
        assert keys[1] == human
        assert keys[2] == verifier
        assert keys[3] == derive_config(PROGRAM, mint)[0]
        assert keys[4] == derive_bond(PROGRAM, human, "qualify-0007")[0]
        assert keys[5] == derive_liveness_receipt(PROGRAM, HASH)[0]
        assert keys[6] == derive_vault(PROGRAM, mint)[0]
        assert keys[7] == tokens
        assert keys[8] == mint

    def test_both_the_human_and_the_verifier_must_sign(self):
        """The human's signature is what makes them a party to the claim.

        SAS's own create_attestation does not require it; this does, and a
        change that quietly dropped it would make the credential something
        asserted about somebody rather than by them.
        """
        payer, human, verifier = _key(), _key(), _key()
        ix = _ix(payer=payer, human=human, verifier=verifier)
        signers = {m.pubkey for m in ix.accounts if m.is_signer}
        assert signers == {payer, human, verifier}

    def test_the_accounts_the_program_writes_are_writable(self):
        ix = _ix()
        writable = [m.is_writable for m in ix.accounts]
        # payer, config, bond, receipt, vault, human_tokens
        assert [writable[i] for i in (0, 3, 4, 5, 6, 7)] == [True] * 6
        # human, verifier, mint and the programs are not written
        assert [writable[i] for i in (1, 2, 8, 9, 10, 11)] == [False] * 6


class TestPdas:
    def test_bond_seeds_are_human_and_task(self):
        human = _key()
        expected, _ = Pubkey.find_program_address(
            [BOND_SEED, bytes(human), b"qualify-0007"], PROGRAM
        )
        assert derive_bond(PROGRAM, human, "qualify-0007")[0] == expected

    def test_two_humans_cannot_collide_on_one_task(self):
        assert (
            derive_bond(PROGRAM, _key(), "t")[0]
            != derive_bond(PROGRAM, _key(), "t")[0]
        )

    def test_one_human_gets_a_distinct_bond_per_task(self):
        human = _key()
        assert (
            derive_bond(PROGRAM, human, "task-a")[0]
            != derive_bond(PROGRAM, human, "task-b")[0]
        )

    def test_the_receipt_is_keyed_only_on_the_hash(self):
        """So the same proof collides regardless of who presents it."""
        expected, _ = Pubkey.find_program_address([LIVENESS_SEED, HASH], PROGRAM)
        assert derive_liveness_receipt(PROGRAM, HASH)[0] == expected

    def test_config_and_vault_are_keyed_on_the_mint(self):
        mint = _key()
        assert derive_config(PROGRAM, mint)[0] == Pubkey.find_program_address(
            [CONFIG_SEED, bytes(mint)], PROGRAM
        )[0]
        assert derive_vault(PROGRAM, mint)[0] == Pubkey.find_program_address(
            [VAULT_SEED, bytes(mint)], PROGRAM
        )[0]

    def test_every_pda_is_off_curve(self):
        human, mint = _key(), _key()
        for pda in (
            derive_config(PROGRAM, mint)[0],
            derive_vault(PROGRAM, mint)[0],
            derive_bond(PROGRAM, human, "t")[0],
            derive_liveness_receipt(PROGRAM, HASH)[0],
        ):
            assert pda.is_on_curve() is False
