"""Settings for AgentHire.

Product rules come from config.yaml and secrets come from .env. Nothing else in
the code base reads either file directly; everything asks for `get_settings()`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent


class CallingRules(BaseModel):
    hours_start: str
    hours_end: str
    timezone: str
    time_cap_seconds: int
    wrap_up_at_seconds: int
    screening_time_cap_seconds: int
    screening_wrap_up_at_seconds: int
    max_calls_per_job: int


class RankingWeights(BaseModel):
    rating: float
    review_count: float
    distance: float


class ProviderRules(BaseModel):
    max_shown: int
    search_radius_km: float
    wider_radius_km: float
    min_results: int
    call_top: int = 2
    ranking_weights: RankingWeights


class VoiceOption(BaseModel):
    model: str
    gender: Literal["male", "female"]


class VoiceSettings(BaseModel):
    agent_name: str
    stt_model: str
    stt_mode: str
    stt_language: str
    # The model that holds conversations is LLM_MODEL_SMART (in .env); this is how hard it
    # thinks before each reply. "low" was the fastest to its first words and the most careful
    # when measured on 22 Nov; "none" or "medium" are the alternatives.
    reasoning_effort: str = "low"
    voices: dict[str, VoiceOption]
    language_voice: dict[str, str]

    @model_validator(mode="after")
    def _every_language_has_a_known_voice(self) -> "VoiceSettings":
        for language, name in self.language_voice.items():
            if name not in self.voices:
                raise ValueError(f"language {language!r} uses voice {name!r}, which is not in voice.voices")
        return self

    def voice_for(self, language: str) -> tuple[str, VoiceOption]:
        """The voice name and its model and gender for a language code (te, hi, en)."""
        name = self.language_voice[language]
        return name, self.voices[name]

    def gender_for(self, language: str) -> str:
        return self.voice_for(language)[1].gender


class PhoneTurnTaking(BaseModel):
    min_endpointing_seconds: float
    max_endpointing_seconds: float
    min_interruption_seconds: float
    min_interruption_words: int
    greeting_delay_seconds: float


class LongAnswerTurnTaking(BaseModel):
    min_endpointing_seconds: float
    max_endpointing_seconds: float


class TurnTaking(BaseModel):
    phone: PhoneTurnTaking
    long_answers: LongAnswerTurnTaking
    unclear_turns_before_ending: int
    dead_air_seconds: float
    silence_seconds: float
    silence_prompts_before_ending: int


class Secrets(BaseModel):
    """Keys and deployment-specific values, all from .env."""

    openai_api_key: str = ""
    llm_model_fast: str = ""
    llm_model_smart: str = ""
    sarvam_api_key: str = ""
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_outbound_trunk_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    google_maps_api_key: str = ""
    avatar_provider: str = ""
    avatar_api_key: str = ""
    hindsight_api_key: str = ""
    hindsight_base_url: str = ""
    hindsight_bank_id: str = ""
    # Shared secret the voice worker sends when it posts events. Empty means
    # no check, which is fine on a laptop; set it before deploying.
    internal_api_token: str = ""


class AvatarSettings(BaseModel):
    """The real-time avatar shown in the voice brief (never on phone calls)."""
    enabled: bool = False
    provider: str = "synthesia"
    avatar_ids: list[str] = Field(default_factory=list)
    join_timeout_seconds: float = 12.0


class Settings(BaseModel):
    calling: CallingRules
    providers: ProviderRules
    voice: VoiceSettings
    turn_taking: TurnTaking
    avatar: AvatarSettings = Field(default_factory=AvatarSettings)
    secrets: Secrets
    test_mode: bool
    allowed_numbers: list[str]
    demo_route_phone: str
    demo_route_email: str
    database_path: Path


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: Path | None = None, env_path: Path | None = None) -> Settings:
    """Build settings from the two files. Tests pass their own paths."""
    load_dotenv(env_path or ROOT / ".env")
    rules = yaml.safe_load((config_path or ROOT / "config.yaml").read_text(encoding="utf-8"))

    secrets = Secrets(**{name: os.getenv(name.upper(), "") for name in Secrets.model_fields})
    allowed = [n.strip() for n in os.getenv("ALLOWED_NUMBERS", "").split(",") if n.strip()]
    database_path = Path(os.getenv("DATABASE_PATH", "data/agenthire.db"))
    if not database_path.is_absolute():
        database_path = ROOT / database_path

    return Settings(
        calling=rules["calling"],
        providers=rules["providers"],
        # AGENT_NAME lets a deployed server register its worker under its own name, so a
        # laptop's worker and the server's never take each other's calls.
        voice={**rules["voice"], **({"agent_name": os.environ["AGENT_NAME"]} if os.getenv("AGENT_NAME") else {})},
        turn_taking=rules["turn_taking"],
        avatar=rules.get("avatar", {}),
        secrets=secrets,
        # Test mode is on unless it is switched off explicitly, so a missing
        # setting can never lead to dialling a stranger.
        test_mode=_env_flag("TEST_MODE", default=True),
        allowed_numbers=allowed,
        demo_route_phone=os.getenv("DEMO_ROUTE_PHONE", ""),
        demo_route_email=os.getenv("DEMO_ROUTE_EMAIL", ""),
        database_path=database_path,
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
