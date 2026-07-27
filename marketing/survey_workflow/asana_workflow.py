"""
Survey Workflow orchestration.

Given a single parent Asana task URL, this:
1. Reads the task's 6-stage subtask pipeline (Content, Provide List, Staging,
   Approval, Launch, Campaign Update) and reports which stage things are at.
2. Takes NO action on Content / Provide List - those are owned upstream.
3. Once BOTH are marked complete, pulls the content doc (from Content's
   comments) and the HubSpot send list (from Provide List's comments), and
   builds 1 or N draft emails - via the same AI logic as emailcreationskill.
"""
import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'emailcreationskill', 'backend'))

import content_tools

import stage_brief
import hubspot_clone
import hubspot_workflow_clone

log = logging.getLogger("survey-workflow")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False


class SurveyWorkflow:
    """Orchestrates the brief + gated multi-draft build for one Asana task."""

    def __init__(self, asana_url: str, overrides: dict = None, hubspot_workflow_url: str = None,
                 content_override: str = None, content_links: list = None):
        self.asana_url = asana_url
        self.overrides = overrides or {}
        self.hubspot_workflow_url = hubspot_workflow_url or ""
        # Manually pasted email content from the UX, used INSTEAD of fetching
        # the Content subtask's Google Doc link - the fallback for when the
        # doc isn't shared with the service account (or any other fetch
        # failure). Run through ai_polish_pasted_content() below (cleanup +
        # link/button placement) rather than used byte-for-byte.
        self.content_override = (content_override or "").strip()
        # Links the user wants placed in the pasted content: list of
        # {"id": str, "text": str (anchor phrase/placement hint), "url": str,
        # "is_button": bool}. Only used together with content_override.
        self.content_links = content_links or []
        self.raw_data = {}
        self.brief = {}
        self.warnings = []

    def _polish_override_content(self) -> str:
        """AI-clean the pasted content and place the user's links/buttons, then
        mechanically substitute the real URLs (never AI-generated) in."""
        html = stage_brief.ai_polish_pasted_content(self.content_override, self.content_links)
        return stage_brief.resolve_polish_placeholders(html, self.content_links)

    async def get_brief(self) -> dict:
        """Read-only: fetch the task, report stage status. Takes no action."""
        log.info(f"Starting brief for: {self.asana_url}")
        self.raw_data = await stage_brief.fetch_task_data_async(self.asana_url)
        log.info("Building stage-by-stage brief...")
        self.brief = stage_brief.build_brief(self.raw_data, overrides=self.overrides)

        loop = asyncio.get_running_loop()
        self.brief = await loop.run_in_executor(None, stage_brief.analyze_stages, self.brief)

        log.info(
            f"[BRIEF] task={self.brief['task_name']!r} "
            f"current_stage={self.brief['current_stage']!r} "
            f"ready_to_build={self.brief['ready_to_build']}"
        )
        return self.brief

    async def get_staging_preview(self) -> dict:
        """
        Read-only preview for the Staging tab:
        - If Staging is already marked complete, surface the built email links
          found in its comments instead of re-building anything.
        - Otherwise, if gated, say so.
        - Otherwise, fetch the content doc and split it into 1-or-N draft
          previews so the user can see what WILL be built before building it.
        """
        if not self.brief:
            await self.get_brief()

        if self.brief.get("staging_done"):
            return {
                "already_completed": True,
                "email_links": self.brief.get("staging_email_links", []),
                "brief": self.brief,
            }

        if not self.brief.get("ready_to_build"):
            return {"gated": True, "brief": self.brief}

        if self.content_override:
            loop = asyncio.get_running_loop()
            doc_html = await loop.run_in_executor(None, self._polish_override_content)
            log.info("[STAGING-PREVIEW] using manually pasted content override, AI-polished with links (skipped content doc fetch)")
        else:
            if not self.brief.get("content_doc_url"):
                return {"error": "Could not find a content doc link in the Content subtask's comments.", "brief": self.brief}

            try:
                loop = asyncio.get_running_loop()
                doc_html = await loop.run_in_executor(None, content_tools.prepare_content, self.brief["content_doc_url"])
            except Exception as e:
                log.error(f"[STAGING-PREVIEW] doc fetch failed for {self.brief['content_doc_url']!r}: {e}")
                return {
                    "error": f"Could not fetch content doc: {e}",
                    "doc_fetch_failed": True,
                    "brief": self.brief,
                }

        loop = asyncio.get_running_loop()
        drafts = await loop.run_in_executor(None, stage_brief.ai_split_drafts, doc_html)
        return {
            "already_completed": False,
            "draft_count": len(drafts),
            "needs_workflow": len(drafts) > 1,
            "drafts": [
                {
                    "index": i,
                    "heading": d["heading"],
                    "description": d["description"],
                    "preview": d["content"],
                }
                for i, d in enumerate(drafts, start=1)
            ],
            "brief": self.brief,
        }

    async def build_drafts(self) -> dict:
        """
        Gated build step. Only runs once Content + Provide List are both
        completed. Builds 1 or N draft emails (matching the doc's draft
        count) using the existing email creation service's AI logic.

        Guardrail: if Staging is already marked complete, this task's emails
        (and workflow, if any) already exist and are considered done - refuse
        to build again rather than risk creating confusing duplicates. This
        service only ever creates NEW clones; it never modifies an existing
        email or workflow, completed or not.
        """
        if not self.brief:
            await self.get_brief()

        if self.brief.get("staging_done"):
            msg = "Staging is already marked complete for this task - refusing to build again."
            log.info(f"[BUILD] {msg}")
            return {
                "success": False,
                "already_completed": True,
                "error": msg,
                "email_links": self.brief.get("staging_email_links", []),
                "brief": self.brief,
            }

        if not self.brief.get("ready_to_build"):
            waiting_on = [
                s["name"] for s in self.brief["stages"]
                if s["name"] in stage_brief.NO_ACTION_STAGES and not s["completed"]
            ]
            log.info(f"[BUILD] Gated - waiting on: {waiting_on}")
            return {
                "success": False,
                "gated": True,
                "waiting_on": waiting_on,
                "brief": self.brief,
            }

        if self.content_override:
            doc_html = self._polish_override_content()
            log.info("[BUILD] using manually pasted content override, AI-polished with links (skipped content doc fetch)")
        else:
            if not self.brief.get("content_doc_url"):
                return {
                    "success": False,
                    "error": "Could not find a content doc link in the Content subtask's comments.",
                    "brief": self.brief,
                }

            # Fetch + split the content doc into draft segments
            try:
                doc_html = content_tools.prepare_content(self.brief["content_doc_url"])
            except Exception as e:
                log.error(f"[BUILD] doc fetch failed for {self.brief['content_doc_url']!r}: {e}")
                return {
                    "success": False,
                    "error": f"Could not fetch content doc: {e}",
                    "doc_fetch_failed": True,
                    "brief": self.brief,
                }

        drafts = stage_brief.ai_split_drafts(doc_html)
        log.info(f"[BUILD] Doc split into {len(drafts)} draft(s)")

        send_list_id = self.brief.get("hubspot_list_id") or None
        task_name = self.brief.get("task_name", "Survey")

        results = []
        for i, draft in enumerate(drafts, start=1):
            clone_name = f"{task_name} - Draft {i}" if len(drafts) > 1 else task_name

            try:
                built = hubspot_clone.clone_and_replace_body(
                    task_name=task_name,
                    content_html=draft["content"],
                    clone_name=clone_name,
                    send_list_id=send_list_id,
                )
                results.append({
                    "draft_index": i,
                    "heading": draft["heading"],
                    "description": draft["description"],
                    "success": True,
                    "email_id": built["email_id"],
                    "email_name": built["email_name"],
                    "draft_url": built["draft_url"],
                    "source_email_id": built["source_email_id"],
                    "source_email_name": built["source_email_name"],
                })
                log.info(
                    f"[BUILD] Draft {i}/{len(drafts)} built: email_id={built['email_id']} "
                    f"(cloned from {built['source_email_name']!r})"
                )
            except Exception as e:
                log.error(f"[BUILD] Draft {i} failed: {e}", exc_info=True)
                self.warnings.append(f"Draft {i} failed: {e}")
                results.append({"draft_index": i, "success": False, "error": str(e)})

        workflow_result = None
        workflow_url = self.hubspot_workflow_url or self.brief.get("hubspot_workflow_url")
        all_built = results and all(r.get("success") for r in results)

        if len(drafts) == 1:
            # Single-email doc: just the one email + send list, no workflow.
            if workflow_url:
                log.info("[BUILD] Doc has 1 email - skipping workflow clone (single-email docs don't need one).")
        elif workflow_url and all_built:
            workflow_result = self._clone_workflow(workflow_url, drafts, results, doc_html, task_name)
        elif workflow_url and not all_built:
            msg = "Skipped workflow clone: not every draft email built successfully."
            log.warning(f"[BUILD] {msg}")
            self.warnings.append(msg)

        return {
            "success": any(r.get("success") for r in results),
            "drafts": results,
            "workflow": workflow_result,
            "warnings": self.warnings,
            "brief": self.brief,
        }

    def _clone_workflow(self, workflow_url: str, drafts: list, results: list, doc_html: str, task_name: str) -> dict:
        """
        Clone the given HubSpot workflow, swap in the newly built draft emails
        (in the same 1,2,3.. order they were built), and update its delay-until
        -date steps to the send dates found in the content doc. Always created
        disabled - a human must review + enable it in HubSpot.
        """
        flow_id = hubspot_workflow_clone.extract_flow_id(workflow_url)
        if not flow_id:
            msg = f"Could not extract a flow id from workflow URL: {workflow_url}"
            log.error(f"[BUILD] {msg}")
            self.warnings.append(msg)
            return {"success": False, "error": msg}

        email_ids_in_order = [r["email_id"] for r in results]
        send_dates = stage_brief.ai_extract_send_dates(doc_html, num_dates=len(drafts))

        try:
            built = hubspot_workflow_clone.clone_and_replace_workflow_emails(
                flow_id=flow_id,
                clone_name=f"{task_name} - Workflow",
                email_ids_in_order=email_ids_in_order,
                send_dates=send_dates or None,
            )
            log.info(
                f"[BUILD] Workflow cloned: flow_id={built['flow_id']} "
                f"(from {built['source_flow_name']!r}, {built['send_email_count']} email(s) replaced, disabled)"
            )
            return {"success": True, **built}
        except Exception as e:
            log.error(f"[BUILD] Workflow clone failed: {e}", exc_info=True)
            self.warnings.append(f"Workflow clone failed: {e}")
            return {"success": False, "error": str(e)}


async def run_survey_workflow(asana_url: str, overrides: dict = None) -> dict:
    """Convenience: brief + gated build in one call."""
    workflow = SurveyWorkflow(asana_url, overrides=overrides)
    await workflow.get_brief()
    if not workflow.brief.get("ready_to_build"):
        return {"success": False, "gated": True, "brief": workflow.brief}
    return await workflow.build_drafts()
