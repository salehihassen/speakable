from pathlib import Path

import pytest

from speakable.config import AppConfig, LlmConfig
from speakable.converter import _extract_blocks, _parse_llm_json, convert


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(llm=LlmConfig(enabled=False, fallback="convert", api_key_file=Path("/missing")))


@pytest.mark.asyncio
async def test_plain_markdown_and_citations(config: AppConfig):
    source = """# Answer

- Go from A -> B with [the guide](https://example.com).[1]
- Use **carefully**.

## Sources
- [1] https://example.com
"""
    result = await convert(source, config)
    assert result.text == "Answer\n\nGo from A to B with the guide.\nUse carefully."
    assert not result.used_llm


def test_extracts_code_and_table_without_keep_path():
    source = """Before.

```python
print('hi')
```

| Name | Value |
| --- | --- |
| One | 1 |

After.
"""
    template, blocks = _extract_blocks(source)
    assert [block.kind for block in blocks] == ["code", "table"]
    assert all(block.content not in template for block in blocks)


@pytest.mark.asyncio
async def test_local_fallback_never_keeps_raw_code(config: AppConfig):
    result = await convert("```python\nprint('secret')\n```", config)
    assert result.text == "A code example was omitted."
    assert "print" not in result.text


@pytest.mark.asyncio
async def test_table_fallback_converts_to_prose(config: AppConfig):
    result = await convert("| Name | Value |\n| --- | --- |\n| One | 1 |", config)
    assert result.text == "Name: One; Value: 1."


def test_model_json_may_be_fenced_or_prefaced():
    parsed = _parse_llm_json('Here is the result:\n```json\n{"replacements": []}\n```')
    assert parsed == {"replacements": []}


@pytest.mark.asyncio
async def test_preserves_paragraph_and_passage_separations(config: AppConfig):
    source = "First paragraph.\n\nSecond paragraph.\nStill the second passage.\n\n\nThird paragraph."
    result = await convert(source, config)
    assert result.text == (
        "First paragraph.\n\n"
        "Second paragraph.\nStill the second passage.\n\n"
        "Third paragraph."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_llm", [False, True])
async def test_unicode_arrows_are_spoken_in_both_modes(config: AppConfig, use_llm: bool):
    source = "consulting → repeated customer pain → reusable solution → product"
    result = await convert(source, config, use_llm=use_llm)
    assert result.text == (
        "consulting to repeated customer pain to reusable solution to product"
    )


@pytest.mark.asyncio
async def test_removes_file_mentions(config: AppConfig):
    source = """I updated `src/speakable/converter.py:42` and config.yaml.
Logs live in /var/log/app (~/notes/todo.md), and `scripts/run` was unchanged.
Use it for input and/or output, 24/7, e.g. on Node."""
    result = await convert(source, config)
    assert result.text == (
        "I updated and.\nLogs live in, and was unchanged.\n"
        "Use it for input and/or output, 24/7, e.g. on Node."
    )
