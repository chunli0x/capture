import base64
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest
from seeker.chain import Chain, ChainUnavailable, discriminator
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import Transaction
from spl.token.constants import TOKEN_PROGRAM_ID


@pytest.fixture
def chain(tmp_path):
    key = Keypair()
    p = tmp_path / "verifier.json"
    p.write_text(json.dumps(list(bytes(key))))
    return Chain(
        SimpleNamespace(
            program_id="5TiDwP86k95yfQWzExrPTj5qcKxED99z8pW9fN81u5SV",
            usdc_mint=str(Keypair().pubkey()),
            skr_mint=str(Keypair().pubkey()),
            verifier_key_file=p,
            cluster="localnet",
            rpc_url="http://127.0.0.1:8899",
            min_bond=1_000_000,
        )
    )


@pytest.fixture
def resources():
    payer, worker = Keypair(), Keypair()
    b = SimpleNamespace(
        id="01" * 16, requester=str(payer.pubkey()), reward=23, slots=4, deadline=1234
    )
    s = SimpleNamespace(
        worker=str(worker.pubkey()), media_hash="02" * 32, label_hash="03" * 32
    )
    return payer, worker, b, s


def test_instruction_layout_and_required_signers(chain, resources):
    payer, worker, b, s = resources
    ix = chain.build("fund", str(payer.pubkey()), b)[-1]
    assert ix.data == discriminator("post_bounty") + bytes.fromhex(b.id) + struct.pack(
        "<QIq", 23, 4, 1234
    )
    assert ix.accounts[0].pubkey == payer.pubkey() and ix.accounts[0].is_signer
    ix = chain.build("fulfill", str(worker.pubkey()), b, s)[-1]
    assert ix.data == discriminator("fulfill") + bytes.fromhex(
        s.media_hash
    ) + bytes.fromhex(s.label_hash)
    assert ix.accounts[0].is_signer and ix.accounts[1].is_signer
    assert ix.accounts[1].pubkey == chain.verifier.pubkey()
    for action in ("accept", "reject", "expire"):
        ix = chain.build(action, str(payer.pubkey()), b, s)[-1]
        assert ix.accounts[0].is_signer and ix.accounts[4].pubkey == worker.pubkey()
        assert ix.data == discriminator(action)
    for action in ("refund", "deposit", "withdraw"):
        assert (
            chain.build(action, str(payer.pubkey()), b)[-1].program_id == chain.program
        )
    with pytest.raises(ChainUnavailable):
        chain.build("unknown", str(payer.pubkey()))


def test_exact_signed_message_confirmation(chain, resources):
    payer, _worker, b, _s = resources
    msg = Message.new_with_blockhash(
        chain.build("fund", str(payer.pubkey()), b), payer.pubkey(), Hash.new_unique()
    )
    tx = Transaction.new_unsigned(msg)
    tx.sign([payer], msg.recent_blockhash)
    p = SimpleNamespace(message_hash=hashlib.sha256(bytes(msg)).hexdigest())
    result = {
        "meta": {"err": None},
        "transaction": [base64.b64encode(bytes(tx)).decode(), "base64"],
    }
    chain.rpc = lambda *args: result
    assert chain.confirm(p, str(tx.signatures[0]))
    p.message_hash = "bad"
    with pytest.raises(ChainUnavailable):
        chain.confirm(p, str(tx.signatures[0]))
    p.message_hash = hashlib.sha256(bytes(msg)).hexdigest()
    result["meta"]["err"] = {"InstructionError": [0, "error"]}
    with pytest.raises(ChainUnavailable):
        chain.confirm(p, str(tx.signatures[0]))
    chain.rpc = lambda *args: None
    with pytest.raises(ChainUnavailable):
        chain.confirm(p, str(tx.signatures[0]))


