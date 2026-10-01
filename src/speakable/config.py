from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://ai-policy-proxy:18443/v1"
    model: str = "ai-policy/public"
    api_key_file: Path = Path("/run/secrets/speakable_cpa_key")
    timeout_seconds: float = 90
    max_input_characters: int = Field(default=40_000, ge=1_000)
    fallback: Literal["convert", "drop"] = "convert"


class ConversionConfig(BaseModel):
    symbol_map: dict[str, str] = {
        "➡️": " to ",
        "→": " to ",
        "➔": " to ",
        "➜": " to ",
        "➡": " to ",
        "⟶": " to ",
        "↦": " to ",
        "->": " to ",
        "⇒": " implies ",
        "⟹": " implies ",
        "=>": " implies ",
        "<->": " maps to ",
        "↔": " maps to ",
        "⟷": " maps to ",
        "&": " and ",
    }
    citation_headings: list[str] = ["sources", "references", "citations"]
    max_body_bytes: int = Field(default=262_144, ge=1_024)
    max_request_characters: int = Field(default=160_000, ge=1_000)


class AppConfig(BaseModel):
    llm: LlmConfig = LlmConfig()
    conversion: ConversionConfig = ConversionConfig()


def load_config() -> AppConfig:
    path = Path(os.environ.get("SPEAKABLE_CONFIG", "/app/config.yaml"))
    if not path.exists():
        return AppConfig()
    return AppConfig.model_validate(yaml.safe_load(path.read_text()) or {})
