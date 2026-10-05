from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from solders.pubkey import Pubkey


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Wallet(Strict):
    wallet: str

    @field_validator("wallet")
    @classmethod
    def valid_wallet(cls, v):
        Pubkey.from_string(v)
        return v


class Verify(Strict):
    challenge_id: str = Field(min_length=32, max_length=64)
    signature: str = Field(min_length=64, max_length=88)


class Enrollment(Wallet):
    worker: bool = False
    reviewer: bool = False


class Category(Strict):
    id: int = Field(strict=True, ge=0, le=65535)
    name: str = Field(min_length=1, max_length=80)


class CreateBounty(Strict):
    title: str = Field(min_length=3, max_length=160)
    categories: list[Category] = Field(min_length=1, max_length=50)
    reward_usdc_units: int = Field(strict=True, ge=1, le=1_000_000_000)
    slots: int = Field(strict=True, ge=1, le=100)
    deadline: int = Field(strict=True)

    @model_validator(mode="after")
    def unique_categories(self):
        if len({c.id for c in self.categories}) != len(self.categories):
            raise ValueError("Category IDs must be unique")
        return self


class Box(Strict):
    category_id: int = Field(strict=True, ge=0)
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def contained(self):
        if self.x + self.w > 1.0000001 or self.y + self.h > 1.0000001:
            raise ValueError("Box exceeds image")
        return self


class Labels(Strict):
    media_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    boxes: list[Box] = Field(min_length=1, max_length=100)


class Confirm(Strict):
    signature: str = Field(min_length=64, max_length=88)


def iou(a, b):
    intersection = max(
        0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    ) * max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return intersection / (a["w"] * a["h"] + b["w"] * b["h"] - intersection)


def agree(left, right):
    """One-to-one category+IoU matching; ordering and duplicate boxes cannot pad votes."""
    if len(left) != len(right):
        return False
    edges = [
        [
            j
            for j, b in enumerate(right)
            if a["category_id"] == b["category_id"] and iou(a, b) >= 0.7
        ]
        for a in left
    ]
    matched = {}

    def augment(i, seen):
        for j in edges[i]:
            if j not in seen:
                seen.add(j)
                if j not in matched or augment(matched[j], seen):
                    matched[j] = i
                    return True
        return False

    return all(augment(i, set()) for i in range(len(left)))
