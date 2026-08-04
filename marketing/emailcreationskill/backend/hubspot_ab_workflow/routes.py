"""
API Routes for HubSpot Workflow A/B Testing
Completely isolated endpoints - can be easily removed
"""
import logging
from fastapi import APIRouter, HTTPException
from .models import ABTestRequest
from . import workflow_manager
from . import hubspot_integration

log = logging.getLogger("email-staging")

router = APIRouter(prefix="/api/ab-workflow", tags=["ab-workflow"])


@router.get("/enabled")
async def check_ab_workflow_enabled():
    """
    Check if A/B Workflow feature is enabled
    Easy way to toggle the feature on/off
    """
    return {"enabled": True, "feature": "hubspot-workflow-ab-testing"}


@router.post("/create")
async def create_ab_test(req: ABTestRequest):
    """
    Create a new A/B test (DRAFT state)
    User selects variants and audience before launching
    """
    try:
        test = workflow_manager.create_ab_test(req)
        return {
            "test_id": test.id,
            "status": "created",
            "variant_a": test.variant_a_email_name,
            "variant_b": test.variant_b_email_name,
            "audience": test.audience_list_name,
            "test_duration_hours": test.test_duration_hours,
        }
    except Exception as e:
        log.error(f"[AB-WF] Failed to create A/B test: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{test_id}/launch")
async def launch_ab_test(test_id: str):
    """
    Launch A/B test - triggers HubSpot workflow
    Sends Variant A to 50% of audience, Variant B to 50%
    """
    try:
        result = workflow_manager.launch_ab_test(test_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"[AB-WF] Failed to launch A/B test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{test_id}")
async def get_ab_test(test_id: str):
    """Get A/B test details"""
    try:
        test = workflow_manager.get_ab_test(test_id)
        if not test:
            raise HTTPException(status_code=404, detail=f"A/B test {test_id} not found")

        return {
            "test_id": test.id,
            "status": test.status.value,
            "variant_a": {
                "email_id": test.variant_a_email_id,
                "name": test.variant_a_email_name,
            },
            "variant_b": {
                "email_id": test.variant_b_email_id,
                "name": test.variant_b_email_name,
            },
            "audience": {
                "list_id": test.audience_list_id,
                "list_name": test.audience_list_name,
            },
            "test_sample_size": test.test_sample_size,
            "test_duration_hours": test.test_duration_hours,
            "created_at": test.created_at.isoformat() if test.created_at else None,
            "launched_at": test.launched_at.isoformat() if test.launched_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[AB-WF] Failed to get A/B test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{test_id}/status")
async def get_ab_test_status(test_id: str):
    """
    Get current A/B test status with live metrics
    Returns different data based on status (draft/running/completed)
    """
    try:
        status = workflow_manager.get_ab_test_status(test_id)
        return status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"[AB-WF] Failed to get A/B test status {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{test_id}/complete")
async def complete_ab_test(test_id: str):
    """
    Complete A/B test and determine winner
    Called after 24-hour test window completes
    """
    try:
        result = workflow_manager.complete_ab_test(test_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"[AB-WF] Failed to complete A/B test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_ab_tests():
    """Get list of all A/B tests"""
    try:
        tests = workflow_manager.get_ab_test_list()
        return {
            "total": len(tests),
            "tests": [
                {
                    "id": t.id,
                    "variant_a": t.variant_a_name,
                    "variant_b": t.variant_b_name,
                    "audience": t.audience_name,
                    "status": t.status.value,
                    "winner": t.winner,
                    "confidence": t.confidence,
                    "created_at": t.created_at.isoformat(),
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                }
                for t in tests
            ]
        }
    except Exception as e:
        log.error(f"[AB-WF] Failed to list A/B tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{test_id}/archive")
async def archive_ab_test(test_id: str):
    """Archive old A/B test"""
    try:
        result = workflow_manager.archive_ab_test(test_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"[AB-WF] Failed to archive A/B test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper endpoints for UI

@router.get("/ui/emails")
async def get_available_emails(name_contains: str = ""):
    """
    Get list of available emails in HubSpot for user to select
    Used by UI dropdown for variant selection
    """
    try:
        emails = hubspot_integration.search_emails_by_name(name_contains)
        return {
            "total": len(emails),
            "emails": [
                {
                    "id": e.get("id"),
                    "name": e.get("name"),
                    "subject": e.get("subject"),
                    "state": e.get("state"),
                }
                for e in emails
            ]
        }
    except Exception as e:
        log.error(f"[AB-WF] Failed to get emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ui/lists")
async def get_available_lists(name_contains: str = ""):
    """
    Get list of available HubSpot lists for user to select
    Used by UI dropdown for audience selection
    """
    try:
        lists = hubspot_integration.search_lists_by_name(name_contains)
        return {
            "total": len(lists),
            "lists": [
                {
                    "id": l.get("id"),
                    "name": l.get("properties", {}).get("name"),
                    "size": l.get("properties", {}).get("listSize", 0),
                }
                for l in lists
            ]
        }
    except Exception as e:
        log.error(f"[AB-WF] Failed to get lists: {e}")
        raise HTTPException(status_code=500, detail=str(e))
