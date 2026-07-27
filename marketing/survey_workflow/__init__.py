"""
Survey Workflow - standalone Asana task automation service.

Accepts a single parent Asana task URL, reports which stage of the
Content -> Provide List -> Staging -> Approval -> Launch -> Campaign Update
pipeline the task is at, and - once Content + Provide List are both
complete - builds 1 or N draft emails using the same AI logic as the
emailcreationskill service (same llm_gateway, same models, same tools).
"""

from .asana_workflow import SurveyWorkflow, run_survey_workflow

__all__ = [
    "SurveyWorkflow",
    "run_survey_workflow",
]
