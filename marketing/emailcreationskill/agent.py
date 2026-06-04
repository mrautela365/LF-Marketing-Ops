"""
Agentic email staging workflow.

Three modes (auto-detected):
  SDK mode         : ANTHROPIC_API_KEY is set AND has credits → Anthropic Python SDK, full tool_use
  Deterministic    : No key / no credits → fixed 9-step Python workflow, no LLM needed
                     Asks the user only when required data is genuinely missing.
"""
import json
import platform
import re
import subprocess
from datetime import date
from typing import Any

from email_service.config import settings
from email_service.tools.hubspot import (
    search_brand_emails, get_email_details, clone_email,
    update_email_settings, update_email_content, get_hubspot_list, create_static_list,
)
from email_service.tools.asana_tool import get_asana_task
from email_service.tools.content import fetch_google_doc_html, validate_links

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert HubSpot email staging agent for Linux Foundation marketing ops.

Your job: given a minimal email request, fully stage a HubSpot marketing email as a DRAFT.

## Workflow (execute in order — use tools at each step)
1. If an Asana task URL is provided, call get_asana_task to extract all fields.
2. Call search_brand_emails to find the most recently sent email for the brand.
3. Call get_email_details on the last sent email to extract: from name, from address,
   suppression list IDs, email type, subscription type.
4. If a Google Doc URL is provided, call fetch_google_doc_html to get the content.
5. Derive the email name using convention: <YY><Q> - <Brand> - <Type> - <Month/Event>
   (e.g. "26Q2 - OpenSSF - Newsletter - June"). Quarter: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec.
6. Call clone_email with the last sent email ID and the derived name.
7. Call update_email_settings with the new email ID to set subject, preview text,
   from name, from address, subscription type, send list, suppression lists.
8. Call update_email_content with the new email ID and the cleaned HTML body.
9. Call validate_links on the HTML to check for broken links.
10. Output your final JSON result.

## Rules
- NEVER schedule or send — always leave as DRAFT.
- Always apply all suppression lists from the brand's last sent email.
- If brand has no prior sent emails, ask the user for: from name, from address,
  subscription type, standard suppression list names.
- If a tool returns an error or access is denied, surface a precise question to the user.
- Do not ask for anything you can retrieve with a tool.

## Output format
When you complete the task output exactly this JSON block (no extra text):
```json
{"status":"complete","email_id":"<id>","email_name":"<name>","hubspot_url":"https://app.hubspot.com/email/8112310/edit/<id>/send-options","summary":{"subject":"<subject>","from":"<from_name> <<from_address>>","send_list":"<list name> (<N> contacts)","suppressions":["<list1>","<list2>"],"email_type":"<type>","status":"DRAFT"},"qa_checklist":[{"item":"Subject set","passed":true},{"item":"Preview text set","passed":true},{"item":"From name/address correct","passed":true},{"item":"Send list configured","passed":true},{"item":"Suppression lists applied","passed":true},{"item":"Content updated","passed":true},{"item":"Links validated","passed":true},{"item":"Naming convention followed","passed":true},{"item":"Email type correct","passed":true},{"item":"Status is DRAFT","passed":true}]}
```

