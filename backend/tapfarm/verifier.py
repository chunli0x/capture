"""The verifier key: what makes an attestation mean anything.

An attestation is not a bare client claim. The backend runs the liveness check
and grades the task, and then *signs* `mint_attestation` with this key. The
on-chain record carries the verifier pubkey, fixed at `initialize`, so anyone
reading the chain can check "this was authorized by Clock In's verifier"
without having to trust the client that submitted it.

What that does and does not buy, stated plainly because the pitch will be
tempted to overstate it: on-chain you get identity, bond, timestamp and a
verifier signature. The liveness decision and the grading stay off-chain,
inside the verifier. A reader learns that we vouched for this human-task pair
and that a bond stands behind it - not that a human was cryptographically
proven to have acted. That distinction is the difference between an honest
claim and one a judge can take apart in Q&A.

The key is operational, not developmental: it is generated outside this repo,
held at `verifier_keypair_path` with 0600 permissions, and gitignored like
`treasury.json`. Nothing here ever writes it.
"""

from __future__ import annotations

import functools
import json
import pathlib
import stat

from solders.keypair import Keypair
from solders.pubkey import Pubkey


class VerifierKeyError(RuntimeError):
    """The verifier key is missing, malformed, or not the expected identity."""


@functools.lru_cache(maxsize=4)
def load_verifier(path_str: str, expected_pubkey: str) -> Keypair:
    """Load the verifier keypair and prove it is the one the chain expects.

    Cached on both arguments so a test pointing at its own fixture is not
    served whichever key happened to load first - the same reason
    `_load_treasury` caches on its path.

    The pubkey check is the point of this function. The attestation program
    only accepts signatures from the verifier recorded at `initialize`; a
    backend holding some *other* valid keypair would sign happily and have
    every mint rejected on-chain, which surfaces as an opaque instruction
    error at the worst possible moment. Failing here instead names the
    problem.
    """
    path = pathlib.Path(path_str)
    if not path.exists():
        raise VerifierKeyError(
            f"verifier keypair missing at {path}. It is generated outside this "
            "repo and installed on the backend host; it is deliberately not in "
            "git and not created by bootstrap."
        )

    try:
        raw = json.loads(path.read_text())
        keypair = Keypair.from_bytes(bytes(raw))
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same fault
        raise VerifierKeyError(
            f"verifier keypair at {path} is not a 64-int Solana CLI keypair: {exc}"
        ) from exc

    if not expected_pubkey:
        raise VerifierKeyError(
            "verifier_pubkey is unset, so there is nothing to check the loaded "
            "key against. Set it to the pubkey recorded on-chain at initialize."
        )

    expected = Pubkey.from_string(expected_pubkey)
    if keypair.pubkey() != expected:
        raise VerifierKeyError(
            f"verifier keypair at {path} is {keypair.pubkey()}, but the "
            f"configured verifier is {expected}. The attestation program only "
            "accepts the verifier set at initialize, so every mint signed with "
            "this key would be rejected on-chain."
        )

    return keypair


def key_permissions_are_private(path_str: str) -> bool:
    """True when the key file is not readable by group or others.

    Advisory: reported by the health endpoint rather than enforced, because a
    container image or a mounted secret may present perfectly safe permissions
    that do not look like 0600, and refusing to boot over that would be a
    worse failure than saying so.
    """
    path = pathlib.Path(path_str)
    if not path.exists():
        return False
    mode = path.stat().st_mode
    return not mode & (stat.S_IRWXG | stat.S_IRWXO)
