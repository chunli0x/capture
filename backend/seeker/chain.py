"""Real Solana RPC + exact-message confirmation. No simulated payment path."""

import base64
import hashlib
import json
import struct
import time
from urllib.parse import urlparse

import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction, TransactionError
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID, TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

SYSTEM = Pubkey.default()
RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


class ChainUnavailable(ValueError):
    pass


def discriminator(name, kind="global"):
    return hashlib.sha256(f"{kind}:{name}".encode()).digest()[:8]


def meta(key, signer=False, writable=False):
    return AccountMeta(key, signer, writable)


def ata_instruction(payer, owner, mint):
    ata = get_associated_token_address(owner, mint)
    return Instruction(
        ASSOCIATED_TOKEN_PROGRAM_ID,
        bytes([1]),
        [
            meta(payer, True, True),
            meta(ata, writable=True),
            meta(owner),
            meta(mint),
            meta(SYSTEM),
            meta(TOKEN_PROGRAM_ID),
        ],
    )


class Chain:
    def __init__(self, settings):
        self.settings = settings
        self.program = Pubkey.from_string(settings.program_id)
        self.usdc = Pubkey.from_string(settings.usdc_mint)
        self.skr = Pubkey.from_string(settings.skr_mint)
        self.verifier = Keypair.from_bytes(
            bytes(json.loads(settings.verifier_key_file.read_text()))
        )
        self.config = self.pda(b"config")

    def pda(self, *seeds):
        return Pubkey.find_program_address(list(seeds), self.program)[0]

    def rpc(self, method, params):
        try:
            response = httpx.post(
                self.settings.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data or "result" not in data:
                raise ChainUnavailable("RPC rejected request")
            return data["result"]
        except (httpx.HTTPError, ValueError) as exc:
            raise ChainUnavailable("RPC unavailable; no settlement recorded") from exc

    def check_environment(self):
        genesis = self.rpc("getGenesisHash", [])
        if self.settings.cluster == "devnet":
            if genesis != DEVNET_GENESIS:
                raise ChainUnavailable("RPC is not Solana devnet")
        elif urlparse(self.settings.rpc_url).hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ChainUnavailable("Localnet RPC must be loopback")
        account = self.rpc(
            "getAccountInfo",
            [str(self.config), {"encoding": "base64", "commitment": "finalized"}],
        )["value"]
        if not account or account["owner"] != str(self.program):
            raise ChainUnavailable("Escrow program has not been initialized")
        raw = base64.b64decode(account["data"][0], validate=True)
        expected = (
            bytes(self.verifier.pubkey())
            + bytes(self.usdc)
            + bytes(self.skr)
            + struct.pack("<Q", self.settings.min_bond)
        )
        if (
            len(raw) != 144
            or raw[:8] != discriminator("Config", "account")
            or raw[40:] != expected
        ):
            raise ChainUnavailable(
                "Configured verifier, mints or bond differ from program"
            )

    def build(self, action, wallet, bounty=None, submission=None):
        who = Pubkey.from_string(wallet)
        b = (
            self.pda(
                b"bounty",
                bytes(Pubkey.from_string(bounty.requester)),
                bytes.fromhex(bounty.id),
            )
            if bounty
            else None
        )
        worker = Pubkey.from_string(submission.worker) if submission else who
        bond = self.pda(b"bond", bytes(worker))
        bond_vault = self.pda(b"bond-vault", bytes(worker))
        common = [meta(self.config), meta(self.usdc)]
        prefix = []
        if action == "fund":
            prefix = [ata_instruction(who, who, self.usdc)]
            accounts = [
                meta(who, True, True),
                *common,
                meta(b, writable=True),
                meta(self.pda(b"vault", bytes(b)), writable=True),
                meta(get_associated_token_address(who, self.usdc), writable=True),
                meta(TOKEN_PROGRAM_ID),
                meta(SYSTEM),
                meta(RENT),
            ]
            data = (
                discriminator("post_bounty")
                + bytes.fromhex(bounty.id)
                + struct.pack("<QIq", bounty.reward, bounty.slots, bounty.deadline)
            )
        elif action == "fulfill":
            accounts = [
                meta(who, True, True),
                meta(self.verifier.pubkey(), True),
                meta(self.config),
                meta(b, writable=True),
                meta(self.pda(b"submission", bytes(b), bytes(worker)), writable=True),
                meta(bond, writable=True),
                meta(bond_vault),
                meta(SYSTEM),
            ]
            data = (
                discriminator("fulfill")
                + bytes.fromhex(submission.media_hash)
                + bytes.fromhex(submission.label_hash)
            )
        elif action in {"accept", "reject", "expire"}:
            prefix = [ata_instruction(who, worker, self.usdc)]
            accounts = [
                meta(who, True),
                *common,
                meta(b, writable=True),
                meta(worker),
                meta(self.pda(b"submission", bytes(b), bytes(worker)), writable=True),
                meta(bond, writable=True),
                meta(self.pda(b"vault", bytes(b)), writable=True),
                meta(get_associated_token_address(worker, self.usdc), writable=True),
                meta(TOKEN_PROGRAM_ID),
            ]
            data = discriminator(action)
        elif action == "refund":
            prefix = [ata_instruction(who, who, self.usdc)]
            accounts = [
                meta(who, True),
                *common,
                meta(b),
                meta(self.pda(b"vault", bytes(b)), writable=True),
                meta(get_associated_token_address(who, self.usdc), writable=True),
                meta(TOKEN_PROGRAM_ID),
            ]
            data = discriminator(action)
        elif action in {"deposit", "withdraw"}:
            prefix = [ata_instruction(who, who, self.skr)]
            accounts = [
                meta(who, True, action == "deposit"),
                meta(self.config),
                meta(self.skr),
                meta(bond, writable=action == "deposit"),
                meta(bond_vault, writable=True),
                meta(get_associated_token_address(who, self.skr), writable=True),
                meta(TOKEN_PROGRAM_ID),
            ]
            if action == "deposit":
                accounts += [meta(SYSTEM), meta(RENT)]
            data = discriminator(
                "deposit_bond" if action == "deposit" else "withdraw_bond"
            )
            if action == "deposit":
                data += struct.pack("<Q", self.settings.min_bond)
        else:
            raise ChainUnavailable("Unknown transaction action")
        return prefix + [Instruction(self.program, data, accounts)]

    def prepare(self, action, wallet, bounty=None, submission=None):
        self.check_environment()
        result = self.rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]
        blockhash = Hash.from_string(result["blockhash"])
        msg = Message.new_with_blockhash(
            self.build(action, wallet, bounty, submission),
            Pubkey.from_string(wallet),
            blockhash,
        )
        tx = Transaction.new_unsigned(msg)
        if action == "fulfill":
            tx.partial_sign([self.verifier], blockhash)
        return {
            "transaction": base64.b64encode(bytes(tx)).decode(),
            "message_hash": hashlib.sha256(bytes(msg)).hexdigest(),
            "last_valid_height": result["lastValidBlockHeight"],
        }

    def height(self):
        return self.rpc("getBlockHeight", [{"commitment": "finalized"}])

    def confirm(self, prepared, signature):
        try:
            Signature.from_string(signature)
        except ValueError as exc:
            raise ChainUnavailable("Invalid transaction signature") from exc
        result = self.rpc(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "base64",
                    "commitment": "finalized",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if not result:
            raise ChainUnavailable(
                "Transaction is not finalized yet; retry confirmation"
            )
        if result["meta"]["err"] is not None:
            raise ChainUnavailable("Transaction failed; no settlement recorded")
        try:
            tx = Transaction.from_bytes(
                base64.b64decode(result["transaction"][0], validate=True)
            )
            tx.verify()
            if (
                str(tx.signatures[0]) != signature
                or hashlib.sha256(bytes(tx.message)).hexdigest()
                != prepared.message_hash
            ):
                raise ChainUnavailable(
                    "Transaction does not match this prepared operation"
                )
        except (ValueError, TypeError, TransactionError) as exc:
            raise ChainUnavailable("Invalid transaction confirmation") from exc
        return True

    def find_signature(self, prepared, bounty=None, submission=None):
        if bounty:
            address = self.pda(
                b"bounty",
                bytes(Pubkey.from_string(bounty.requester)),
                bytes.fromhex(bounty.id),
            )
        else:
            address = self.pda(b"bond", bytes(Pubkey.from_string(prepared.wallet)))
        page_size = 100
        max_pages = 20  # sane cap: walk at most 2000 signatures
        # Overall wall-clock bound on the whole walk, on top of the per-call
        # RPC timeout, so a slow RPC endpoint cannot stall reconciliation
        # indefinitely (20 pages x 15s would otherwise be 300s).
        deadline = time.monotonic() + 30
        before = None
        for _ in range(max_pages):
            if time.monotonic() > deadline:
                raise ChainUnavailable(
                    "Confirmation scan deadline exceeded; supply its signature"
                )
            params = {"commitment": "finalized", "limit": page_size}
            if before is not None:
                params["before"] = before
            results = self.rpc("getSignaturesForAddress", [str(address), params])
            for item in results:
                if item["err"] is None:
                    try:
                        self.confirm(prepared, item["signature"])
                        return item["signature"]
                    except ChainUnavailable:
                        continue
            if len(results) < page_size:
                break  # end of history
            before = results[-1]["signature"]
        raise ChainUnavailable(
            "No matching finalized transaction found in recent history; supply its signature"
        )
