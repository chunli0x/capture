"""The claim transaction's whole purpose is that the contributor must sign it.

These tests assert that structurally, so a refactor can't quietly turn the
wallet prompt back into decoration.
"""

import base64

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction
from spl.token.instructions import get_associated_token_address

from tapfarm.claim_tx import (
    build_claim_transaction,
    serialize_for_wallet,
    treasury_sign,
)

BLOCKHASH = Hash.from_string("11111111111111111111111111111111")
DECIMALS = 6
AMOUNT = 1_500_000  # 1.5 USDC


@pytest.fixture
def treasury_kp() -> Keypair:
    return Keypair()


@pytest.fixture
def contributor() -> Pubkey:
    return Keypair().pubkey()


@pytest.fixture
def mint() -> Pubkey:
    return Keypair().pubkey()


def _build(contributor, treasury_kp, mint) -> Transaction:
    return build_claim_transaction(
        contributor=contributor,
        treasury=treasury_kp.pubkey(),
        mint=mint,
        amount=AMOUNT,
        decimals=DECIMALS,
        blockhash=BLOCKHASH,
    )


def test_contributor_is_fee_payer(contributor, treasury_kp, mint):
    """Fee payer is account_keys[0] by definition, and it must be the user."""
    tx = _build(contributor, treasury_kp, mint)
    assert tx.message.account_keys[0] == contributor


def test_exactly_two_required_signers(contributor, treasury_kp, mint):
    tx = _build(contributor, treasury_kp, mint)
    assert tx.message.header.num_required_signatures == 2
    assert set(tx.message.signer_keys()) == {contributor, treasury_kp.pubkey()}


def test_treasury_signs_and_contributor_slot_stays_empty(
    contributor, treasury_kp, mint
):
    tx = treasury_sign(_build(contributor, treasury_kp, mint), treasury_kp)

    positions = tx.get_signing_keypair_positions([contributor, treasury_kp.pubkey()])
    contributor_idx, treasury_idx = positions[0], positions[1]

    assert tx.signatures[treasury_idx] != Signature.default()
    assert tx.signatures[contributor_idx] == Signature.default(), (
        "contributor's signature slot must be empty - the wallet fills it"
    )


def test_unsigned_by_contributor_means_verify_fails(contributor, treasury_kp, mint):
    """Proof the tx is genuinely unusable until the wallet signs it."""
    tx = treasury_sign(_build(contributor, treasury_kp, mint), treasury_kp)
    with pytest.raises(Exception):
        tx.verify()


def test_wallet_signature_completes_the_transaction(treasury_kp, mint):
    """Simulate what the wallet does, and confirm the result verifies."""
    contributor_kp = Keypair()
    tx = treasury_sign(
        _build(contributor_kp.pubkey(), treasury_kp, mint), treasury_kp
    )
    tx.partial_sign([contributor_kp], tx.message.recent_blockhash)
    tx.verify()  # raises if any required signature is missing or wrong


def test_transfer_targets_the_contributors_ata(contributor, treasury_kp, mint):
    tx = _build(contributor, treasury_kp, mint)
    keys = tx.message.account_keys
    referenced = {keys[i] for ix in tx.message.instructions for i in ix.accounts}
    assert get_associated_token_address(contributor, mint) in referenced
    assert get_associated_token_address(treasury_kp.pubkey(), mint) in referenced


def test_roundtrips_through_base64(contributor, treasury_kp, mint):
    """MWA receives base64; make sure it survives the trip."""
    tx = treasury_sign(_build(contributor, treasury_kp, mint), treasury_kp)
    restored = Transaction.from_bytes(base64.b64decode(serialize_for_wallet(tx)))
    assert restored.message.account_keys[0] == contributor
    assert restored.signatures == tx.signatures


@pytest.mark.parametrize("bad", [0, -1, -1_000_000])
def test_rejects_nonpositive_amounts(contributor, treasury_kp, mint, bad):
    with pytest.raises(ValueError, match="must be positive"):
        build_claim_transaction(
            contributor=contributor,
            treasury=treasury_kp.pubkey(),
            mint=mint,
            amount=bad,
            decimals=DECIMALS,
            blockhash=BLOCKHASH,
        )