def test_unsigned_or_other_signer_never_confirms(chain, resources):
    payer, _worker, b, _s = resources
    msg = Message.new_with_blockhash(
        chain.build("fund", str(payer.pubkey()), b), payer.pubkey(), Hash.new_unique()
    )
    tx = Transaction.new_unsigned(msg)
    p = SimpleNamespace(message_hash=hashlib.sha256(bytes(msg)).hexdigest())
    chain.rpc = lambda *args: {
        "meta": {"err": None},
        "transaction": [base64.b64encode(bytes(tx)).decode(), "base64"],
    }
    with pytest.raises(ChainUnavailable):
        chain.confirm(p, str(tx.signatures[0]))


def test_prepare_cosigns_only_fulfillment(chain, resources):
    payer, worker, b, s = resources
    chain.check_environment = lambda: None
    block = Hash.new_unique()
    chain.rpc = lambda *args: {
        "value": {"blockhash": str(block), "lastValidBlockHeight": 300}
    }
    prepared = chain.prepare("fulfill", str(worker.pubkey()), b, s)
    tx = Transaction.from_bytes(base64.b64decode(prepared["transaction"]))
    checks = tx.verify_with_results()
    assert checks == [
        False,
        True,
    ]  # worker still must approve; only verifier has signed
    tx.partial_sign([worker], block)
    tx.verify()
    prepared = chain.prepare("fund", str(payer.pubkey()), b)
    assert Transaction.from_bytes(
        base64.b64decode(prepared["transaction"])
    ).verify_with_results() == [False]


def test_environment_binds_config_mints_verifier_and_network(chain):
    from seeker.chain import DEVNET_GENESIS

    raw = (
        discriminator("Config", "account")
        + bytes(Keypair().pubkey())  # admin (not checked)
        + bytes(chain.verifier.pubkey())
        + bytes(chain.usdc)
        + bytes(chain.skr)
        + struct.pack("<Q", 1_000_000)
        + bytes(chain.verifier.pubkey())  # slash_authority == verifier
    )
    assert len(raw) == 176
    account = {
        "value": {
            "owner": str(chain.program),
            "data": [base64.b64encode(raw).decode(), "base64"],
        }
    }
    chain.rpc = lambda method, params: (
        DEVNET_GENESIS if method == "getGenesisHash" else account
    )
    chain.check_environment()
    chain.settings.cluster = "devnet"
    chain.check_environment()
    account["value"]["owner"] = str(Keypair().pubkey())
    with pytest.raises(ChainUnavailable):
        chain.check_environment()
    chain.rpc = lambda *args: "mainnet"
    with pytest.raises(ChainUnavailable):
        chain.check_environment()


def test_environment_rejects_stale_144_byte_config(chain):
    from seeker.chain import DEVNET_GENESIS

    # The pre-slash layout (no slash_authority) must be rejected as a mismatch.
    raw = (
        discriminator("Config", "account")
        + bytes(Keypair().pubkey())
        + bytes(chain.verifier.pubkey())
        + bytes(chain.usdc)
        + bytes(chain.skr)
        + struct.pack("<Q", 1_000_000)
    )
    account = {
        "value": {
            "owner": str(chain.program),
            "data": [base64.b64encode(raw).decode(), "base64"],
        }
    }
    chain.rpc = lambda method, params: (
        DEVNET_GENESIS if method == "getGenesisHash" else account
    )
    with pytest.raises(ChainUnavailable):
        chain.check_environment()


