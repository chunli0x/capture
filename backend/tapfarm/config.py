"""Configuration and economic constants.

## The tokens

**USDC** is payroll. Contributors are paid a stablecoin, never the token, so
the token is not what anyone is working for.
**HUMAN** is the attestation bond: the slashable stake behind an attestation.
Slashing is not wired in v1 - the bond is staked and shown, enforcement is v2 -
but HUMAN is the asset the slash path will ever be able to touch.
**SKR** is Solana Mobile's: a non-slashable access gate. We never mint SKR and
never burn it.
**TAP** is ours, and predates the Union pivot: the earn-side token and the
labeling quality bond. It stays wired because the labeling campaigns still use
it; new attestation work bonds HUMAN and pays USDC.

## Where the numbers come from

The defaults below are tuned so a demo is watchable - a contributor reaches a
stakeable balance in about ten tasks - and the ratios, not the absolute values,
are the part that carries over to production.

- `reward_per_task` 0.01 TAP: 100 tasks to a whole token, so the balance moves
  visibly on screen without the numbers looking like dust.
- `min_tap_stake` 0.1 TAP, about ten tasks of honest work. Deliberately low so
  the demo can show the whole earn-stake-unlock loop. In production a bond has
  to exceed what a burst of bad labeling can extract before the accuracy window
  catches up, which is a much larger multiple of per-task value - the right way
  to set it is from the window length in `scoring.py`, not by taste.
- `min_skr_stake` 1 SKR: nominal. It is a commitment signal, not collateral, so
  it only has to be inconvenient to fake at scale.
- `cooldown_seconds` 24h: long enough that a bad actor's accuracy is scored
  before they can exit, short enough not to feel punitive.
- `referral_share_of_fee_bps` 10% of our margin, which at a 20% platform fee is
  2% of task value. It comes out of the platform's cut and never out of the
  referee's earnings - that difference is what separates a referral bonus from
  a pyramid.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BPS = 10_000

# The canonical SKR mint, for when the access gate points at the real token
# rather than the devnet fixture. Verified against mainnet-beta: an SPL mint
# owned by the Token program with 6 decimals, which is why `skr_decimals`
# defaults to 6. Not the default for `skr_mint`, because devnet has no SKR and
# silently defaulting to a mainnet address would make a misconfigured devnet
# backend look configured.
SKR_MAINNET_MINT = "SKRbvo6Gf7GondiT3BbTfuRDPqLWei4j2Qy2NPGZhW3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAPFARM_", env_file=".env")

    rpc_url: str = "https://api.devnet.solana.com"
    cluster: str = "devnet"

    # --- TAP: earnings and the slashable bond -------------------------------
    # Created by scripts/bootstrap_devnet.sh. Ours on every cluster.
    tap_mint: str = ""
    tap_decimals: int = 6

    # --- HUMAN: the slashable attestation bond ------------------------------
    # Created by scripts/bootstrap_devnet.sh. The only asset an attestation
    # slash may ever target; making that structural is the point of a separate
    # mint, exactly as SKR's unslashability is structural in the program.
    human_mint: str = ""
    human_decimals: int = 6

    # --- USDC: payroll ------------------------------------------------------
    # Devnet has no canonical USDC we control, so bootstrap mints a stand-in
    # and records it here. On mainnet this is the real USDC mint and the
    # treasury holds a balance rather than mint authority.
    usdc_mint: str = ""
    usdc_decimals: int = 6

    # --- the verifier -------------------------------------------------------
    # The attestation is verifier-signed: the backend runs liveness and grades
    # the task, then signs mint_attestation. This pubkey is set on-chain at
    # initialize, so a third party can check "authorized by our verifier"
    # without trusting us about anything else. The private key never leaves
    # the backend host.
    verifier_pubkey: str = "DNBwRqu7rEWTaod4r6daUGfFqXPqxpYHgaSRKhXp5SPP"
    verifier_keypair_path: str = "verifier.json"

    # --- SKR: non-slashable access stake ------------------------------------
    # Empty on devnet, where SKR does not exist. Set to SKR_MAINNET_MINT for the
    # real staking demo; decimals must match that mint.
    skr_mint: str = ""
    skr_decimals: int = 6

    # Treasury keypair as a JSON array of 64 ints (Solana CLI keypair format).
    treasury_keypair_path: str = "treasury.json"

    # --- economics ----------------------------------------------------------
    reward_per_task: int = 10_000  # 0.01 TAP
    min_tap_stake: int = 100_000  # 0.1 TAP, ~10 tasks
    min_skr_stake: int = 1_000_000  # 1 SKR
    cooldown_seconds: int = 86_400  # 24h

    platform_fee_bps: int = Field(default=2_000, ge=0, le=BPS)  # 20% of task value
    referral_share_of_fee_bps: int = Field(default=1_000, ge=0, le=BPS)  # 10% of that

    # Contributors below this rolling gold-standard accuracy earn nothing.
    min_accuracy_to_claim: float = Field(default=0.80, gt=0.0, le=1.0)

    database_url: str = "sqlite:///./tapfarm.db"

    # Generated by `python -m tapfarm.generator.dataset`.
    dataset_dir: str = "data/tapgrid"

    # --- ghost-overlay (image-plane pose) campaign --------------------------
    # Generated by `python -m tapfarm.pose.dataset`.
    pose_dataset_dir: str = "data/pose"

    # Qualification gate. A starting point, not a physics constant: finger
    # input on a phone is looser than this first guess, and the robotics
    # advisor expects these to land nearer 25px / 15deg / 80% once fresh users
    # have been run through the golden set. They are config for that reason.
    pose_max_error_px: float = 15.0
    pose_max_error_deg: float = 10.0
    pose_pass_fraction: float = Field(default=0.90, gt=0.0, le=1.0)
    pose_qualify_items: int = Field(default=6, ge=1)

    # --- clip-judgment campaign ---------------------------------------------
    # Built by `python -m tapfarm.clip.dataset` from clips supplied to it.
    clip_dataset_dir: str = "data/clip"

    # Sized against the binomial tail, not by taste. A two-choice question has
    # a chance floor the ghost overlay does not: at the pose campaign's own
    # gate (6 items, 0.90) a coin-flipper passes 1.6% of the time, and at 0.80
    # it passes 10.9%. 12 items at 0.85 requires 11 correct, which luck reaches
    # 0.32% of the time while still forgiving one human misclick. Raising
    # qualify_items to 14 buys a second allowed mistake at 0.65%.
    clip_qualify_items: int = Field(default=12, ge=1)
    clip_pass_fraction: float = Field(default=0.85, gt=0.0, le=1.0)
    # Choices per question, used only to check the gate against chance.
    clip_choices: int = Field(default=2, ge=2)

    # A failed blind run is resettable this many times, after this cooldown.
    # One retry forgives a fluke; the cap is what keeps the gate from being
    # brute-forced, since 0.32% per attempt becomes about one in three over a
    # hundred attempts. The cooldown is what makes those attempts expensive.
    clip_max_retries: int = Field(default=1, ge=0)
    clip_retry_cooldown_seconds: float = Field(default=3600.0, ge=0.0)

    # Deployed tapfarm-stake program. Empty means staking is not wired up, in
    # which case nobody is referral-eligible and referrals accrue nothing.
    stake_program_id: str = ""

    # How long a read stake position is trusted before re-reading. See
    # stake_reader.py for why a stale window is acceptable here.
    stake_cache_ttl_seconds: float = 30.0

    @model_validator(mode="after")
    def _check_mints_differ(self) -> "Settings":
        """No two roles may share a mint.

        The separation is the safety property, not a tidiness preference: if
        HUMAN and SKR were the same mint, slashing the bond would slash the
        access gate, and the invariant the stake program tests on purpose
        would be defeated by configuration rather than by code.
        """
        named = {
            "tap_mint": self.tap_mint,
            "skr_mint": self.skr_mint,
            "human_mint": self.human_mint,
            "usdc_mint": self.usdc_mint,
        }
        seen: dict[str, str] = {}
        for role, mint in named.items():
            if not mint:
                continue
            if mint in seen:
                raise ValueError(
                    f"{seen[mint]} and {role} must be different mints (both {mint})"
                )
            seen[mint] = role
        return self

    @model_validator(mode="after")
    def _check_clip_gate_beats_chance(self) -> "Settings":
        """Refuse a blind gate a guesser clears too often.

        The claim on the demo's central screen is that the task is hard for a
        bot. With a small number of choices that is a property of the *gate's
        size*, not of the task, and it is quietly lost by lowering
        clip_pass_fraction. Checking it here means the configuration cannot
        contradict the pitch without failing to boot.
        """
        from tapfarm.clip.scoring import (
            MAX_CHANCE_PASS,
            chance_pass_probability,
            required_correct,
        )

        required = required_correct(self.clip_qualify_items, self.clip_pass_fraction)
        chance = chance_pass_probability(
            self.clip_qualify_items, required, self.clip_choices
        )
        if chance >= MAX_CHANCE_PASS:
            raise ValueError(
                f"clip gate is {self.clip_qualify_items} items needing {required} "
                f"correct, which a guesser passes {chance:.2%} of the time - over "
                f"the {MAX_CHANCE_PASS:.0%} budget. Raise clip_qualify_items or "
                "clip_pass_fraction."
            )
        return self

    def platform_fee(self, task_value: int) -> int:
        """Our margin on one completed task, in base units."""
        return task_value * self.platform_fee_bps // BPS

    def referral_reward(self, task_value: int) -> int:
        """What a referrer earns when their referee completes a paid task.

        Taken out of the platform fee, never out of the referee's reward, so a
        referred contributor is never worse off for having been referred. The
        cap below makes that structural rather than a matter of configuration
        discipline.
        """
        share = self.platform_fee(task_value) * self.referral_share_of_fee_bps // BPS
        return min(share, self.platform_fee(task_value))


@lru_cache
def settings() -> Settings:
    return Settings()
