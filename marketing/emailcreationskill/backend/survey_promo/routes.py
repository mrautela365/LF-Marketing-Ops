"""
FastAPI routes for the Survey/Report Promo tab.

Ported from Survey_Workflow_automation/backend/main.py + implementation/routes.py,
namespaced under /api/survey so nothing collides with this app's existing
/api/... campaign-builder and /api/audience-builder routes.

The standalone app's /api/audience/plan and /api/audience/build routes are NOT
ported — the Audience step in this tab drives the existing Audience Builder
(/api/audience-builder/*) instead.

Steps:
  1. Planning        -> POST /api/survey/generate-preview   (AI, no HubSpot)
  2. Email Preview   -> POST /api/survey/rerender-preview   (no AI, no HubSpot)
                        POST /api/survey/approve            (creates HubSpot drafts)
  3. Audience        -> handled by /api/audience-builder/*
  4. Implementation  -> POST /api/survey/implementation/single
                        POST /api/survey/implementation/sequence
"""
import logging
import uuid
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

import config
from llm import gateway
from survey_promo import brands, prompts
from survey_promo import hubspot_api as hubspot
from audience_builder import master_list
from survey_promo.email_render import render_email_html, render_body_fragment
from survey_promo.models import (
    GeneratePreviewRequest, GeneratePreviewResponse, RerenderPreviewRequest,
    RerenderPreviewResponse, UploadHeroImageResponse, ApproveRequest, ApproveResponse,
    ApproveResultItem, VariantPreview,
    ImplementationSingleRequest, ImplementationSingleResponse, SuppressionListItem,
    ImplementationSequenceRequest, ImplementationSequenceResponse,
)

log = logging.getLogger("survey-promo")

router = APIRouter(prefix="/api/survey", tags=["survey-promo"])

UPLOADS_DIR = Path(__file__).parent.parent / "uploads" / "survey_promo"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

FIXED_BRAND_ID = "lf_research"


def _hero_image_path(hero_image_id: str) -> Path:
    """Resolve a staged hero image by id. The id is always a uuid4 hex + extension
    minted by upload_hero_image, but it arrives back from the client, so reject
    anything with path separators rather than trusting it into a path join."""
    if not hero_image_id or "/" in hero_image_id or "\\" in hero_image_id or ".." in hero_image_id:
        raise HTTPException(status_code=400, detail="Invalid hero image id.")
    return UPLOADS_DIR / hero_image_id


def _hero_image_url(hero_image_id: str) -> str:
    if not hero_image_id:
        return ""
    return f"/api/survey/uploads/{hero_image_id}"


@router.get("/brands")
def get_brands():
    return brands.list_brands()


