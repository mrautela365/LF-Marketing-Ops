import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import audience
import brands
import config
import prompts
from audience_builder.routes import router as audience_builder_router
from implementation.routes import router as implementation_router
from llm import gateway
from email_render import render_email_html, render_body_fragment
from integrations import hubspot
from models import (
    GeneratePreviewRequest, GeneratePreviewResponse, RerenderPreviewRequest,
    RerenderPreviewResponse, UploadHeroImageResponse, ApproveRequest, ApproveResponse,
    ApproveResultItem, VariantPreview, AudiencePlan, AudiencePlanRequest, AudiencePlanResponse,
    AudienceBuildRequest, AudienceBuildResponse,
)

app = FastAPI(title="Survey/Report Promo Email Automation")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

FIXED_BRAND_ID = "lf_research"


def _hero_image_path(hero_image_id: str) -> Path:
    return UPLOADS_DIR / hero_image_id


def _hero_image_url(hero_image_id: str) -> str:
    if not hero_image_id:
        return ""
    return f"/uploads/{hero_image_id}"


@app.get("/api/brands")
def get_brands():
    return brands.list_brands()


@app.post("/api/upload-hero-image", response_model=UploadHeroImageResponse)
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


@app.post("/api/generate-preview", response_model=GeneratePreviewResponse)
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


@app.post("/api/rerender-preview", response_model=RerenderPreviewResponse)
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


@app.post("/api/approve", response_model=ApproveResponse)
def approve(req: ApproveRequest):
    """Only step that talks to HubSpot. Finds the most recent same-brand+type
    published email once, then clones it once per variant (1 for a single email,
    3 for an invite/reminder/deadline sequence) and swaps only the hero image +
    body copy on each clone — header/footer/template come from the source
    untouched. Never runs twice for the same click since the frontend disables
    the button after a successful call."""
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


@app.post("/api/audience/plan", response_model=AudiencePlanResponse)
def audience_plan(req: AudiencePlanRequest):
    """Phase 1: parse the free-text audience description into a structured plan.
    Creates NOTHING in HubSpot — the user reviews/edits this plan before /build."""
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Audience description is required.")

    prompt = prompts.build_audience_planning_prompt(req.description, req.qa or "")
    raw = gateway.complete_text(prompt, system=prompts.AUDIENCE_SYSTEM, max_tokens=1500)
    try:
        parsed = prompts.parse_generation_json(raw)
    except Exception:
        raise HTTPException(status_code=502, detail=f"Model did not return valid JSON: {raw[:2000]}")

    return AudiencePlanResponse(plan=AudiencePlan(**parsed))


@app.post("/api/audience/build", response_model=AudienceBuildResponse)
def audience_build(req: AudienceBuildRequest):
    """Phase 2: only step that talks to HubSpot for the audience feature. Builds
    the master (inclusion) list from the confirmed plan, plus a combined
    suppression list if the plan calls for one, and gates the master list on it."""
    if not config.HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=400, detail="HUBSPOT_ACCESS_TOKEN is not configured in .env")

    try:
        result = audience.build_audience(req.plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return AudienceBuildResponse(**result)


app.include_router(audience_builder_router)
app.include_router(implementation_router)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
