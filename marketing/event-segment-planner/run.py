"""
Event Segment Planner – local web UI
Uses the Anthropic Python SDK directly (no claude subprocess).

Setup:
  1. Copy .env.example to .env and add your ANTHROPIC_API_KEY
  2. Run: .venv\Scripts\python run.py
  3. Open: http://localhost:8081
"""

import json
import os
import queue
import threading
import webbrowser
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv
from flask import Flask, Response, request

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
_jobs: dict[str, queue.Queue] = {}

# ── Anthropic client (key from .env or environment) ───────────────────────────
def _make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to the .env file.")
    return anthropic.Anthropic(api_key=key)


# ── Tools exposed to Claude ───────────────────────────────────────────────────
TOOLS = [
    {
        "name": "web_fetch",
        "description": (
            "Fetch the contents of a public web page. "
            "Use this to scrape the Linux Foundation event page for event details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
    }
]


def _execute_tool(name: str, tool_input: dict) -> str:
    """Run a tool call requested by Claude and return the result as a string."""
    if name == "web_fetch":
        url = tool_input.get("url", "")
        try:
            r = httpx.get(
                url,
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LFSegmentPlanner/1.0)"},
            )
            r.raise_for_status()
            # Return first 12 000 chars — enough for an event page
            return r.text[:12_000]
        except Exception as exc:
            return f"Error fetching {url}: {exc}"
    return f"Unknown tool: {name}"


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM = """You are an expert Linux Foundation email audience strategist with deep knowledge
of HubSpot list structures, the LF event portfolio, and the organisation's segmentation patterns.

You have access to a web_fetch tool to retrieve event pages. Use it in Step 1.

For Steps 2-3, you will not have live HubSpot or Snowflake access — draw on your knowledge of
LF's typical segmentation patterns and clearly flag any list names or counts you cannot verify.

Write the full Segment Plan Report in the exact format specified, section by section.
Always end with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""

USER_PROMPT = """Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Follow the event-segment-planner skill instructions exactly, working through all 4 steps:

**Step 1** — Use web_fetch to scrape the event page. Extract: event name, foundation/brand,
location, dates, year, event type.

**Step 2** — Search your knowledge of prior HubSpot email sends for this event series.
Note: you do not have live HubSpot access, so document what you know and flag anything unverified.

**Step 3** — Reconstruct the inclusion sources, exclusion/suppression lists, and opt-in filter
logic used for this event historically (or the closest comparable event if new).

**Step 4** — Write the complete Segment Plan Report in the standard format:
- Event summary
- Historical context (prior master list name, send counts, changes)
- Recommended master list name (following LF naming convention)
- Inclusion strategy (past registrants, web visitors, geo, topic, foundation subs)
- Exclusion strategy (LF Events Global Opt Outs, GDPR suppression, current registrants, etc.)
- Opt-in filter recommendation
- Estimated list size
- Recommended HubSpot filter group sketch
- Open questions / flags

End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""


# ── Agentic loop: stream Claude + handle tool calls ──────────────────────────
def _run_agent(job_id: str, url: str, q: queue.Queue):
    try:
        client = _make_client()
    except RuntimeError as exc:
        q.put({"type": "output", "text": f"❌ {exc}"})
        q.put({"type": "done", "done": True, "success": False})
        return

    messages = [{"role": "user", "content": USER_PROMPT.format(url=url)}]

    def emit(text: str):
        if text:
            q.put({"type": "output", "text": text})

    try:
        while True:
            # Stream the response
            full_text = ""
            tool_calls = []

            with client.messages.stream(
                model="claude-opus-4-5",
                max_tokens=8096,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                current_tool = None

                for event in stream:
                    # Text delta — stream to browser immediately
                    if hasattr(event, "type"):
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "tool_use":
                                current_tool = {"id": block.id, "name": block.name, "input_raw": ""}
                                emit(f"\n🔧 Calling tool: **{block.name}**\n")
                            elif block.type == "text":
                                current_tool = None

                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "text"):
                                full_text += delta.text
                                emit(delta.text)
                            elif hasattr(delta, "partial_json"):
                                if current_tool:
                                    current_tool["input_raw"] += delta.partial_json

                        elif event.type == "content_block_stop":
                            if current_tool:
                                try:
                                    current_tool["input"] = json.loads(current_tool["input_raw"] or "{}")
                                except Exception:
                                    current_tool["input"] = {}
                                tool_calls.append(current_tool)
                                current_tool = None

                stop_reason = stream.get_final_message().stop_reason

            # No tool calls → we're done
            if not tool_calls or stop_reason == "end_turn":
                break

            # Execute each tool call and feed results back
            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })

            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in tool_calls:
                emit(f"  → Fetching: {tc['input'].get('url','')}\n")
                result = _execute_tool(tc["name"], tc["input"])
                emit(f"  ✓ Got {len(result)} chars\n\n")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        q.put({"type": "done", "done": True, "success": True})

    except Exception as exc:
        emit(f"\n\n❌ Error: {exc}")
        q.put({"type": "done", "done": True, "success": False})


