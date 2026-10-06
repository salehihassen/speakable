from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class LlmConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://ai-policy-proxy:18443/v1"
    model: str = "ai-policy/public"
    api_key_file: Path = Path("/run/secrets/speakable_cpa_key")
    timeout_seconds: float = 90
    max_input_characters: int = Field(default=40_000, ge=1_000)
    fallback: Literal["convert", "drop"] = "convert"


# Path segment whose dots must sit between word characters, so a sentence's
# final period is never swallowed into the match.
_SEGMENT = r"\.?[\w@-]+(?:\.[\w@-]+)*"
_EXTENSIONS = (
    r"(?:py|pyi|ipynb|js|mjs|cjs|ts|tsx|jsx|json|jsonl|ya?ml|toml|ini|cfg|conf|env|"
    r"md|mdx|rst|txt|csv|tsv|log|sh|bash|zsh|ps1|go|rs|java|kt|swift|c|h|cc|cpp|hpp|"
    r"cs|rb|php|lua|sql|html?|css|scss|vue|svelte|xml|lock|tf)"
)
_LINE_SUFFIX = r"(?::\d+(?:[:-]\d+)?)?"


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
    # Regexes removed from the text after Markdown links and URLs are stripped.
    # The defaults drop file mentions: names with a known extension (with any
    # directory prefix and :line suffix), explicit /, ./, ../ or ~/ paths, and
    # inline code containing a slash.
    remove_patterns: list[str] = [
        rf"(?<![\w/.-])`?(?:(?:~|\.{{1,2}})?/)?(?:{_SEGMENT}/)*{_SEGMENT}\.{_EXTENSIONS}{_LINE_SUFFIX}`?(?![\w/-])",
        rf"(?<![\w/.:-])`?(?:~|\.{{1,2}})?(?:/{_SEGMENT})+/?{_LINE_SUFFIX}`?(?![\w/])",
        r"`[^`\s]*/[^`\s]*`",
    ]
    max_body_bytes: int = Field(default=262_144, ge=1_024)
    max_request_characters: int = Field(default=160_000, ge=1_000)

    @field_validator("remove_patterns")
    @classmethod
    def _patterns_compile(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            re.compile(pattern)
        return patterns


class AppConfig(BaseModel):
    llm: LlmConfig = LlmConfig()
    conversion: ConversionConfig = ConversionConfig()


def load_config() -> AppConfig:
    path = Path(os.environ.get("SPEAKABLE_CONFIG", "/app/config.yaml"))
    if not path.exists():
        return AppConfig()
    return AppConfig.model_validate(yaml.safe_load(path.read_text()) or {})
