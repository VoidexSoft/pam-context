"""Extraction schemas for structured business entities."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MetricDefinition(BaseModel):
    """A business metric extracted from documentation."""

    name: str = Field(description="Name of the metric (e.g. 'DAU', 'MRR', 'Conversion Rate')")
    formula: str | None = Field(default=None, description="How the metric is calculated")
    owner: str | None = Field(default=None, description="Team or person responsible")
    data_source: str | None = Field(default=None, description="Where the data comes from")


class EventTrackingSpec(BaseModel):
    """An analytics event tracking specification."""

    event_name: str = Field(description="Name of the event (e.g. 'signup_completed')")
    properties: list[str] = Field(default_factory=list, description="Event properties/attributes")
    trigger: str | None = Field(default=None, description="What triggers this event")


class KPITarget(BaseModel):
    """A KPI target or goal."""

    metric: str = Field(description="Name of the metric")
    target_value: str = Field(description="Target value (e.g. '50000', '3.5%', '$2M')")
    period: str | None = Field(default=None, description="Time period (e.g. 'Q1 2025', 'monthly')")
    owner: str | None = Field(default=None, description="Team or person responsible")


class ExtractedEntityData(BaseModel):
    """Wrapper for any extracted entity with its type and source info."""

    entity_type: str  # "metric_definition", "event_tracking_spec", "kpi_target"
    entity_data: dict  # Serialized entity
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_segment_id: uuid.UUID | None = None
    source_text: str = ""  # The text from which this was extracted


# Schema descriptions for LLM extraction prompts
EXTRACTION_SCHEMAS = {
    "metric_definition": {
        "model": MetricDefinition,
        "description": "A business metric with its name, calculation formula, owner, and data source.",
        "examples": [
            "DAU (Daily Active Users) is calculated as the count of unique users who logged in within 24 hours.",
            "MRR is owned by the Finance team and sourced from the billing system.",
        ],
    },
    "event_tracking_spec": {
        "model": EventTrackingSpec,
        "description": "An analytics event with its name, properties, and trigger condition.",
        "examples": [
            "The signup_completed event fires when a user submits the registration form. Properties: user_id, signup_method, referral_source.",
        ],
    },
    "kpi_target": {
        "model": KPITarget,
        "description": "A KPI target or goal with its metric, target value, period, and owner.",
        "examples": [
            "DAU target for Q1 2025: 50,000 (owned by Growth team).",
            "Conversion rate goal: 3.5% monthly.",
        ],
    },
}
