from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .config import AppConfig, load_config
from .converter import convert


class ConvertRequest(BaseModel):
    text: str = Field(min_length=1)
    use_llm: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config()
    yield


app = FastAPI(title="Speakable", version="0.1.0", lifespan=lifespan)


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@app.middleware("http")
async def limit_conversion_request_body(request: Request, call_next):
    if request.method == "POST" and request.url.path.startswith("/api/v1/convert"):
        content_length = request.headers.get("content-length")
        if content_length is None:
            return JSONResponse(
                {"detail": "Content-Length is required"}, status_code=411
            )
        try:
            body_bytes = int(content_length)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if body_bytes > _config(request).conversion.max_body_bytes:
            return JSONResponse({"detail": "Request body is too large"}, status_code=413)
    return await call_next(request)


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


async def _run(payload: ConvertRequest, request: Request):
    config = _config(request)
    if len(payload.text) > config.conversion.max_request_characters:
        raise HTTPException(status_code=413, detail="Input is too large")
    return await convert(payload.text, config, payload.use_llm)


@app.post("/api/v1/convert", response_class=PlainTextResponse)
async def convert_plain(payload: ConvertRequest, request: Request) -> PlainTextResponse:
    result = await _run(payload, request)
    headers = {
        "X-Speakable-LLM-Used": str(result.used_llm).lower(),
        "X-Speakable-Block-Count": str(result.block_count),
    }
    if result.warnings:
        headers["X-Speakable-Warning"] = result.warnings[0][:512]
    return PlainTextResponse(result.text, headers=headers)


@app.post("/api/v1/convert/details")
async def convert_details(payload: ConvertRequest, request: Request) -> JSONResponse:
    result = await _run(payload, request)
    return JSONResponse(
        {
            "text": result.text,
            "used_llm": result.used_llm,
            "block_count": result.block_count,
            "warnings": list(result.warnings),
        }
    )


INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Speakable</title>
  <style>
    :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #111827; color: #f9fafb; }
    main { width: min(70rem, calc(100% - 2rem)); margin: 3rem auto; }
    h1 { margin-bottom: .25rem; }
    p { color: #cbd5e1; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    textarea { box-sizing: border-box; width: 100%; min-height: 55vh; resize: vertical; padding: 1rem;
      border: 1px solid #475569; border-radius: .75rem; background: #0f172a; color: #f8fafc;
      font: 1rem/1.55 ui-monospace, monospace; }
    .actions { display: flex; align-items: center; gap: .75rem; margin: 1rem 0; flex-wrap: wrap; }
    button { border: 0; border-radius: .6rem; padding: .7rem 1rem; font-weight: 700; cursor: pointer; }
    #convert { background: #38bdf8; color: #082f49; }
    #copy { background: #334155; color: #f8fafc; }
    #status { color: #94a3b8; }
    @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } main { margin-top: 1.5rem; } }
  </style>
</head>
<body><main>
  <h1>Speakable</h1>
  <p>Turn a ChatGPT response into clean plain text for listening.</p>
  <div class="actions">
    <button id="convert" type="button">Convert</button>
    <button id="copy" type="button">Copy result</button>
    <label><input id="llm" type="checkbox" checked> Let AI convert or drop tables and code</label>
    <span id="status" role="status"></span>
  </div>
  <div class="grid">
    <textarea id="source" aria-label="Markdown input" placeholder="Paste the ChatGPT response here..."></textarea>
    <textarea id="result" aria-label="Plain text output" readonly placeholder="TTS-friendly plain text appears here..."></textarea>
  </div>
</main>
<script>
const source = document.querySelector('#source');
const result = document.querySelector('#result');
const status = document.querySelector('#status');
document.querySelector('#convert').addEventListener('click', async () => {
  if (!source.value.trim()) return;
  status.textContent = 'Converting…';
  try {
    const response = await fetch('/api/v1/convert', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: source.value, use_llm: document.querySelector('#llm').checked})
    });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    result.value = await response.text();
    const used = response.headers.get('X-Speakable-LLM-Used') === 'true';
    const blocks = Number(response.headers.get('X-Speakable-Block-Count') || 0);
    status.textContent = blocks ? `${blocks} complex block${blocks === 1 ? '' : 's'} processed${used ? ' with AI' : ' locally'}.` : 'Converted locally.';
  } catch (error) { status.textContent = error.message; }
});
document.querySelector('#copy').addEventListener('click', async () => {
  await navigator.clipboard.writeText(result.value); status.textContent = 'Copied.';
});
</script></body></html>'''