def test_warn_slash_instruction_layout(chain, resources):
    _payer, worker, _b, _s = resources
    ix = chain.build("warn", str(worker.pubkey()))[-1]
    assert ix.data == discriminator("warn") + bytes(worker.pubkey())
    assert len(ix.accounts) == 3
    assert ix.accounts[0].pubkey == chain.verifier.pubkey() and ix.accounts[0].is_signer
    assert ix.accounts[1].pubkey == chain.config and not ix.accounts[1].is_writable
    assert ix.accounts[2].pubkey == chain.pda(b"bond", bytes(worker.pubkey()))
    assert ix.accounts[2].is_writable

    ix = chain.build("slash", str(worker.pubkey()))[-1]
    assert ix.data == discriminator("slash") + bytes(worker.pubkey())
    assert len(ix.accounts) == 6
    assert ix.accounts[0].pubkey == chain.verifier.pubkey() and ix.accounts[0].is_signer
    assert ix.accounts[2].pubkey == chain.pda(b"bond", bytes(worker.pubkey()))
    assert ix.accounts[3].pubkey == chain.pda(b"bond-vault", bytes(worker.pubkey()))
    assert ix.accounts[3].is_writable
    assert ix.accounts[4].pubkey == chain.penalty_vault and ix.accounts[4].is_writable
    assert ix.accounts[5].pubkey == TOKEN_PROGRAM_ID


def test_find_signature_paginates_beyond_first_100(chain, resources):
    payer, _worker, b, _s = resources
    msg = Message.new_with_blockhash(
        chain.build("fund", str(payer.pubkey()), b), payer.pubkey(), Hash.new_unique()
    )
    tx = Transaction.new_unsigned(msg)
    tx.sign([payer], msg.recent_blockhash)
    p = SimpleNamespace(
        wallet=str(payer.pubkey()),
        message_hash=hashlib.sha256(bytes(msg)).hexdigest(),
    )
    target = str(tx.signatures[0])

    decoys = [str(Keypair().sign_message(b"decoy")) for _ in range(100)]
    page1 = [{"signature": s, "err": None} for s in decoys]
    page2 = [{"signature": target, "err": None}]
    tx_lookup = {
        target: {
            "meta": {"err": None},
            "transaction": [base64.b64encode(bytes(tx)).decode(), "base64"],
        }
    }

    calls = []

    def fake_rpc(method, params):
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            return page1 if params[1].get("before") is None else page2
        if method == "getTransaction":
            return tx_lookup.get(params[0])
        raise AssertionError(f"unexpected rpc method: {method}")

    chain.rpc = fake_rpc
    assert chain.find_signature(p, b) == target

    sig_calls = [c for c in calls if c[0] == "getSignaturesForAddress"]
    assert len(sig_calls) == 2
    assert sig_calls[0][1][1] == {"commitment": "finalized", "limit": 100}
    assert sig_calls[1][1][1]["before"] == decoys[-1]


def test_faucet_and_settle_build_signed_instructions(chain, tmp_path):
    # Regression: the treasury is a Keypair (not a Pubkey), and the SPL
    # instruction params take pubkeys while _sign_and_send signs with the
    # Keypair. This exercises both paths end to end against a stub RPC.
    treasury = Keypair()
    p = tmp_path / "treasury.json"
    p.write_text(json.dumps(list(bytes(treasury))))
    chain.treasury = treasury
    chain.usdc_treasury = treasury
    chain._load_key = lambda path: Keypair.from_bytes(bytes(json.loads(path.read_text())))

    worker = Keypair()
    sent = []

    def fake_rpc(method, params):
        sent.append((method, params))
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.new_unique())}}
        if method == "sendTransaction":
            return "sig_" + method
        if method == "getSignatureStatuses":
            # confirm success so settle_usdc/post_batch _confirm_sent passes
            return {"value": [{"err": None, "confirmationStatus": "finalized"}]}
        raise AssertionError(f"unexpected rpc method: {method}")

    chain.rpc = fake_rpc
    # Faucet mints min_bond SKR to the worker (mint authority = treasury).
    sig = chain.faucet(str(worker.pubkey()))
    assert sig == "sig_sendTransaction"
    # Settlement transfers USDC from the treasury to the worker.
    sig = chain.settle_usdc(str(worker.pubkey()), 100_000)
    assert sig == "sig_sendTransaction"

    # Both produced exactly two sendTransaction calls (one each) and the
    # instructions serialized without a Keypair/Pubkey type mismatch.
    sends = [c for c in sent if c[0] == "sendTransaction"]
    assert len(sends) == 2
