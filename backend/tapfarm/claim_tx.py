"""Two-signer claim transaction.

The contributor is the *fee payer*; the treasury is the *token authority*. That
makes both parties required signers on a single transaction:

    signer[0] = contributor   (fee payer, signs in the wallet via MWA)
    signer[1] = treasury      (partial-signed here, server-side)

This matters. If the treasury simply transferred tokens to the contributor, the
contributor would sign nothing and the wallet approval prompt would be
decorative. Making them the fee payer means the wallet is approving a real
transaction it must sign for the transfer to land at all.

Instruction order:
  1. create_idempotent_associated_token_account  - payer: contributor
     No-ops if the contributor already has a USDC token account, so the first
     claim and the fiftieth take the same code path.
  2. transfer_checked  - authority: treasury
     `transfer_checked` over `transfer` so the mint and decimals are validated
     on-chain; a decimals mismatch fails the instruction instead of moving the
     wrong amount.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from solders.hash import Hash
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


@dataclass(frozen=True)
class ClaimQuote:
    """What a contributor is owed, in mint base units."""

    contributor: Pubkey
    amount: int
    decimals: int

    def ui_amount(self) -> float:
        return self.amount / (10**self.decimals)


def build_claim_transaction(
    *,
    contributor: Pubkey,
    treasury: Pubkey,
    mint: Pubkey,
    amount: int,
    decimals: int,
    blockhash: Hash,
) -> Transaction:
    """Build the unsigned claim transaction with the contributor as fee payer."""
    if amount <= 0:
        raise ValueError(f"claim amount must be positive, got {amount}")

    treasury_ata = get_associated_token_address(treasury, mint)
    contributor_ata = get_associated_token_address(contributor, mint)

    instructions = [
        create_idempotent_associated_token_account(
            payer=contributor, owner=contributor, mint=mint
        ),
        transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=treasury_ata,
                mint=mint,
                dest=contributor_ata,
                owner=treasury,
                amount=amount,
                decimals=decimals,
            )
        ),
    ]

    # Third arg to new_with_blockhash is the fee payer: the contributor, not us.
    message = Message.new_with_blockhash(instructions, contributor, blockhash)
    return Transaction.new_unsigned(message)


def treasury_sign(tx: Transaction, treasury_keypair: Keypair) -> Transaction:
    """Apply the treasury's signature, leaving the contributor's slot empty.

    `partial_sign` clears prior signatures if handed a different blockhash, so
    always pass the one already recorded in the message.
    """
    tx.partial_sign([treasury_keypair], tx.message.recent_blockhash)
    return tx


def serialize_for_wallet(tx: Transaction) -> str:
    """Base64 the wire-format transaction for MWA `signAndSendTransactions`."""
    return base64.b64encode(bytes(tx)).decode("ascii")