# ── Flask routes ──────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Event Segment Planner</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --blue:#003366; --teal:#009cde; --light:#e8f4fb;
      --idle:#d1d5db; --active:#f59e0b; --done:#10b981; --err:#ef4444;
      --bg:#f9fafb; --card:#fff; --border:#e5e7eb; --muted:#6b7280;
    }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
           background:var(--bg); min-height:100vh; padding:2rem 1rem; }

    header { max-width:860px; margin:0 auto 1.75rem; display:flex; align-items:center; gap:1rem; }
    .logo { width:48px; height:48px; background:var(--blue); border-radius:10px;
            display:flex; align-items:center; justify-content:center; flex-shrink:0; }
    .logo svg { width:26px; height:26px; fill:none; stroke:#fff; stroke-width:2;
                stroke-linecap:round; stroke-linejoin:round; }
    header h1 { font-size:1.35rem; font-weight:700; color:var(--blue); }
    header p  { font-size:.83rem; color:var(--muted); margin-top:3px; }

    .card { background:var(--card); border:1px solid var(--border); border-radius:12px;
            padding:1.5rem; max-width:860px; margin:0 auto 1.25rem;
            box-shadow:0 1px 4px rgba(0,0,0,.06); }

    /* api key warning */
    #key-warn { background:#fff7ed; border:1.5px solid #fed7aa; border-radius:8px;
                padding:.75rem 1rem; font-size:.82rem; color:#9a3412; margin-bottom:1rem;
                display:none; }

    .row { display:flex; gap:.75rem; }
    input[type=url],input[type=text],input[type=password] {
      flex:1; padding:.65rem 1rem; border:1.5px solid var(--border);
      border-radius:8px; font-size:.95rem; outline:none; transition:border-color .15s; }
    input:focus { border-color:var(--teal); }
    .hint { font-size:.78rem; color:var(--muted); margin-top:.45rem; }

    button { padding:.65rem 1.4rem; background:var(--blue); color:#fff; border:none;
             border-radius:8px; font-size:.9rem; font-weight:600; cursor:pointer;
             transition:background .15s; white-space:nowrap; }
    button:hover:not(:disabled) { background:#00407a; }
    button:disabled { opacity:.5; cursor:not-allowed; }
    .btn-outline { background:transparent; color:var(--blue); border:1.5px solid var(--blue); }
    .btn-outline:hover:not(:disabled) { background:var(--light); }
    .btn-teal { background:var(--teal); }
    .btn-teal:hover:not(:disabled) { background:#007bb0; }
    .btn-sm { padding:.35rem .9rem; font-size:.8rem; }

    /* Steps */
    .steps-wrap { margin-bottom:1.5rem; }
    .steps { display:flex; position:relative; margin-bottom:1rem; }
    .steps::before { content:""; position:absolute; top:18px; left:32px; right:32px;
                     height:2px; background:var(--idle); z-index:0; }
    .step { flex:1; display:flex; flex-direction:column; align-items:center;
            gap:.35rem; position:relative; z-index:1; }
    .bubble { width:36px; height:36px; border-radius:50%; background:var(--idle); color:#fff;
              font-weight:700; font-size:.85rem; display:flex; align-items:center;
              justify-content:center; transition:background .3s, transform .25s; }
    .step.active .bubble {
      background:var(--active); transform:scale(1.18);
      animation:pulse-ring 1.5s ease-out infinite;
    }
    @keyframes pulse-ring {
      0%   { box-shadow:0 0 0 0   rgba(245,158,11,.45); }
      70%  { box-shadow:0 0 0 10px rgba(245,158,11,0);  }
      100% { box-shadow:0 0 0 0   rgba(245,158,11,0);   }
    }
    .step.done  .bubble { background:var(--done); animation:none; transform:scale(1); }
    .step.done  .bubble::after { content:"✓"; }
    .step.done  .bubble span { display:none; }
    .step.error .bubble { background:var(--err); animation:none; }
    .step-label { font-size:.68rem; color:var(--muted); text-align:center;
                  line-height:1.3; max-width:90px; }
    .step.active .step-label { color:var(--active); font-weight:700; }
    .step.done   .step-label { color:var(--done);   font-weight:600; }

    .step-details { display:grid; grid-template-columns:repeat(4,1fr); gap:.75rem; }
    .step-detail { border:1.5px solid var(--border); border-radius:8px; padding:.75rem;
                   font-size:.77rem; transition:border-color .3s, background .3s; }
    .step-detail .sd-num   { font-size:.65rem; font-weight:700; color:var(--muted);
                              text-transform:uppercase; letter-spacing:.04em; margin-bottom:.2rem; }
    .step-detail .sd-title { font-weight:700; color:#374151; margin-bottom:.25rem; }
    .step-detail .sd-body  { color:var(--muted); line-height:1.45; }
    .step-detail.active { border-color:var(--active); background:#fffbeb; }
    .step-detail.active .sd-num   { color:var(--active); }
    .step-detail.active .sd-title { color:#92400e; }
    .step-detail.active .sd-body  { color:#374151; }
    .step-detail.done   { border-color:var(--done); background:#f0fdf4; }
    .step-detail.done   .sd-num   { color:var(--done); }
    .step-detail.done   .sd-title { color:#065f46; }
    .step-detail.error  { border-color:var(--err); }

    /* Activity line */
    #activity-wrap { display:flex; align-items:center; gap:.6rem; margin:.6rem 0;
                     min-height:26px; }
    #activity-icon { font-size:1rem; flex-shrink:0; }
    #activity-text { font-size:.82rem; color:#374151; flex:1; font-style:italic;
                     overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
    #activity-text.idle { color:var(--muted); }
    .dots::after { content:""; animation:dots 1.4s steps(4,end) infinite; }
    @keyframes dots { 0%{content:""} 25%{content:"."} 50%{content:".."} 75%{content:"..."} }

    /* Report */
    #report-panel { display:none; margin-top:.75rem; }
    #report-toolbar { display:flex; justify-content:space-between; align-items:center;
                      margin-bottom:.6rem; flex-wrap:wrap; gap:.5rem; }
    #report-toolbar span { font-weight:600; font-size:.9rem; color:var(--blue); }
    .tabs { display:flex; gap:4px; }
    .tab { padding:.3rem .85rem; border-radius:6px; border:1.5px solid var(--border);
           background:transparent; color:var(--muted); font-size:.8rem; font-weight:600; cursor:pointer; }
    .tab.active { background:var(--blue); color:#fff; border-color:var(--blue); }

    #report-md { border:1px solid var(--border); border-radius:8px; padding:1.5rem;
                 max-height:500px; overflow-y:auto; font-size:.88rem; line-height:1.75; }
    #report-md h1,#report-md h2,#report-md h3 { color:var(--blue); margin:1.1rem 0 .4rem; }
    #report-md h3 { font-size:1rem; }
    #report-md p  { margin-bottom:.6rem; }
    #report-md ul,#report-md ol { margin:.4rem 0 .6rem 1.5rem; }
    #report-md li { margin-bottom:.3rem; }
    #report-md strong { color:var(--blue); }
    #report-md hr { border:none; border-top:1px solid var(--border); margin:1rem 0; }
    #report-md code { background:#f1f5f9; padding:.1rem .35rem; border-radius:4px; font-size:.82rem; }
    #report-md blockquote { border-left:3px solid var(--teal); padding-left:.75rem; color:var(--muted); }

    #report-raw { display:none; background:#0f172a; color:#cbd5e1; border-radius:8px;
                  padding:1rem; font-family:"Cascadia Code","Fira Code",monospace;
                  font-size:.76rem; line-height:1.65; max-height:500px; overflow-y:auto;
                  white-space:pre-wrap; word-break:break-word; }

    #action-btns { display:none; gap:.75rem; flex-wrap:wrap; margin-top:1rem; }

    #toast { position:fixed; bottom:1.5rem; right:1.5rem; background:#1e293b; color:#e2e8f0;
             padding:.6rem 1.1rem; border-radius:8px; font-size:.82rem; opacity:0;
             transition:opacity .3s; pointer-events:none; z-index:99; }
    #toast.show { opacity:1; }

    @keyframes spin { to { transform:rotate(360deg); } }
    .spin { display:inline-block; width:13px; height:13px;
            border:2px solid rgba(255,255,255,.3); border-top-color:#fff;
            border-radius:50%; animation:spin .7s linear infinite;
            vertical-align:middle; margin-right:5px; }
  </style>
</head>
<body>

<header>
  <div class="logo">
    <svg viewBox="0 0 24 24">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
    </svg>
  </div>
  <div>
    <h1>Event Segment Planner</h1>
    <p>Research and plan the HubSpot audience segment for any Linux Foundation event</p>
  </div>
</header>

<!-- Input card -->
<div class="card" id="input-card">
  <div id="key-warn">⚠️ No API key configured. Add <code>ANTHROPIC_API_KEY=sk-…</code> to the <code>.env</code> file in the event-segment-planner folder, then restart.</div>

  <!-- API key field (shown only if not set server-side) -->
  <div id="key-row" style="display:none; margin-bottom:.75rem;">
    <div class="row">
      <input type="password" id="api-key" placeholder="sk-ant-… (paste Anthropic API key)" />
      <button class="btn-outline" onclick="saveKey()">Save key</button>
    </div>
    <p class="hint">Key is stored only for this browser session and sent only to your local server.</p>
  </div>

  <div class="row">
    <input type="url" id="url"
      placeholder="https://events.linuxfoundation.org/confidential-computing-summit/" />
    <button id="go-btn" onclick="start()">Plan Segment</button>
  </div>
  <p class="hint">Paste any events.linuxfoundation.org URL — Claude will scrape the page and produce a full segment plan.</p>
</div>

<!-- Progress card -->
<div class="card" id="prog-card" style="display:none">
  <div class="steps-wrap">
    <div class="steps">
      <div class="step" id="s1"><div class="bubble"><span>1</span></div><div class="step-label">Scrape<br>event page</div></div>
      <div class="step" id="s2"><div class="bubble"><span>2</span></div><div class="step-label">Find prior<br>sends</div></div>
      <div class="step" id="s3"><div class="bubble"><span>3</span></div><div class="step-label">Analyse<br>segmentation</div></div>
      <div class="step" id="s4"><div class="bubble"><span>4</span></div><div class="step-label">Write<br>plan</div></div>
    </div>
    <div class="step-details">
      <div class="step-detail" id="sd1">
        <div class="sd-num">Step 1</div>
        <div class="sd-title">Scrape event page</div>
        <div class="sd-body">Fetching page · extracting name, foundation, location, dates, type</div>
      </div>
      <div class="step-detail" id="sd2">
        <div class="sd-num">Step 2</div>
        <div class="sd-title">Prior HubSpot sends</div>
        <div class="sd-body">Searching prior email sends · checking LF Event Audiences OptIn tracking</div>
      </div>
      <div class="step-detail" id="sd3">
        <div class="sd-num">Step 3</div>
        <div class="sd-title">Analyse segmentation</div>
        <div class="sd-body">Reconstructing inclusion, exclusion &amp; opt-in filter logic from history</div>
      </div>
      <div class="step-detail" id="sd4">
        <div class="sd-num">Step 4</div>
        <div class="sd-title">Write segment plan</div>
        <div class="sd-body">Master list name · inclusion strategy · exclusions · size estimate · filter sketch</div>
      </div>
    </div>
  </div>

  <div id="activity-wrap">
    <span id="activity-icon">⏳</span>
    <span id="activity-text" class="idle dots">Waiting for Claude</span>
  </div>

  <div id="report-panel">
    <div id="report-toolbar">
      <span>📋 Segment Plan</span>
      <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;">
        <div class="tabs">
          <button class="tab active" onclick="showTab('md')">Formatted</button>
          <button class="tab"        onclick="showTab('raw')">Raw</button>
        </div>
        <button class="btn-teal btn-sm" onclick="copyReport()">Copy</button>
      </div>
    </div>
    <div id="report-md"></div>
    <div id="report-raw"></div>
  </div>

  <div id="action-btns">
    <button class="btn-outline" onclick="reset()">Plan another event</button>
    <button class="btn-teal"    onclick="buildLists()">Build HubSpot lists →</button>
  </div>
</div>

<div id="toast">Copied!</div>

<script>
  marked.setOptions({ breaks:true, gfm:true });

  const STEP_RE = [
    null,
    /step 1|scraping|fetching|web_fetch|event page|event name|event type|foundation|location|dates|extracting|calling tool/i,
    /step 2|prior send|previous edition|email send|hubspot|optIn|tracking|historical|found.*email|search.*email/i,
    /step 3|inclus|exclus|suppress|opt.in|filter logic|reconstruct|analysing|historical segment/i,
    /step 4|segment plan|recommended|master list|inclusion strategy|exclusion strategy|estimated|ready to proceed|filter group|open question/i,
  ];

  const STEP_ICONS  = ["","🔍","📧","🧩","📋"];
  const STEP_STATUS = ["","Scraping event page…","Searching prior sends…","Analysing segmentation…","Writing segment plan…"];

  let cur = 0, rawLog = "", es = null, hbTimer = null;
  let apiKeySession = "";

  // ── Check if server has API key configured
  fetch("/status").then(r=>r.json()).then(d=>{
    if (!d.has_key) {
      document.getElementById("key-warn").style.display = "block";
      document.getElementById("key-row").style.display  = "block";
    }
  });

  function saveKey() {
    apiKeySession = document.getElementById("api-key").value.trim();
    if (apiKeySession) {
      document.getElementById("key-warn").style.display = "none";
      document.getElementById("key-row").style.display  = "none";
    }
  }

  function setActivityIdle() {
    const el = document.getElementById("activity-text");
    el.className = "idle dots"; el.textContent = "Waiting for Claude";
    document.getElementById("activity-icon").textContent = "⏳";
  }

  function setActivity(text) {
    const t = text.trim();
    if (!t || t.length < 4) return;
    const el = document.getElementById("activity-text");
    el.className = ""; el.textContent = t.slice(0,140);
    document.getElementById("activity-icon").textContent = STEP_ICONS[cur] || "⚙️";
    clearTimeout(hbTimer);
    hbTimer = setTimeout(() => {
      if (cur > 0) { el.className = "dots"; el.textContent = STEP_STATUS[cur] || "Working"; }
    }, 8000);
  }

  async function start() {
    const url = document.getElementById("url").value.trim();
    if (!url) { alert("Please enter an event URL."); return; }

    setBtn(true, "Planning…");
    document.getElementById("input-card").style.display  = "none";
    document.getElementById("prog-card").style.display   = "block";
    document.getElementById("report-panel").style.display = "none";
    document.getElementById("action-btns").style.display  = "none";
    document.getElementById("report-md").innerHTML = "";
    document.getElementById("report-raw").textContent = "";
    rawLog = ""; cur = 0;
    for (let i=1;i<=4;i++) {
      document.getElementById("s"+i).className  = "step";
      document.getElementById("sd"+i).className = "step-detail";
    }
    setActivityIdle();

    const body = { url };
    if (apiKeySession) body.api_key = apiKeySession;

    const r = await fetch("/build", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(body)
    });
    if (!r.ok) {
      const err = await r.json().catch(()=>({error:"Unknown error"}));
      alert("Error: " + (err.error || r.status));
      setBtn(false, "Plan Segment");
      document.getElementById("input-card").style.display = "block";
      document.getElementById("prog-card").style.display  = "none";
      return;
    }
    const {job_id} = await r.json();

    es = new EventSource("/stream/" + job_id);
    es.onmessage = (e) => {
      const msg = JSON.parse(e.data);

      if (msg.type === "heartbeat") {
        if (cur > 0) {
          const el = document.getElementById("activity-text");
          if (!el.classList.contains("dots")) { el.className="dots"; el.textContent=STEP_STATUS[cur]||"Working"; }
        }
        return;
      }

      if (msg.type === "output" && msg.text !== undefined) {
        rawLog += msg.text;
        checkStep(msg.text);
        // Update activity with last non-empty line
        const lines = msg.text.split("\n").filter(l=>l.trim());
        if (lines.length) setActivity(lines[lines.length-1]);
        renderReport();
      }

      if (msg.done) {
        es.close(); clearTimeout(hbTimer);
        if (msg.success) {
          markDone(cur);
          document.getElementById("activity-icon").textContent = "✅";
          document.getElementById("activity-text").className = "";
          document.getElementById("activity-text").textContent = "Plan complete";
        } else {
          markErr(cur);
          document.getElementById("activity-icon").textContent = "⚠️";
          document.getElementById("activity-text").className = "";
          document.getElementById("activity-text").textContent = "Finished with errors";
        }
        setBtn(false, "Plan Segment");
        document.getElementById("action-btns").style.display = "flex";
      }
    };
    es.onerror = () => {
      es.close(); clearTimeout(hbTimer);
      document.getElementById("activity-text").textContent = "Connection lost";
      setBtn(false, "Plan Segment");
      document.getElementById("action-btns").style.display = "flex";
    };
  }

  function checkStep(text) {
    for (let i=1;i<=4;i++) {
      if (i>cur && STEP_RE[i] && STEP_RE[i].test(text)) { advance(i); break; }
    }
  }

  function advance(n) {
    if (n<=cur) return;
    if (cur>0) {
      document.getElementById("s"+cur).className  = "step done";
      document.getElementById("sd"+cur).className = "step-detail done";
    }
    cur = n;
    document.getElementById("s"+n).className  = "step active";
    document.getElementById("sd"+n).className = "step-detail active";
    const el = document.getElementById("activity-text");
    el.className = "dots"; el.textContent = STEP_STATUS[n]||"Working";
    document.getElementById("activity-icon").textContent = STEP_ICONS[n]||"⚙️";
  }

  function markDone(last) {
    for (let i=1;i<=last;i++) {
      document.getElementById("s"+i).className  = "step done";
      document.getElementById("sd"+i).className = "step-detail done";
    }
  }
  function markErr(n) {
    if (n>0) {
      document.getElementById("s"+n).className  = "step error";
      document.getElementById("sd"+n).className = "step-detail error";
    }
  }

  function renderReport() {
    document.getElementById("report-panel").style.display = "block";
    document.getElementById("report-md").innerHTML = marked.parse(rawLog);
    document.getElementById("report-raw").textContent = rawLog;
    const md = document.getElementById("report-md");
    md.scrollTop = md.scrollHeight;
  }

  function showTab(tab) {
    document.getElementById("report-md").style.display  = tab==="md"  ? "block":"none";
    document.getElementById("report-raw").style.display = tab==="raw" ? "block":"none";
    document.querySelectorAll(".tab").forEach((el,i)=>{
      el.classList.toggle("active",(i===0&&tab==="md")||(i===1&&tab==="raw"));
    });
  }

  function copyReport() {
    navigator.clipboard.writeText(rawLog).then(()=>{
      const t=document.getElementById("toast");
      t.classList.add("show"); setTimeout(()=>t.classList.remove("show"),2000);
    });
  }

  function buildLists() {
    window.open("http://localhost:8080?url="+encodeURIComponent(document.getElementById("url").value.trim()),"_blank");
  }

  function setBtn(disabled,label) {
    const b=document.getElementById("go-btn");
    b.disabled=disabled;
    b.innerHTML=disabled?`<span class="spin"></span>${label}`:label;
  }

  function reset() {
    document.getElementById("input-card").style.display="block";
    document.getElementById("prog-card").style.display="none";
    document.getElementById("url").value="";
    rawLog=""; cur=0; clearTimeout(hbTimer);
  }

  document.getElementById("url").addEventListener("keydown",e=>{if(e.key==="Enter")start();});
  const qs=new URLSearchParams(location.search);
  if(qs.get("url")) document.getElementById("url").value=qs.get("url");
</script>
</body>
</html>"""


@app.get("/status")
def status():
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    return {"has_key": has_key}


@app.get("/")
def index():
    return Response(HTML, mimetype="text/html")


@app.post("/build")
def build():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return {"error": "url required"}, 400

    # Allow passing API key from the browser during setup
    if data.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = data["api_key"]

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return {"error": "ANTHROPIC_API_KEY not set. Add it to the .env file."}, 400

    import uuid
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = q

    t = threading.Thread(target=_run_agent, args=(job_id, url, q), daemon=True)
    t.start()
    return {"job_id": job_id}


@app.get("/stream/<job_id>")
def stream(job_id: str):
    if job_id not in _jobs:
        def err():
            yield f"data: {json.dumps({'error':'not found','done':True})}\n\n"
        return Response(err(), mimetype="text/event-stream")

    def generate():
        q = _jobs[job_id]
        while True:
            try:
                item = q.get(timeout=3)
            except Exception:
                yield f"data: {json.dumps({'type':'heartbeat'})}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done"):
                _jobs.pop(job_id, None)
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    port = 8081
    print(f"\n  Event Segment Planner  →  http://localhost:{port}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ⚠  ANTHROPIC_API_KEY not set — add it to .env or paste in the browser UI\n")
    else:
        print("  ✓  API key loaded\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
