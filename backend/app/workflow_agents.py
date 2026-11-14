"""Structured LangChain calls for agreement preparation and final review."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


ApplicationField = Literal["businessName", "businessActivity", "registration", "owners", "products", "sector"]


class ApplicationIssue(BaseModel):
    field: ApplicationField
    message: str = Field(min_length=1, max_length=300)


class ApplicationValidation(BaseModel):
    issues: list[ApplicationIssue] = Field(max_length=6)


class AgreementDraft(BaseModel):
    missingFields: list[Literal["businessName", "registration", "products"]]
    coverNote: str = Field(min_length=1, max_length=800)


class EvidenceCheck(BaseModel):
    findings: list[str] = Field(min_length=1, max_length=10)
    sourceIds: list[str] = Field(min_length=1, max_length=12)
    missingInputs: list[str] = Field(max_length=10)


class RiskRecommendation(EvidenceCheck):
    rationale: str = Field(min_length=1, max_length=4000)
    ownership: int = Field(ge=1, le=5)
    activity: int = Field(ge=1, le=5)
    geography: int = Field(ge=1, le=5)


class FinalAssessment(BaseModel):
    verification: EvidenceCheck
    risk: RiskRecommendation


@lru_cache(maxsize=4)
def structured_model(model: str, schema: type[BaseModel]):
    from langchain.chat_models import init_chat_model

    return init_chat_model(model, timeout=40, max_retries=1).with_structured_output(schema)


def run_skill(skill: str, schema: type[BaseModel], context: dict):
    model = os.getenv("ONBOARDING_CHAT_MODEL")
    if not model:
        raise ValueError("Configure ONBOARDING_CHAT_MODEL before running the workflow agents.")
    skill_file = Path(__file__).parent / "skills" / skill / "SKILL.md"
    instruction = skill_file.read_text(encoding="utf-8").split("---", 2)[2].strip()
    result = structured_model(model, schema).invoke([
        ("system", instruction),
        ("human", json.dumps(context, default=str)),
    ])
    return schema.model_validate(result)


def cited_sources(report, references):
    by_id = {source["_id"]: source for source in references}
    ids = list(dict.fromkeys(report.sourceIds))
    if any(identifier not in by_id for identifier in ids):
        raise ValueError("The agent returned an unknown source ID.")
    return [
        {"id": identifier, "citation": by_id[identifier]["citation"], "url": by_id[identifier].get("source_url")}
        for identifier in ids
    ]
