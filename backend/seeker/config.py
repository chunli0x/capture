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
    sightengine_user: str = ""
    sightengine_secret: str = ""
    hive_key: str = ""
    max_upload_bytes: int = 15 * 1024 * 1024
    session_seconds: int = 3600
    min_bond: int = Field(default=1_000_000, gt=0, le=1_000_000_000_000)

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