If you need information from the user, output exactly:
```json
{"status":"needs_input","question":"<your specific question>"}
```
"""

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_asana_task",
        "description": "Fetch an Asana task by URL and extract email request fields (brand, content URL, subject, send date, audience, reviewers).",
        "input_schema": {
            "type": "object",
            "properties": {"task_url": {"type": "string"}},
            "required": ["task_url"],
        },
    },
    {
        "name": "search_brand_emails",
        "description": "Search HubSpot for sent emails matching a brand name, sorted by most recently sent.",
        "input_schema": {
            "type": "object",
            "properties": {"brand_name": {"type": "string"}},
            "required": ["brand_name"],
        },
    },
    {
        "name": "get_email_details",
        "description": "Get full HubSpot email metadata by ID: from name, from address, suppression list IDs, email type, subscription type.",
        "input_schema": {
            "type": "object",
            "properties": {"email_id": {"type": "string"}},
            "required": ["email_id"],
        },
    },
    {
        "name": "clone_email",
        "description": "Clone a HubSpot email. Returns the new email object with its unique ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "clone_name": {"type": "string"},
            },
            "required": ["email_id", "clone_name"],
        },
    },
    {
        "name": "update_email_settings",
        "description": "PATCH HubSpot email: subject, previewText, fromName, fromEmail, subscriptionTypeId, send list, suppression lists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "settings_dict": {"type": "object"},
            },
            "required": ["email_id", "settings_dict"],
        },
    },
    {
        "name": "update_email_content",
        "description": "Replace the body content of a HubSpot email draft with clean HTML.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "html": {"type": "string"},
            },
            "required": ["email_id", "html"],
        },
    },
    {
        "name": "get_hubspot_list",
        "description": "Look up a HubSpot contact list by name or numeric ID.",
        "input_schema": {
            "type": "object",
            "properties": {"list_name_or_id": {"type": "string"}},
            "required": ["list_name_or_id"],
        },
    },
    {
        "name": "create_static_list",
        "description": "Create a new static HubSpot contact list. Optionally provide a CSV file path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "csv_path": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "fetch_google_doc_html",
        "description": "Fetch a Google Doc by URL and return clean email-ready HTML.",
        "input_schema": {
            "type": "object",
            "properties": {"doc_url": {"type": "string"}},
            "required": ["doc_url"],
        },
    },
    {
        "name": "validate_links",
        "description": "Check all hyperlinks in HTML. Returns broken or suspicious links.",
        "input_schema": {
            "type": "object",
            "properties": {"html": {"type": "string"}},
            "required": ["html"],
        },
    },
]

TOOL_FUNCTIONS: dict[str, Any] = {
    "get_asana_task": get_asana_task,
    "search_brand_emails": search_brand_emails,
    "get_email_details": get_email_details,
    "clone_email": clone_email,
    "update_email_settings": update_email_settings,
    "update_email_content": update_email_content,
    "get_hubspot_list": get_hubspot_list,
    "create_static_list": create_static_list,
    "fetch_google_doc_html": fetch_google_doc_html,
    "validate_links": validate_links,
}

MAX_TOOL_ROUNDS = 20  # safety limit


def _dispatch_tool(name: str, inputs: dict) -> Any:
    fn = TOOL_FUNCTIONS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**inputs)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# SDK mode — full native tool_use protocol
# ---------------------------------------------------------------------------

def _run_sdk(messages: list[dict]) -> tuple[str, list[dict]]:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Extract final text
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text, messages
            return "", messages

        # Execute every tool_use block and collect results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _dispatch_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return json.dumps({"status": "error", "error": "Exceeded max tool rounds"}), messages


# ---------------------------------------------------------------------------
# CLI mode — text-based tool-use loop via Claude Code subprocess
#
# Protocol: Claude outputs either a tool call block or a final result block.
# We parse it, dispatch the tool, feed the result back, repeat.
#
# Claude is instructed to respond with one of:
#   ```tool\n{"name":"...","input":{...}}\n```
#   ```json\n{"status":"complete",...}\n```
#   ```json\n{"status":"needs_input",...}\n```
# ---------------------------------------------------------------------------

CLI_TOOL_PROMPT = """
## Tool-calling protocol (text mode)
When you want to call a tool, respond with ONLY this block (no other text):
```tool
{"name": "<tool_name>", "input": {<input_json>}}
```

