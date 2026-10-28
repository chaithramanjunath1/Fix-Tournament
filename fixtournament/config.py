"""Settings, model tiers and cost accounting.

Model ids and prices are deliberately overridable: check the Token Factory model
catalogue for the exact Nemotron ids available to your account and set the
FT_MODEL_* variables accordingly. Prices are illustrative placeholders used for
the relative cost comparison in the UI, not billing data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR.parent / "web"
CASES_DIR = PKG_DIR / "cases"

TIERS: dict[str, dict] = {
    "nano": {"label": "Nano", "env": "FT_MODEL_NANO", "default": "nvidia/nemotron-3-nano", "price": (0.06, 0.24)},
    "super": {"label": "Super", "env": "FT_MODEL_SUPER", "default": "nvidia/nemotron-3-super", "price": (0.30, 0.90)},
    "ultra": {"label": "Ultra", "env": "FT_MODEL_ULTRA", "default": "nvidia/nemotron-3-ultra", "price": (0.60, 1.80)},
}


def model_for(tier: str) -> str:
    spec = TIERS[tier]
    return os.environ.get(spec["env"], spec["default"])


def price_for(tier: str) -> tuple[float, float]:
    raw = os.environ.get(f"FT_PRICE_{tier.upper()}")
    if raw:
        try:
            a, b = (float(x) for x in raw.split(","))
            return a, b
        except ValueError:
            pass
    return TIERS[tier]["price"]


def cost_usd(tier: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = price_for(tier)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    force_replay: bool
    replay_speed: float
    runner: str  # "local" or "job"
    job_cmd: str
    max_turns: int
    test_timeout: float
    allow_custom: bool
    github_token: str

    @property
    def live_available(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        api_key=env("NEBIUS_API_KEY", ""),
        base_url=env("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
        force_replay=env("FT_MODE", "").lower() == "replay",
        replay_speed=float(env("FT_REPLAY_SPEED", "1")),
        runner=env("FT_RUNNER", "local"),
        job_cmd=env("FT_JOB_SUBMIT_CMD", ""),
        max_turns=int(env("FT_MAX_TURNS", "3")),
        test_timeout=float(env("FT_TEST_TIMEOUT", "20")),
        allow_custom=env("FT_ALLOW_CUSTOM", "") == "1",
        github_token=env("FT_GITHUB_TOKEN", ""),
    )
