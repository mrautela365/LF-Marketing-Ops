import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="HubSpot Event List Builder")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

# In-memory job store: job_id -> asyncio.Queue
_jobs: dict[str, asyncio.Queue] = {}

STEP_PATTERNS = {
    1: re.compile(r"(scraping|fetching|event page|step 1|event name|edition|brand key)", re.I),
    2: re.compile(r"(snowflake|sql|event_registrations|past edition|step 2)", re.I),
    3: re.compile(r"(master list|brand master|list id|step 3)", re.I),
    4: re.compile(r"(clone|all past registrant|list 1|step 4|filter condition)", re.I),
    5: re.compile(r"(web visitor|list 2|registrant.*web|step 5|filter group)", re.I),
    6: re.compile(r"(confirm|report|created|list id.*\d{4,}|step 6|complete|both list)", re.I),
}

PROMPT_TEMPLATE = """Build the HubSpot event audience lists for this Linux Foundation event:

{url}

Follow the hubspot-event-list-builder skill instructions exactly. Work through all 6 steps:
1. Scrape the event page to extract name, edition, brand key, and Snowflake search terms
2. Query Snowflake for all past editions
3. Look up the brand master list ID
4. Clone the reference list and build List 1 (All Past Registrants)
5. Build List 2 (Registrants + Web Visitors)
6. Confirm and report both list IDs, names, and filter counts

Report your progress at each step."""


class BuildRequest(BaseModel):
    url: str


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (BASE_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/build")
async def start_build(req: BuildRequest):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = queue
    prompt = PROMPT_TEMPLATE.format(url=req.url.strip())
    asyncio.create_task(_run_claude(job_id, prompt, queue))
    return {"job_id": job_id}


@app.get("/stream/{job_id}")
async def stream(job_id: str):
    if job_id not in _jobs:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': 'Job not found'})}\n\n"]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _sse_generator(_jobs[job_id]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse_generator(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    while True:
        item = await queue.get()
        yield f"data: {json.dumps(item)}\n\n"
        if item.get("done"):
            break


async def _run_claude(job_id: str, prompt: str, queue: asyncio.Queue):
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--dangerously-skip-permissions",
            "-p",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(BASE_DIR),
        )

        active_step = 0
        buffer = ""

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            buffer += line + "\n"

            # Detect step transitions
            for step, pattern in STEP_PATTERNS.items():
                if step > active_step and pattern.search(line):
                    active_step = step
                    await queue.put({"type": "step", "step": step})
                    break

            await queue.put({"type": "output", "text": line})

        await proc.wait()
        success = proc.returncode == 0
        await queue.put({"type": "done", "done": True, "success": success, "step": active_step})

    except Exception as exc:
        await queue.put({"type": "error", "text": str(exc), "done": True, "success": False})
    finally:
        _jobs.pop(job_id, None)