When you are done or need user input, respond with ONLY the final JSON block as described above.
Do NOT mix tool calls and final output in the same response.
Available tools: """ + ", ".join(TOOL_FUNCTIONS.keys())


def _build_cli_prompt(messages: list[dict]) -> str:
    parts = [f"SYSTEM:\n{SYSTEM_PROMPT}\n{CLI_TOOL_PROMPT}\n"]
    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        if isinstance(content, list):
            # Flatten tool results or assistant blocks
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "tool_result":
                        text_parts.append(f"TOOL RESULT:\n{item.get('content', '')}")
                    else:
                        text_parts.append(json.dumps(item))
                else:
                    text_parts.append(str(item))
            content = "\n".join(text_parts)
        parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


def _run_cli(messages: list[dict]) -> tuple[str, list[dict]]:
    for _ in range(MAX_TOOL_ROUNDS):
        prompt = _build_cli_prompt(messages)

        is_windows = platform.system() == "Windows"
        # --system-prompt replaces Claude Code's default system prompt so Claude
        # acts purely as the email agent without any Claude Code context injection.
        # --dangerously-skip-permissions avoids interactive permission prompts in subprocess.
        if is_windows:
            cmd = ["cmd", "/c", "claude", "-p", prompt,
                   "--system-prompt", SYSTEM_PROMPT,
                   "--output-format", "text"]
        else:
            cmd = ["claude", "-p", prompt,
                   "--system-prompt", SYSTEM_PROMPT,
                   "--output-format", "text"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        text = result.stdout.strip()

        # Check for a tool call
        tool_match = re.search(r"```tool\s*(\{.*?\})\s*```", text, re.DOTALL)
        if tool_match:
            try:
                call = json.loads(tool_match.group(1))
                tool_result = _dispatch_tool(call["name"], call.get("input", {}))
                # Append the assistant's tool call and our result as new messages
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": f"TOOL RESULT for {call['name']}:\n{json.dumps(tool_result)}",
                })
                continue
            except (json.JSONDecodeError, KeyError):
                pass  # Fall through to return raw text

        # No tool call — Claude produced a final response
        messages.append({"role": "assistant", "content": text})
        return text, messages

    return json.dumps({"status": "error", "error": "Exceeded max tool rounds"}), messages


# ---------------------------------------------------------------------------
# Shared output parser (SDK / CLI modes)
# ---------------------------------------------------------------------------

def _parse_output(text: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {"status": "needs_input", "question": text or "No response from agent."}


# ---------------------------------------------------------------------------
# Deterministic workflow (no LLM needed)
# ---------------------------------------------------------------------------

QUARTER_MAP = {1:"Q1",2:"Q1",3:"Q1",4:"Q2",5:"Q2",6:"Q2",
               7:"Q3",8:"Q3",9:"Q3",10:"Q4",11:"Q4",12:"Q4"}


def _make_email_name(brand: str, email_type: str, descriptor: str, dt=None) -> str:
    dt = dt or date.today()
    q = f"{str(dt.year)[2:]}{QUARTER_MAP[dt.month]}"
    return f"{q} - {brand} - {email_type} - {descriptor}"


def _extract_request_from_messages(messages: list[dict]) -> dict:
    """Parse the latest user messages to rebuild the request dict."""
    req: dict = {}
    for msg in messages:
        if msg["role"] == "user":
            content = msg["content"] if isinstance(msg["content"], str) else json.dumps(msg["content"])
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("Please stage") or "brand:" in line.lower():
                    for part in line.split("\n") + content.split("\n"):
                        part = part.strip()
                        if part.lower().startswith("brand:"):
                            req["brand"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("subject:"):
                            req["subject"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("preview text:"):
                            req["preview_text"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("content doc:"):
                            req["content_url"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("target send date:"):
                            req["send_date"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("audience:"):
                            req["audience"] = part.split(":", 1)[1].strip()
                        elif part.lower().startswith("asana task:"):
                            req["asana_task_url"] = part.split(":", 1)[1].strip()
                # Continuation answers fill missing fields
                if "from name:" in line.lower():
                    req["from_name"] = line.split(":", 1)[1].strip()
                if "from address:" in line.lower():
                    req["from_address"] = line.split(":", 1)[1].strip()
                if "subject:" in line.lower() and "subject" not in req:
                    req["subject"] = line.split(":", 1)[1].strip()
    return req


def _run_deterministic(messages: list[dict], request_data: dict = None) -> tuple[dict, list[dict]]:
    """
    Execute the 9-step email staging workflow without an LLM.
    Asks the user only when required data is genuinely missing.
    """
    req = request_data or {}
    brand = req.get("brand", "")

    if not brand:
        return {"status": "needs_input", "question": "What brand/project is this email for? (e.g. OpenSSF, CNCF, NeoNephos)"}, messages

    # Step 1 — Asana task
    if req.get("asana_task_url"):
        task_data = _dispatch_tool("get_asana_task", {"task_url": req["asana_task_url"]})
        if "error" not in task_data:
            req.setdefault("subject", task_data.get("subject"))
            req.setdefault("content_url", task_data.get("content_url"))
            req.setdefault("send_date", task_data.get("send_date"))
            req.setdefault("audience", task_data.get("audience"))
            brand = task_data.get("brand") or brand

    # Step 2 — Brand history
    history = _dispatch_tool("search_brand_emails", {"brand_name": brand})
    sent_emails = history.get("emails", [])
    if not sent_emails:
        missing = []
        if not req.get("from_name"):
            missing.append("From name (e.g. 'OpenSSF')")
        if not req.get("from_address"):
            missing.append("From address (e.g. marketing@openssf.org)")
        if missing:
            return {"status": "needs_input",
                    "question": f"No prior sent emails found for '{brand}' in HubSpot. Please provide:\n" + "\n".join(f"- {m}" for m in missing)}, messages

    last_email = sent_emails[0] if sent_emails else {}
    last_email_id = last_email.get("id", "")

    # Step 3 — Full metadata from last email
    brand_settings: dict = {}
    if last_email_id:
        details = _dispatch_tool("get_email_details", {"email_id": last_email_id})
        if "error" not in details:
            brand_settings = {
                "from_name": details.get("fromName", req.get("from_name", "")),
                "from_address": details.get("fromEmail", req.get("from_address", "")),
                "subscription_type_id": details.get("subscriptionDetails", {}).get("id"),
                "email_type": details.get("emailType", "REGULAR_BATCH"),
                "suppression_list_ids": [
                    seg.get("id") for seg in details.get("rssData", {}).get("exceptLists", [])
                    if seg.get("id")
                ],
            }

    from_name = req.get("from_name") or brand_settings.get("from_name", brand)
    from_address = req.get("from_address") or brand_settings.get("from_address", "")

    if not from_address:
        return {"status": "needs_input",
                "question": f"What is the from address for {brand}? (e.g. marketing@openssf.org)"}, messages

    # Step 4 — Prepare content
    content_html = req.get("content_html", "")
    if not content_html and req.get("content_url"):
        doc_result = _dispatch_tool("fetch_google_doc_html", {"doc_url": req["content_url"]})
        if "error" in doc_result:
            return {"status": "needs_input",
                    "question": f"Could not access the content doc: {doc_result['error']}\nPlease share the doc with 'Anyone with link can view', or paste the HTML content directly."}, messages
        content_html = doc_result.get("html", "")

    if not content_html:
        return {"status": "needs_input",
                "question": "Please provide the email content — either a Google Doc URL or paste the HTML directly."}, messages

    # Step 5 — Subject line
    subject = req.get("subject", "")
    if not subject:
        return {"status": "needs_input", "question": "What is the subject line for this email?"}, messages

    preview_text = req.get("preview_text", "")
    if not preview_text:
        return {"status": "needs_input", "question": "What is the preview text (short teaser shown in inbox)?"}, messages

    # Step 6 — Email name
    send_date_str = req.get("send_date", "")
    try:
        from datetime import datetime
        dt = datetime.strptime(send_date_str, "%Y-%m-%d").date() if send_date_str else date.today()
    except ValueError:
        dt = date.today()

    descriptor = dt.strftime("%B") if not req.get("asana_task_url") else subject.split()[0]
    email_name = _make_email_name(brand, "Newsletter", descriptor, dt)

    # Step 7 — Clone
    if not last_email_id:
        return {"status": "needs_input",
                "question": f"No source email found to clone for '{brand}'. Please provide an existing HubSpot email ID to clone from."}, messages

    clone_result = _dispatch_tool("clone_email", {"email_id": last_email_id, "clone_name": email_name})
    if "error" in clone_result:
        return {"status": "error", "error": f"Failed to clone email: {clone_result['error']}"}, messages

    new_email_id = clone_result.get("id", "")
    if not new_email_id:
        return {"status": "error", "error": "Clone succeeded but no email ID returned."}, messages

    # Step 8 — Update settings
    settings_dict = {
        "subject": subject,
        "previewText": preview_text,
        "fromName": from_name,
        "fromEmail": from_address,
    }
    if brand_settings.get("subscription_type_id"):
        settings_dict["subscriptionId"] = brand_settings["subscription_type_id"]

    settings_result = _dispatch_tool("update_email_settings", {
        "email_id": new_email_id,
        "settings_dict": settings_dict,
    })
    if "error" in settings_result:
        return {"status": "error", "error": f"Failed to update settings: {settings_result['error']}"}, messages

    # Step 9 — Update content
    content_result = _dispatch_tool("update_email_content", {"email_id": new_email_id, "html": content_html})
    if "error" in content_result:
        return {"status": "error", "error": f"Failed to update content: {content_result['error']}"}, messages

    # Step 10 — Validate links
    link_check = _dispatch_tool("validate_links", {"html": content_html})
    broken = link_check.get("broken_links", [])

    hubspot_url = f"https://app.hubspot.com/email/{settings.hubspot_portal_id}/edit/{new_email_id}/send-options"

    suppression_ids = brand_settings.get("suppression_list_ids", [])

    qa = [
        {"item": "Subject set", "passed": bool(subject)},
        {"item": "Preview text set", "passed": bool(preview_text)},
        {"item": "From name/address correct", "passed": bool(from_name and from_address)},
        {"item": "Content updated", "passed": "error" not in content_result},
        {"item": "Links validated", "passed": len(broken) == 0,
         "note": f"{len(broken)} broken link(s) found" if broken else None},
        {"item": "Suppression lists applied", "passed": len(suppression_ids) > 0,
         "note": "No suppression lists found in brand history" if not suppression_ids else None},
        {"item": "Naming convention followed", "passed": True},
        {"item": "Status is DRAFT", "passed": True},
    ]

    return {
        "status": "complete",
        "email_id": new_email_id,
        "email_name": email_name,
        "hubspot_url": hubspot_url,
        "summary": {
            "subject": subject,
            "from": f"{from_name} <{from_address}>",
            "send_list": req.get("audience", "Not configured — set in HubSpot"),
            "suppressions": [str(i) for i in suppression_ids],
            "email_type": brand_settings.get("email_type", "REGULAR_BATCH"),
            "status": "DRAFT",
        },
        "qa_checklist": qa,
    }, messages


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_agent(messages: list[dict], request_data: dict = None) -> tuple[dict, list[dict]]:
    """
    Run the email staging workflow.
    - SDK mode      : ANTHROPIC_API_KEY set → Claude drives tool-use loop
    - Deterministic : no key / no credits → fixed 9-step Python workflow
    """
    if settings.anthropic_api_key:
        try:
            text, updated = _run_sdk(messages)
            return _parse_output(text), updated
        except Exception as e:
            if "credit" in str(e).lower() or "billing" in str(e).lower() or "insufficient" in str(e).lower():
                pass  # fall through to deterministic
            else:
                raise

    return _run_deterministic(messages, request_data)
