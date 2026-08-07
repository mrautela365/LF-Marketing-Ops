"""
Data models for HubSpot Workflow A/B Testing Feature
Completely isolated - can be removed without affecting other modules
"""
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum


class ABTestStatus(str, Enum):
    """A/B test lifecycle states"""
    DRAFT = "draft"           # Created but not launched
    RUNNING = "running"       # Workflow active
    COMPLETED = "completed"   # 24h window closed, winner selected
    ARCHIVED = "archived"     # Old test, moved to history


class WinnerMetric(str, Enum):
    """Metric used to determine winning variant"""
    OPEN_RATE = "open_rate"
    CLICK_RATE = "click_rate"
    CONVERSION_RATE = "conversion_rate"


@dataclass
class ABTestConfig:
    """Configuration for A/B test"""
    id: Optional[str] = None

    # Variants
    variant_a_email_id: str = None
    variant_a_email_name: str = None
    variant_b_email_id: str = None
    variant_b_email_name: str = None

    # Test Settings
    audience_list_id: str = None
    audience_list_name: str = None
    test_sample_size: int = 50  # % of audience (50 = 50/50 split)
    test_duration_hours: int = 24
    winner_metric: WinnerMetric = WinnerMetric.OPEN_RATE

    # HubSpot Integration
    hubspot_workflow_id: Optional[str] = None
    hubspot_workflow_execution_id: Optional[str] = None

    # Status
    status: ABTestStatus = ABTestStatus.DRAFT
    created_at: Optional[datetime] = None
    launched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class EmailStats:
    """Email statistics from HubSpot"""
    sent: int = 0
    opens: int = 0
    clicks: int = 0
    conversions: int = 0
    open_rate: float = 0.0
    click_rate: float = 0.0
    conversion_rate: float = 0.0


@dataclass
class ABTestResults:
    """Results of completed A/B test"""
    test_id: str

    # Variant A Stats
    variant_a_stats: EmailStats
    variant_a_email_id: str
    variant_a_email_name: str

    # Variant B Stats
    variant_b_stats: EmailStats
    variant_b_email_id: str
    variant_b_email_name: str

    # Winner determination
    winner: str  # "A" or "B"
    winner_email_id: str
    winner_email_name: str
    confidence_level: float  # 0-100
    winner_determined_at: datetime

    # Remaining audience
    remaining_audience_count: int
    winner_sent_to_remaining: bool = False
    winner_sent_at: Optional[datetime] = None


@dataclass
class ABTestRequest:
    """Request to create and launch A/B test"""
    variant_a_email_id: str
    variant_a_email_name: str
    variant_b_email_id: str
    variant_b_email_name: str

    audience_list_id: str
    audience_list_name: str

    test_sample_size: int = 50  # % of audience
    test_duration_hours: int = 24
    winner_metric: str = "open_rate"


@dataclass
class ABTestListItem:
    """For displaying list of past A/B tests"""
    id: str
    variant_a_name: str
    variant_b_name: str
    audience_name: str
    status: ABTestStatus
    winner: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    confidence: Optional[float]