@router.get("/uploads/{hero_image_id}")
def get_hero_image(hero_image_id: str):
    """Serve a locally staged hero image. A route rather than a second StaticFiles
    mount so the whole tab stays behind the /api/survey prefix."""
    path = _hero_image_path(hero_image_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Hero image not found.")
    return FileResponse(str(path))


@router.post("/upload-hero-image", response_model=UploadHeroImageResponse)
async def upload_hero_image(file: UploadFile = File(...)):
    """Stage the hero image locally only. It is NOT sent to HubSpot until the
    user clicks Approve, to avoid creating duplicate files there on every retry."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext or 'unknown'}")

    hero_image_id = f"{uuid.uuid4().hex}{ext}"
    dest = _hero_image_path(hero_image_id)
    contents = await file.read()
    dest.write_bytes(contents)

    return UploadHeroImageResponse(hero_image_id=hero_image_id, url=_hero_image_url(hero_image_id))


@router.post("/generate-preview", response_model=GeneratePreviewResponse)
def generate_preview(req: GeneratePreviewRequest):
    brand = brands.get_brand(FIXED_BRAND_ID)
    email_type = req.email_type

    prompt = prompts.build_prompt(
        email_type=email_type,
        source_text=req.source_text,
        promoted_url=req.promoted_url,
        brand_label=brand["label"],
        email_plan=req.email_plan,
    )

    max_tokens = 4000 if req.email_plan == "sequence" else 2000
    raw = gateway.complete_text(prompt, system=prompts.SYSTEM_PROMPT, max_tokens=max_tokens)
    try:
        generated = prompts.parse_generation_json(raw)
    except Exception:
        raise HTTPException(status_code=502, detail=f"Model did not return valid JSON: {raw[:2000]}")

    hero_image_url = _hero_image_url(req.hero_image_id or "")

    if req.email_plan == "sequence":
        variant_dicts = prompts.sequence_variants_from_generation(generated)
        if len(variant_dicts) != 3:
            raise HTTPException(
                status_code=502,
                detail=f"Model did not return a 3-part sequence: {raw[:2000]}",
            )
    else:
        variant_dicts = [{**generated, "stage": "single"}]

    variants = []
    for v in variant_dicts:
        html_out = render_email_html(
            generated=v, brand=brand, email_type=email_type, promoted_url=req.promoted_url,
            hero_image_url=hero_image_url,
        )
        variants.append(VariantPreview(
            stage=v.get("stage", "single"),
            subject=v.get("subject", ""),
            preview_text=v.get("preview_text", ""),
            hero_headline=v.get("hero_headline", ""),
            body_paragraphs=v.get("body_paragraphs", []),
            use_bullets=bool(v.get("use_bullets")),
            bullets=v.get("bullets", []),
            incentive=v.get("incentive", ""),
            impact_sentence=v.get("impact_sentence", ""),
            share_line=v.get("share_line", ""),
            cta_text=v.get("cta_text", ""),
            hero_image_url=hero_image_url,
            html=html_out,
        ))

    return GeneratePreviewResponse(email_type=email_type, email_plan=req.email_plan, variants=variants)


@router.post("/rerender-preview", response_model=RerenderPreviewResponse)
def rerender_preview(req: RerenderPreviewRequest):
    """Re-render one variant's HTML from user-edited copy fields without a new AI call."""
    brand = brands.get_brand(FIXED_BRAND_ID)

    generated = req.variant.model_dump()
    hero_image_url = _hero_image_url(req.hero_image_id or "")
    html_out = render_email_html(
        generated=generated, brand=brand, email_type=req.email_type, promoted_url=req.promoted_url,
        hero_image_url=hero_image_url,
    )
    return RerenderPreviewResponse(stage=req.variant.stage, html=html_out, hero_image_url=hero_image_url)


@router.post("/approve", response_model=ApproveResponse)
def approve(req: ApproveRequest):
    """Only step in the preview flow that talks to HubSpot. Finds the most recent
    same-brand+type published email once, then clones it once per variant (1 for a
    single email, 3 for an invite/reminder/deadline sequence) and swaps only the
    hero image + body copy on each clone — header/footer/template come from the
    source untouched. Never runs twice for the same click since the frontend
    disables the button after a successful call."""
    brand = brands.get_brand(FIXED_BRAND_ID)

    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    type_term = "survey" if req.email_type == "survey" else "report promo"
    try:
        source = hubspot.find_latest_email(brand["hubspot_search_term"], type_term)
        if not source.get("found"):
            override_name = (brand.get("clone_source_overrides") or {}).get(req.email_type)
            if override_name:
                source = hubspot.find_email_by_name(override_name)
    except requests.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HubSpot API error while searching for a clone source: {exc}",
        )
    if not source.get("found"):
        raise HTTPException(
            status_code=404,
            detail=f"No published '{type_term}' email found in HubSpot for brand "
                   f"'{brand['hubspot_search_term']}' to clone from.",
        )

    hero_cdn_url = ""
    warnings = []
    if req.hero_image_id:
        local_path = _hero_image_path(req.hero_image_id)
        if local_path.exists():
            try:
                hero_cdn_url = hubspot.upload_local_image_to_hubspot(str(local_path), req.hero_image_id)
            except RuntimeError as exc:
                warnings.append(
                    f"Hero image upload to HubSpot failed, so the draft(s) below kept the clone "
                    f"source's original banner — everything else (subject/preview/body copy) was "
                    f"still created. Fix and re-upload manually in HubSpot, or resolve the upload "
                    f"error and re-approve: {exc}"
                )

    results = []
    try:
        for variant in req.variants:
            stage_label = f" ({variant.stage})" if variant.stage != "single" else ""
            clone_name = f"{brand['label']} - {type_term.title()} - AI Draft{stage_label} ({variant.subject[:50]})"
            # Sequence-stage variants (invite/reminder/deadline) clone from the fixed
            # sequence workflow's own already-automated template emails, so the new
            # draft inherits "Send: Through an automation" (no audience list) instead
            # of the "To a segment of contacts" method a regular batch-email clone
            # would carry. The single-email path is unaffected.
            stage_template_id = hubspot.SEQUENCE_STAGE_TEMPLATE_EMAIL_IDS.get(variant.stage)
            clone_source_id = stage_template_id or source["email_id"]
            cloned = hubspot.clone_email(clone_source_id, clone_name)

            hubspot.update_email_settings(
                cloned["email_id"], subject=variant.subject, preview_text=variant.preview_text
            )

            generated = {
                "body_paragraphs": variant.body_paragraphs,
                "use_bullets": variant.use_bullets,
                "bullets": variant.bullets,
                "incentive": variant.incentive,
                "impact_sentence": variant.impact_sentence,
                "share_line": variant.share_line,
            }
            body_html = render_body_fragment(generated)
            hubspot.apply_body_and_banner(cloned["email_id"], hero_image_url=hero_cdn_url, body_html=body_html)

            results.append(ApproveResultItem(
                stage=variant.stage,
                email_id=cloned["email_id"],
                draft_url=cloned["draft_url"],
                state=cloned["state"],
                cloned_from_name=source.get("name", ""),
            ))
    except requests.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HubSpot API error while creating draft(s) "
                   f"({len(results)}/{len(req.variants)} completed before failure): {exc}",
        )

    return ApproveResponse(results=results, warnings=warnings)


