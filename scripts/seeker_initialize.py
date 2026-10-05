#!/usr/bin/env python3
"""Explicit test-cluster config initialization after an operator deploys the program."""

import argparse
import base64
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from seeker.chain import DEVNET_GENESIS, SYSTEM, Chain, discriminator, meta
from seeker.config import Settings
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upgrade-authority",
        required=True,
        type=Path,
        help="Keypair JSON held by the deployed program upgrade authority",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send after verifying test cluster; otherwise only print the unsigned operation summary",
    )
    args = parser.parse_args()
    s = Settings()
    chain = Chain(s)
    authority = Keypair.from_bytes(
        bytes(json.loads(args.upgrade_authority.read_text()))
    )
    genesis = chain.rpc("getGenesisHash", [])
    if s.cluster == "devnet" and genesis != DEVNET_GENESIS:
        parser.error("RPC is not devnet")
    if s.cluster == "localnet":
        from urllib.parse import urlparse

        if urlparse(s.rpc_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
            parser.error("Localnet must use loopback")
    loader = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    data_account = Pubkey.find_program_address([bytes(chain.program)], loader)[0]
    ix = Instruction(
        chain.program,
        discriminator("initialize")
        + bytes(chain.verifier.pubkey())
        + struct.pack("<Q", s.min_bond),
        [
            meta(authority.pubkey(), True, True),
            meta(chain.config, writable=True),
            meta(chain.usdc),
            meta(chain.skr),
            meta(chain.program),
            meta(data_account),
            meta(SYSTEM),
        ],
    )
    print(
        json.dumps(
            {
                "cluster": s.cluster,
                "program": str(chain.program),
                "config": str(chain.config),
                "verifier": str(chain.verifier.pubkey()),
                "usdc": str(chain.usdc),
                "skr": str(chain.skr),
                "min_bond": s.min_bond,
            },
            indent=2,
        )
    )
    if args.send:
        recent = chain.rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]
        msg = Message.new_with_blockhash(
            [ix], authority.pubkey(), Hash.from_string(recent["blockhash"])
        )
        tx = Transaction.new_unsigned(msg)
        tx.sign([authority], msg.recent_blockhash)
        print(
            "Submitted signature:",
            chain.rpc(
                "sendTransaction",
                [
                    base64.b64encode(bytes(tx)).decode(),
                    {"encoding": "base64", "preflightCommitment": "finalized"},
                ],
            ),
        )
        print(
            "Submission is not confirmation. Verify finalized config before starting the service."
        )


if __name__ == "__main__":
    main()
