import base64
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEEKER_", extra="ignore")
    database_url: str = "postgresql+psycopg://localhost/seeker"
    local_sqlite: bool = False
    domain: str = "localhost"
    operator_key: str
    media_key: str  # base64 AES-256 key; keep outside DB/backups
    rpc_url: str = "https://api.devnet.solana.com"
    cluster: str = "devnet"
    program_id: str
    usdc_mint: str
    skr_mint: str
    verifier_key_file: Path
    # Devnet treasuries (both optional, 0600, gitignored). treasury_key_file
    # holds the SKR mint authority keypair (the /bond/faucet mint); the
    # usdc_treasury_key_file holds the USDC payout wallet (accept settlement).
    # Unset -> the corresponding on-chain operation is unavailable and the
    # backend fails closed instead of fabricating a transfer.
    treasury_key_file: Path | None = None
    usdc_treasury_key_file: Path | None = None
    sightengine_user: str = ""
    sightengine_secret: str = ""
    max_upload_bytes: int = 15 * 1024 * 1024
    max_video_bytes: int = 100 * 1024 * 1024
    session_seconds: int = 3600
    min_bond: int = Field(default=1_000_000, gt=0, le=1_000_000_000_000)
    # Capture v2 VLM judge. judge_driver="" -> deterministic StubJudge (tests
    # run free); judge_driver="astra" -> real gpt-6-astra via the Codex CLI
    # (uses the ChatGPT OAuth token already on this box). Fail-closed.
    judge_driver: str = ""
    judge_codex_bin: str = "/usr/local/bin/codex-judge"
    judge_timeout_seconds: int = 90
    # Per-wallet daily cap on judged uploads. The VLM judge is the single
    # biggest token cost; this bounds a heavy user (or a script) from draining
    # the judge budget. 0 disables.
    judge_daily_cap: int = 50

    # ---- Judgment product (RLHF preference judging) ----
    # Consensus-gated pay in test $SKR. All are starting hypotheses (incentive
    # spec §8): tune against real agreement data, not once.
    judge_k: int = Field(default=3, gt=0)
    calibration_n: int = Field(default=10, gt=0)
    judge_window: int = Field(default=100, gt=0)
    judge_slash_floor: float = 0.45
    judge_slash_min_judged: int = Field(default=20, gt=0)
    # Payout in SKR base units. The treasury keypair is the SKR mint authority;
    # settlement mints test SKR to the judge (devnet faucet-equivalent).
    judge_base_skr: int = Field(default=1_000_000, gt=0)
    judge_flat_skr: int = Field(default=100_000, gt=0)
    # Cap on flat "can't tell" payments a judge can earn per rolling window,
    # to bound abstention farming (finding #12): three colluding judges can
    # otherwise send "can't tell" on every fresh pair and collect flat without
    # ever resolving a task. 0 disables the cap.
    judge_flat_cap: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def safe_environment(self):
        if self.cluster not in {"devnet", "localnet"}:
            raise ValueError("Only devnet/localnet are supported")
        if self.database_url.startswith("sqlite") and not self.local_sqlite:
            raise ValueError("SQLite requires explicit local_sqlite=true")
        if (
            len(self.operator_key) < 32
            or len(base64.b64decode(self.media_key, validate=True)) != 32
        ):
            raise ValueError("Independent operator and media keys are required")
        if not self.domain or "\n" in self.domain:
            raise ValueError("Invalid authentication domain")
        return self
