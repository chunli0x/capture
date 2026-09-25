"""The verifier key is what an attestation's authority rests on.

These tests pin the failure modes that would otherwise show up as an opaque
on-chain instruction error during a demo.
"""

from __future__ import annotations

import json
import os
import stat

import pytest
from solders.keypair import Keypair

from tapfarm.config import Settings
from tapfarm.verifier import (
    VerifierKeyError,
    key_permissions_are_private,
    load_verifier,
)


def _write_key(tmp_path, keypair: Keypair, name: str = "verifier.json"):
    path = tmp_path / name
    path.write_text(json.dumps(list(bytes(keypair))))
    return path


def test_loads_the_key_when_it_matches_the_configured_verifier(tmp_path):
    kp = Keypair()
    path = _write_key(tmp_path, kp)

    loaded = load_verifier(str(path), str(kp.pubkey()))

    assert loaded.pubkey() == kp.pubkey()


def test_a_key_that_is_not_the_configured_verifier_is_refused(tmp_path):
    """The whole point: a valid key that is the *wrong* key must not sign.

    On-chain this would be rejected by the program, so signing with it only
    moves the failure somewhere harder to read.
    """
    wrong = Keypair()
    expected = Keypair()
    path = _write_key(tmp_path, wrong)

    with pytest.raises(VerifierKeyError) as err:
        load_verifier(str(path), str(expected.pubkey()))

    message = str(err.value)
    assert str(wrong.pubkey()) in message
    assert str(expected.pubkey()) in message


def test_missing_key_says_it_is_not_bootstrapped(tmp_path):
    with pytest.raises(VerifierKeyError, match="not created by bootstrap"):
        load_verifier(str(tmp_path / "absent.json"), str(Keypair().pubkey()))


def test_malformed_key_is_reported_as_such(tmp_path):
    path = tmp_path / "verifier.json"
    path.write_text('{"not": "a keypair"}')

    with pytest.raises(VerifierKeyError, match="64-int Solana CLI keypair"):
        load_verifier(str(path), str(Keypair().pubkey()))


def test_empty_expected_pubkey_is_refused_rather_than_trusted(tmp_path):
    """An unset verifier must not degrade into "accept whatever key is here"."""
    path = _write_key(tmp_path, Keypair())

    with pytest.raises(VerifierKeyError, match="nothing to check"):
        load_verifier(str(path), "")


def test_permissions_check_flags_a_world_readable_key(tmp_path):
    path = _write_key(tmp_path, Keypair(), name="loose.json")

    os.chmod(path, 0o600)
    assert key_permissions_are_private(str(path)) is True

    os.chmod(path, 0o644)
    assert key_permissions_are_private(str(path)) is False

    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
    assert key_permissions_are_private(str(path)) is False


def test_default_verifier_pubkey_is_the_one_the_brief_fixed():
    assert (
        Settings().verifier_pubkey == "DNBwRqu7rEWTaod4r6daUGfFqXPqxpYHgaSRKhXp5SPP"
    )


class TestMintSeparation:
    """Two roles sharing a mint would defeat the unslashability invariant."""

    def test_human_and_skr_must_differ(self):
        mint = str(Keypair().pubkey())
        with pytest.raises(ValueError, match="different mints"):
            Settings(human_mint=mint, skr_mint=mint)

    def test_payroll_may_not_be_the_bond(self):
        mint = str(Keypair().pubkey())
        with pytest.raises(ValueError, match="different mints"):
            Settings(human_mint=mint, usdc_mint=mint)

    def test_three_distinct_mints_are_accepted(self):
        cfg = Settings(
            skr_mint=str(Keypair().pubkey()),
            human_mint=str(Keypair().pubkey()),
            usdc_mint=str(Keypair().pubkey()),
        )
        assert len({cfg.skr_mint, cfg.human_mint, cfg.usdc_mint}) == 3

    def test_unset_mints_do_not_collide_with_each_other(self):
        """Empty is "not configured", not a value - three blanks are fine."""
        cfg = Settings()
        assert cfg.human_mint == ""
        assert cfg.usdc_mint == ""
        assert cfg.skr_mint == ""
