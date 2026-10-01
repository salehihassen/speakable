# Speakable

Speakable converts Markdown-heavy AI chat responses into plain text that works
well with external text-to-speech apps. It offers both a small web UI and a
plain-text HTTP API.

Ordinary Markdown cleanup, citation removal, and configurable symbol
pronunciation happen locally. Tables and fenced code can be sent to an
OpenAI-compatible model, which must either rewrite each block as spoken prose
or drop it. There is deliberately no keep-as-is action.

## Threat model

Speakable is intended for a single user or household on a trusted network such
as a LAN, VPN, or Tailscale network. The application has no user accounts,
authentication, authorization, or rate limiting. **Do not expose it directly to
the public internet.** An untrusted caller could submit repeated long-running
LLM requests, consume provider quota, and deny service to legitimate users.

If internet exposure is required, place Speakable behind a reverse proxy or
identity-aware gateway that provides authentication, rate limiting, TLS, and a
request-body limit. Treat the configured LLM credential as a secret and give it
only the provider permissions and quota the service needs.

The supplied container is designed to run as a non-root user. A production
deployment should additionally use a read-only root filesystem, drop Linux
capabilities, apply memory/CPU/PID limits, and bind the published port only to a
trusted interface or loopback address.

## LLM data sharing

When `use_llm` is `false`, conversion is entirely local and no document content
is sent to an inference provider.

When `use_llm` is `true`, the model is contacted only if the input contains a
recognized Markdown table or fenced code block. The request sends the extracted
tables/code **and up to `llm.max_input_characters` characters of surrounding
document text** to the configured OpenAI-compatible endpoint. The provider can
therefore receive substantially more than only the extracted block. It receives
this content as plaintext and applies its own logging, retention, training, and
human-review policies. Choose the endpoint accordingly and disable LLM use for
sensitive material unless that provider is appropriate for it.

The service does not intentionally persist submitted documents. Application or
reverse-proxy logging should likewise avoid recording request bodies.

## Request limits

The defaults allow a 256 KiB JSON request body and up to 160,000 characters of
document text. That is deliberately generous while remaining below roughly 100
typical book pages; actual page counts vary by formatting and language. Requests
larger than either limit receive HTTP `413`.

`conversion.max_body_bytes` protects the HTTP parsing boundary and
`conversion.max_request_characters` limits the extracted text. If changing
them, keep the byte limit large enough for JSON/UTF-8 overhead and configure the
same or a smaller limit at the reverse proxy.

## API

`POST /api/v1/convert` accepts JSON and returns `text/plain`:

```json
{"text":"# Answer\n\nA → B.[1]","use_llm":true}
```

For a Markdown file:

```bash
jq -Rs '{text: ., use_llm: true}' response.md |
  curl -fsS http://localhost:8000/api/v1/convert \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

`POST /api/v1/convert/details` accepts the same body and returns JSON with the
plain text, whether inference ran, the complex block count, and fallback
warnings. Interactive API documentation is available at `/docs`.

## Configuration

Copy `config.example.yaml` to the runtime configuration location. `symbol_map`
is applied longest-key-first. The LLM key is read from a mounted secret file,
never from YAML. If inference fails, `fallback: convert` turns tables into
simple row prose and replaces code with a spoken omission; `drop` removes both
kinds of block.

## Development

```bash
uv sync --locked --extra dev
uv run pytest
```

## License

Speakable is available under the [MIT License](LICENSE).
