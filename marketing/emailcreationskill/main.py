import logging
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from email_service.models import EmailRequest, ContinueRequest, AgentResponse
from email_service import session_store
from email_service.agent import run_agent

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Email Creation Agent",
    description="Agentic HubSpot email staging service. Claude orchestrates all steps.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_initial_message(req: EmailRequest) -> str:
    parts = [f"Please stage a HubSpot marketing email for brand: {req.brand}"]
    if req.asana_task_url:
        parts.append(f"Asana task: {req.asana_task_url}")
    if req.subject:
        parts.append(f"Subject: {req.subject}")
    if req.preview_text:
        parts.append(f"Preview text: {req.preview_text}")
    if req.content_url:
        parts.append(f"Content doc: {req.content_url}")
    if req.content_html:
        parts.append(f"Content HTML provided inline (length: {len(req.content_html)} chars)")
    if req.send_date:
        parts.append(f"Target send date: {req.send_date}")
    if req.audience:
        parts.append(f"Audience: {req.audience}")
    if req.from_name:
        parts.append(f"From name override: {req.from_name}")
    if req.from_address:
        parts.append(f"From address override: {req.from_address}")
    return "\n".join(parts)


def _format_response(session_id: str, result: dict) -> AgentResponse:
    status = result.get("status", "needs_input")

    if status == "complete":
        summary_raw = result.get("summary", {})
        from email_service.models import EmailSummary, QAItem
        summary = EmailSummary(
            subject=summary_raw.get("subject"),
            from_=summary_raw.get("from"),
            send_list=summary_raw.get("send_list"),
            suppressions=summary_raw.get("suppressions", []),
            email_type=summary_raw.get("email_type"),
            status=summary_raw.get("status", "DRAFT"),
        )
        qa = [QAItem(**item) for item in result.get("qa_checklist", [])]
        return AgentResponse(
            session_id=session_id,
            status="complete",
            email_id=result.get("email_id"),
            email_name=result.get("email_name"),
            hubspot_url=result.get("hubspot_url"),
            summary=summary,
            qa_checklist=qa,
        )

    if status == "needs_input":
        return AgentResponse(
            session_id=session_id,
            status="needs_input",
            question=result.get("question"),
        )

    return AgentResponse(
        session_id=session_id,
        status="error",
        error=result.get("error", "Unknown error from agent"),
    )


@app.post("/api/email-request", response_model=AgentResponse, summary="Start email staging session")
async def start_email_request(req: EmailRequest):
    try:
        request_data = req.model_dump(exclude_none=True)
        session_id = session_store.create_session(request_data=request_data)
        user_message = _build_initial_message(req)
        logger.debug("Starting session %s | message: %s", session_id, user_message)
        session_store.append_message(session_id, "user", user_message)

        session = session_store.get_session(session_id)
        result, updated_messages = run_agent(session["messages"], session["request_data"])
        logger.debug("Agent result: %s", result)

        session_store.update_session(session_id, messages=updated_messages, status=result.get("status"))
        if result.get("email_id"):
            session_store.update_session(session_id, email_id=result["email_id"])

        return _format_response(session_id, result)
    except Exception:
        err = traceback.format_exc()
        logger.error("Error in start_email_request:\n%s", err)
        return JSONResponse(status_code=500, content={"detail": err})


@app.post("/api/email-request/{session_id}/continue", response_model=AgentResponse,
          summary="Continue a paused session with user answer")
async def continue_email_request(session_id: str, req: ContinueRequest):
    try:
        session = session_store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

        session_store.append_message(session_id, "user", req.answer)
        # Merge any key:value pairs from the answer into request_data
        for line in req.answer.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().lower().replace(" ", "_")
                v = v.strip()
                if k and v:
                    session["request_data"][k] = v
        logger.debug("Continuing session %s | answer: %s", session_id, req.answer)

        session = session_store.get_session(session_id)
        result, updated_messages = run_agent(session["messages"], session["request_data"])
        logger.debug("Agent result: %s", result)

        session_store.update_session(session_id, messages=updated_messages, status=result.get("status"))
        if result.get("email_id"):
            session_store.update_session(session_id, email_id=result["email_id"])

        return _format_response(session_id, result)
    except Exception:
        err = traceback.format_exc()
        logger.error("Error in continue_email_request:\n%s", err)
        return JSONResponse(status_code=500, content={"detail": err})


@app.get("/health")
async def health():
    return {"status": "ok"}
