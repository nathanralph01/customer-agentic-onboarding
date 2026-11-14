"""Interpret a single onboarding field. The API owns workflow progression."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

QUESTIONS = (
    ("Business name", "What is the legal name of your business?"),
    ("Business activity", "What does your business do, and which industry does it operate in?"),
    ("Registration location", "Where is your business registered? Please include the country and province or state."),
    ("Business owners", "Who owns your business? Please list the owners and their ownership percentages."),
    ("Banking products", "Which banking products are you interested in? For example, a business account, payments or a credit facility."),
)
WELCOME = "Hi, I’m your onboarding guide. I’ll help you gather your business details, one question at a time. "
REVIEW = "Your business details are ready to review. You can also attach company documents to your draft."
SKILL = Path(__file__).parent / "skills" / "onboarding-intake" / "SKILL.md"
SYSTEM_INSTRUCTION = SKILL.read_text(encoding="utf-8").split("---", 2)[2].strip()


class IntakeDecision(BaseModel):
    action: Literal["accept", "clarify"]
    answer: str = Field(max_length=4000)
    reply: str = Field(max_length=600)

    @model_validator(mode="after")
    def check_payload(self):
        self.answer = self.answer.strip()
        self.reply = self.reply.strip()
        if self.action == "accept" and self.answer and not self.reply:
            return self
        if self.action == "clarify" and self.reply and not self.answer:
            return self
        raise ValueError("Invalid onboarding decision")


def agent_enabled() -> bool:
    return bool(os.getenv("ONBOARDING_CHAT_MODEL"))


def interpret_answer(
    step: int, content: str, recent_turns: list[dict[str, str]]
) -> IntakeDecision:
    model = os.getenv("ONBOARDING_CHAT_MODEL")
    if not model:
        return IntakeDecision(action="accept", answer=content, reply="")

    from langchain.chat_models import init_chat_model

    field, question = QUESTIONS[step]
    structured_model = init_chat_model(model).with_structured_output(IntakeDecision)
    decision = structured_model.invoke([
        ("system", SYSTEM_INSTRUCTION),
        ("human", json.dumps({
            "field": field,
            "question": question,
            "recent_clarifications": recent_turns,
            "message": content,
        })),
    ])
    return IntakeDecision.model_validate(decision)
