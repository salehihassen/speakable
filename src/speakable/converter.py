from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from .config import AppConfig


@dataclass(frozen=True)
class Block:
    id: str
    kind: str
    content: str


@dataclass(frozen=True)
class ConversionResult:
    text: str
    used_llm: bool
    block_count: int
    warnings: tuple[str, ...] = ()


FENCE_RE = re.compile(r"```(?:[^\n]*)\n(.*?)```", re.DOTALL)
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _remove_citation_sections(text: str, headings: list[str]) -> str:
    lines = text.splitlines()
    output: list[str] = []
    skipping_level: int | None = None
    wanted = {heading.casefold() for heading in headings}
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = re.sub(r"[*_`]", "", match.group(2)).strip().casefold()
            if skipping_level is not None and level <= skipping_level:
                skipping_level = None
            if title in wanted:
                skipping_level = level
                continue
        if skipping_level is None:
            output.append(line)
    return "\n".join(output)


def _extract_blocks(text: str) -> tuple[str, list[Block]]:
    blocks: list[Block] = []

    def replace_fence(match: re.Match[str]) -> str:
        block = Block(f"SPEAKABLEBLOCK{len(blocks)}TOKEN", "code", match.group(1).strip())
        blocks.append(block)
        return f"\n{block.id}\n"

    text = FENCE_RE.sub(replace_fence, text)
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if index + 1 < len(lines) and "|" in lines[index] and TABLE_DIVIDER_RE.match(lines[index + 1]):
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            block = Block(f"SPEAKABLEBLOCK{len(blocks)}TOKEN", "table", "\n".join(table_lines))
            blocks.append(block)
            output.append(block.id)
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output), blocks


def _table_fallback(content: str) -> str:
    rows = []
    for line in content.splitlines():
        if TABLE_DIVIDER_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return ""
    headers = rows[0]
    sentences = []
    for row in rows[1:]:
        pairs = [f"{header}: {value}" for header, value in zip(headers, row, strict=False) if value]
        if pairs:
            sentences.append("; ".join(pairs) + ".")
    return " ".join(sentences)


def _fallback(block: Block, mode: str) -> str:
    if mode == "drop":
        return ""
    if block.kind == "table":
        return _table_fallback(block.content)
    # Code cannot safely pass through unchanged. A short omission is speakable.
    return "A code example was omitted."


def _parse_llm_json(content: str) -> dict:
    """Accept plain JSON or JSON wrapped in a model's prose/code fence."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
    start = content.find("{")
    if start < 0:
        raise ValueError("Model response did not contain a JSON object")
    parsed, _ = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON was not an object")
    return parsed


def _local_markdown_to_text(text: str, symbol_map: dict[str, str]) -> str:
    # Footnotes, numeric citation markers, and raw citation URLs.
    text = re.sub(r"(?m)^[ \t]*\[[^\]]+\]:[ \t]+\S+.*$", "", text)
    text = re.sub(r"(?<!\w)\[(?:\d+(?:\s*[,;-]\s*\d+)*)\]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", text)
    text = re.sub(r"(?m)^[ \t]*>[ \t]?", "", text)
    text = re.sub(r"(?m)^[ \t]*(?:[-+*]|\d+[.)])[ \t]+", "", text)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    for symbol in sorted(symbol_map, key=len, reverse=True):
        text = text.replace(symbol, symbol_map[symbol])
    text = re.sub(r"[ \t]+", " ", text)
    # Trim horizontal whitespace at line edges without consuming blank lines;
    # those paragraph and passage boundaries are useful in both the UI and TTS.
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _llm_replacements(
    surrounding_text: str, blocks: list[Block], config: AppConfig
) -> dict[str, str]:
    key = config.llm.api_key_file.read_text().strip()
    block_payload = [
        {"id": block.id, "kind": block.kind, "content": block.content} for block in blocks
    ]
    prompt = {
        "task": (
            "For every block, choose exactly one action: convert or drop. Convert only when the "
            "content contributes useful meaning, rewriting it as concise natural prose suitable "
            "for text-to-speech. Drop boilerplate, low-value code, or content that is not useful "
            "when heard. Never preserve Markdown, code syntax, table formatting, citations, URLs, "
            "or a block verbatim. Return JSON only."
        ),
        "output_schema": {
            "replacements": [
                {"id": "the supplied block id", "action": "convert or drop", "text": "spoken prose; empty when dropped"}
            ]
        },
        "surrounding_text": surrounding_text[: config.llm.max_input_characters],
        "blocks": block_payload,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": config.llm.model,
        "messages": [
            {"role": "system", "content": "You edit text for listening. Obey the JSON schema exactly."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=config.llm.timeout_seconds) as client:
        response = await client.post(
            f"{config.llm.base_url.rstrip('/')}/chat/completions", headers=headers, json=payload
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    parsed = _parse_llm_json(content)
    valid_ids = {block.id for block in blocks}
    replacements: dict[str, str] = {}
    for item in parsed.get("replacements", []):
        block_id = item.get("id")
        action = item.get("action")
        if block_id not in valid_ids or action not in {"convert", "drop"}:
            continue
        replacements[block_id] = "" if action == "drop" else str(item.get("text", "")).strip()
    return replacements


async def convert(source: str, config: AppConfig, use_llm: bool = True) -> ConversionResult:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source = _remove_citation_sections(source, config.conversion.citation_headings)
    template, blocks = _extract_blocks(source)
    replacements: dict[str, str] = {}
    warnings: list[str] = []
    used_llm = False
    if blocks and use_llm and config.llm.enabled:
        try:
            replacements = await _llm_replacements(template, blocks, config)
            used_llm = True
        except (OSError, KeyError, ValueError, httpx.HTTPError) as error:
            warnings.append(f"LLM unavailable; used {config.llm.fallback} fallback ({type(error).__name__}).")
    for block in blocks:
        replacement = replacements.get(block.id, _fallback(block, config.llm.fallback))
        template = template.replace(block.id, replacement)
    return ConversionResult(
        text=_local_markdown_to_text(template, config.conversion.symbol_map),
        used_llm=used_llm,
        block_count=len(blocks),
        warnings=tuple(warnings),
    )
