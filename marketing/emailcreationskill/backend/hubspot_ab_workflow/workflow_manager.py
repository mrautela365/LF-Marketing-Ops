"""
A/B Workflow Manager
Orchestrates the A/B testing workflow lifecycle
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from .models import (
    ABTestConfig, ABTestStatus, ABTestRequest, ABTestResults,
    ABTestListItem, WinnerMetric
)
from . import hubspot_integration as hs

log = logging.getLogger("email-staging")

# In-memory storage for this session
# In production, use a real database
_ab_tests: dict[str, ABTestConfig] = {}
_ab_results: dict[str, ABTestResults] = {}


def create_ab_test(req: ABTestRequest) -> ABTestConfig:
    """
    Create a new A/B test configuration
    Status: DRAFT (not yet launched)
    """
    test_id = str(uuid.uuid4())

    test = ABTestConfig(
        id=test_id,
        variant_a_email_id=req.variant_a_email_id,
        variant_a_email_name=req.variant_a_email_name,
        variant_b_email_id=req.variant_b_email_id,
        variant_b_email_name=req.variant_b_email_name,
        audience_list_id=req.audience_list_id,
        audience_list_name=req.audience_list_name,
        test_sample_size=req.test_sample_size,
        test_duration_hours=req.test_duration_hours,
        winner_metric=WinnerMetric(req.winner_metric),
        status=ABTestStatus.DRAFT,
        created_at=datetime.now(),
    )

    _ab_tests[test_id] = test
    log.info(f"[AB-WF] Created A/B test: {test_id}")
    return test


def launch_ab_test(test_id: str) -> dict:
    """
    Launch A/B test - triggers HubSpot workflow
    Status changes: DRAFT → RUNNING
    """
    if test_id not in _ab_tests:
        raise ValueError(f"A/B test {test_id} not found")

    test = _ab_tests[test_id]

    # Create workflow in HubSpot
    workflow = hs.create_hubspot_workflow(
        name=f"AB Test: {test.variant_a_email_name} vs {test.variant_b_email_name}",
        variant_a_id=test.variant_a_email_id,
        variant_b_id=test.variant_b_email_id,
    )

    # Trigger workflow execution
    execution = hs.trigger_workflow_execution(
        workflow_id=workflow["workflow_id"],
        list_id=test.audience_list_id,
        variant_a_id=test.variant_a_email_id,
        variant_b_id=test.variant_b_email_id,
        test_duration_hours=test.test_duration_hours,
    )

    # Update test status
    test.hubspot_workflow_id = workflow["workflow_id"]
    test.hubspot_workflow_execution_id = execution["execution_id"]
    test.status = ABTestStatus.RUNNING
    test.launched_at = datetime.now()

    log.info(f"[AB-WF] Launched A/B test {test_id}: {execution['execution_id']}")

    return {
        "test_id": test_id,
        "status": "launched",
        "workflow_id": workflow["workflow_id"],
        "execution_id": execution["execution_id"],
        "started_at": execution["started_at"],
        "will_complete_at": execution["will_complete_at"],
    }


def get_ab_test(test_id: str) -> Optional[ABTestConfig]:
    """Get A/B test details"""
    return _ab_tests.get(test_id)


def get_ab_test_status(test_id: str) -> dict:
    """
    Get current status of running A/B test
    Includes live stats if test is running
    """
    if test_id not in _ab_tests:
        raise ValueError(f"A/B test {test_id} not found")

    test = _ab_tests[test_id]

    # If test is running, fetch live stats
    if test.status == ABTestStatus.RUNNING:
        variant_a_stats = hs.get_email_stats(test.variant_a_email_id)
        variant_b_stats = hs.get_email_stats(test.variant_b_email_id)

        # Calculate time remaining
        time_remaining = test.test_duration_hours
        if test.launched_at:
            elapsed = (datetime.now() - test.launched_at).total_seconds() / 3600
            time_remaining = max(0, test.test_duration_hours - elapsed)

        return {
            "test_id": test_id,
            "status": "running",
            "variant_a": {
                "name": test.variant_a_email_name,
                "sent": variant_a_stats.sent,
                "opens": variant_a_stats.opens,
                "clicks": variant_a_stats.clicks,
                "open_rate": round(variant_a_stats.open_rate, 2),
                "click_rate": round(variant_a_stats.click_rate, 2),
            },
            "variant_b": {
                "name": test.variant_b_email_name,
                "sent": variant_b_stats.sent,
                "opens": variant_b_stats.opens,
                "clicks": variant_b_stats.clicks,
                "open_rate": round(variant_b_stats.open_rate, 2),
                "click_rate": round(variant_b_stats.click_rate, 2),
            },
            "time_remaining_hours": round(time_remaining, 1),
            "launched_at": test.launched_at.isoformat() if test.launched_at else None,
        }

    # If completed, return results
    if test.status == ABTestStatus.COMPLETED:
        if test_id in _ab_results:
            results = _ab_results[test_id]
            return {
                "test_id": test_id,
                "status": "completed",
                "winner": results.winner,
                "winner_email_name": results.winner_email_name,
                "confidence": results.confidence_level,
                "variant_a": {
                    "name": results.variant_a_email_name,
                    "open_rate": round(results.variant_a_stats.open_rate, 2),
                    "click_rate": round(results.variant_a_stats.click_rate, 2),
                },
                "variant_b": {
                    "name": results.variant_b_email_name,
                    "open_rate": round(results.variant_b_stats.open_rate, 2),
                    "click_rate": round(results.variant_b_stats.click_rate, 2),
                },
                "completed_at": results.winner_determined_at.isoformat(),
                "winner_sent_to_remaining": results.winner_sent_to_remaining,
            }

    return {
        "test_id": test_id,
        "status": test.status.value,
    }


def complete_ab_test(test_id: str) -> dict:
    """
    Complete A/B test and fetch final results
    Status changes: RUNNING → COMPLETED
    """
    if test_id not in _ab_tests:
        raise ValueError(f"A/B test {test_id} not found")

    test = _ab_tests[test_id]

    # Fetch results from HubSpot
    results_data = hs.get_workflow_results(
        workflow_id=test.hubspot_workflow_id,
        variant_a_id=test.variant_a_email_id,
        variant_b_id=test.variant_b_email_id,
    )

    # Update test status
    test.status = ABTestStatus.COMPLETED
    test.completed_at = datetime.now()

    # Store results
    winner_a = results_data["winner"] == "A"
    results = ABTestResults(
        test_id=test_id,
        variant_a_stats=hs.get_email_stats(test.variant_a_email_id),
        variant_a_email_id=test.variant_a_email_id,
        variant_a_email_name=test.variant_a_email_name,
        variant_b_stats=hs.get_email_stats(test.variant_b_email_id),
        variant_b_email_id=test.variant_b_email_id,
        variant_b_email_name=test.variant_b_email_name,
        winner=results_data["winner"],
        winner_email_id=results_data["winner_email_id"],
        winner_email_name=test.variant_a_email_name if winner_a else test.variant_b_email_name,
        confidence_level=results_data["confidence"],
        winner_determined_at=datetime.now(),
        remaining_audience_count=5000,  # TODO: Calculate from actual list
    )

    _ab_results[test_id] = results

    log.info(f"[AB-WF] Completed A/B test {test_id}: Winner = {results.winner}")

    return {
        "test_id": test_id,
        "status": "completed",
        "winner": results.winner,
        "winner_name": results.winner_email_name,
        "confidence": results.confidence_level,
        "variant_a_open_rate": round(results.variant_a_stats.open_rate, 2),
        "variant_b_open_rate": round(results.variant_b_stats.open_rate, 2),
    }


def get_ab_test_list() -> List[ABTestListItem]:
    """Get list of all A/B tests for history/dashboard"""
    items = []
    for test_id, test in _ab_tests.items():
        winner = None
        confidence = None
        completed_at = None

        if test_id in _ab_results:
            results = _ab_results[test_id]
            winner = results.winner
            confidence = results.confidence_level
            completed_at = results.winner_determined_at

        items.append(
            ABTestListItem(
                id=test_id,
                variant_a_name=test.variant_a_email_name,
                variant_b_name=test.variant_b_email_name,
                audience_name=test.audience_list_name,
                status=test.status,
                winner=winner,
                created_at=test.created_at,
                completed_at=completed_at,
                confidence=confidence,
            )
        )

    # Sort by created date (newest first)
    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


def archive_ab_test(test_id: str) -> dict:
    """Archive an old A/B test"""
    if test_id not in _ab_tests:
        raise ValueError(f"A/B test {test_id} not found")

    test = _ab_tests[test_id]
    test.status = ABTestStatus.ARCHIVED

    log.info(f"[AB-WF] Archived A/B test {test_id}")

    return {
        "test_id": test_id,
        "status": "archived",
    }