# --- Implementation ---
#
# Two paths, gated by which email plan the user chose in Planning:
#  - single email: attach the selected audience list to the approved draft.
#    Never calls any HubSpot schedule/publish endpoint — the draft stays a
#    draft; the user schedules/sends it themselves in HubSpot for the
#    date/time they picked here.
#  - 3-email sequence: clone the fixed base sequence workflow (which sends all
#    3 emails itself) with the new email ids, dates, and audience list as its
#    enrollment criteria. The clone is always created disabled — the user
#    must open it in HubSpot and turn it on themselves when ready.

def _parse_time(value: str) -> dict:
    hour, minute = value.split(":")
    return {"hour": int(hour), "minute": int(minute)}


@router.post("/implementation/single", response_model=ImplementationSingleResponse)
def implementation_single(req: ImplementationSingleRequest):
    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    # A one-off email has no workflow around it to enforce hygiene, so the
    # standard opt-out/GDPR/exclusion lists are written straight onto the
    # draft's "don't send to" field. No brand/event args: this tab is pinned to
    # LF Research and promotes a survey/report rather than an event, so only
    # the 6 portfolio-wide lists apply. Resolution is best-effort — a HubSpot
    # search outage should not block attaching the send list.
    try:
        suppression = master_list.find_standard_suppression_lists()
    except Exception as exc:
        log.warning("Standard suppression lookup failed, continuing without it: %s", exc)
        suppression = []

    try:
        hubspot.set_email_send_list(
            req.email_id,
            req.list_id,
            suppression_list_ids=[s["list_id"] for s in suppression],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HubSpot API error while attaching the send list: {exc}")

    return ImplementationSingleResponse(
        email_id=req.email_id,
        list_id=req.list_id,
        draft_url=hubspot.email_edit_url(req.email_id),
        send_date=req.send_date,
        suppression_lists=[
            SuppressionListItem(
                list_id=s["list_id"],
                label=s["label"],
                name=s.get("name") or s["label"],
            )
            for s in suppression
        ],
    )


@router.post("/implementation/sequence", response_model=ImplementationSequenceResponse)
def implementation_sequence(req: ImplementationSequenceRequest):
    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    try:
        flow = hubspot.clone_sequence_workflow(
            name=req.workflow_name or "Survey Promo Sequence (AI Draft)",
            list_id=req.list_id,
            invite_email_id=req.invite_email_id,
            invite_date=req.invite.date,
            invite_time=_parse_time(req.invite.time),
            reminder_email_id=req.reminder_email_id,
            reminder_date=req.reminder.date,
            reminder_time=_parse_time(req.reminder.time),
            deadline_email_id=req.deadline_email_id,
            deadline_date=req.deadline.date,
            deadline_time=_parse_time(req.deadline.time),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HubSpot API error while cloning the sequence workflow: {exc}",
        )

    return ImplementationSequenceResponse(
        invite_email_id=req.invite_email_id,
        invite_draft_url=hubspot.email_edit_url(req.invite_email_id),
        workflow_id=flow["flow_id"],
        workflow_url=flow["url"],
        workflow_enabled=flow["is_enabled"],
    )
