"""Customer 360 demo API with Atlas-backed onboarding conversations."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID, uuid4

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from gridfs import GridFSBucket
from gridfs.errors import NoFile
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .demo import _upsert_by_key, conversation_actor, get_database
from .documents import document_response, store_upload, stream_document
from .routers import router
from .onboarding_agent import QUESTIONS, REVIEW, WELCOME, agent_enabled, interpret_answer

load_dotenv(Path(__file__).resolve().parents[2] / "database" / ".env")

logger = logging.getLogger(__name__)

QUESTION_COUNT = len(QUESTIONS)
class ConversationPayload(BaseModel):
    id: UUID
    startedAt: datetime
    answers: list[str] = Field(default_factory=list, max_length=QUESTION_COUNT)


class AnswerPayload(BaseModel):
    sequence: int = Field(ge=0, lt=QUESTION_COUNT)
    content: str = Field(min_length=1, max_length=4000)


class ChatPayload(BaseModel):
    id: UUID
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0, lt=QUESTION_COUNT)
    content: str = Field(min_length=1, max_length=4000)


class ChatTurn(BaseModel):
    id: UUID
    sequence: int
    content: str
    clarification: str


class ConversationResponse(BaseModel):
    id: str
    startedAt: str
    answers: list[str]
    fields: list[str]
    prompts: list[str]
    turns: list[ChatTurn]
    revision: int
    agentEnabled: bool
    applicationId: str | None = None


class DocumentResponse(BaseModel):
    id: str
    filename: str
    contentType: str
    sizeBytes: int
    createdAt: str
    source: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    uri = os.environ.get("MONGODB_URI")
    database_name = os.environ.get("MONGODB_DATABASE")
    client = None
    app.state.database = None

    if uri and database_name:
        client = MongoClient(uri)
        client.admin.command("ping")
        app.state.database = client[database_name]

    try:
        yield
    finally:
        if client is not None:
            client.close()


app = FastAPI(title="Customer 360 API", lifespan=lifespan)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _read_answers(
    database: Database, conversation_id: ObjectId, session: ClientSession | None = None
) -> list[str]:
    messages = database["messages"].find(
        {"conversation_id": conversation_id, "role": "user"}, session=session
    ).sort("sequence", 1)
    return [message["content"] for message in messages]


def _conversation_response(document: dict, answers: list[str]) -> ConversationResponse:
    return ConversationResponse(
        id=document["client_id"],
        startedAt=document["created_at"].isoformat(),
        answers=answers,
        fields=[field for field, _ in QUESTIONS],
        prompts=[WELCOME + QUESTIONS[0][1], *[question for _, question in QUESTIONS[1:]], REVIEW],
        turns=document.get("chat_turns", []),
        revision=document.get("chat_revision", 0),
        agentEnabled=agent_enabled(),
        applicationId=str(document["onboarding_id"]) if document.get("application_submitted") else None,
    )


def _owned_conversation(
    database: Database, customer_id: ObjectId, conversation_id: UUID
) -> dict:
    conversation = database["conversations"].find_one(
        {"client_id": str(conversation_id), "customer_id": customer_id}
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conversation


def _save_answer(
    database: Database,
    conversation: dict,
    customer_id: ObjectId,
    sequence: int,
    content: str,
    session: ClientSession | None = None,
) -> None:
    onboarding = database.onboardings.find_one(
        {"_id": conversation["onboarding_id"], "customer_id": customer_id},
        session=session,
    )
    if onboarding is None or onboarding["status"] != "DRAFT":
        raise HTTPException(409, "This draft has already been submitted.")
    messages = database["messages"]
    query = {"conversation_id": conversation["_id"], "sequence": sequence}
    existing = messages.find_one(query, session=session)
    if existing is not None:
        if existing["content"] != content:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This answer sequence was already saved with different content.",
            )
    else:
        current_count = messages.count_documents(
            {"conversation_id": conversation["_id"], "role": "user"}, session=session
        )
        if sequence != current_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Answers must be submitted in order.",
            )
        now = datetime.now(timezone.utc)
        try:
            messages.insert_one(
                {
                    "conversation_id": conversation["_id"],
                    "role": "user",
                    "content": content,
                    "sequence": sequence,
                    "created_at": now,
                },
                session=session,
            )
        except DuplicateKeyError:
            if session is not None:
                raise
            existing = messages.find_one(query, session=session)
            if existing is None or existing["content"] != content:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This answer sequence was already saved with different content.",
                ) from None

    answers = _read_answers(database, conversation["_id"], session)
    now = datetime.now(timezone.utc)
    database["onboardings"].update_one(
        {"_id": conversation["onboarding_id"], "customer_id": customer_id, "status": "DRAFT"},
        {
            "$set": {
                "application": {"answers": answers},
                "current_step": "review" if len(answers) == QUESTION_COUNT
                else f"question_{len(answers) + 1}",
                "updated_at": now,
            }
        },
        session=session,
    )
    database["conversations"].update_one(
        {"_id": conversation["_id"]},
        {
            "$set": {
                "title": answers[0] if answers else "Business onboarding",
                "updated_at": now,
            }
        },
        session=session,
    )


@app.post("/api/v1/login", response_model=bool)
async def login() -> bool:
    """Always succeed for the customer demo; no credentials are needed."""
    return True


@app.get("/api/v1/conversations", response_model=list[ConversationResponse])
def list_conversations(request: Request):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversations = database["conversations"].find(
        {"customer_id": customer_id}
    ).sort("updated_at", -1)
    return [
        _conversation_response(
            conversation, _read_answers(database, conversation["_id"])
        )
        for conversation in conversations
    ]


@app.post(
    "/api/v1/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(payload: ConversationPayload, request: Request):
    database = get_database(request)
    customer_id, user_id = conversation_actor(database, request.query_params.get("customer_id"))
    client_id = str(payload.id)
    started_at = payload.startedAt
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    onboarding = _upsert_by_key(
        database["onboardings"],
        {"client_id": client_id, "customer_id": customer_id},
        {
            "created_at": started_at,
            "updated_at": started_at,
            "customer_id": customer_id,
            "created_by": user_id,
            "status": "DRAFT",
            "current_step": "question_1",
            "application": {"answers": []},
            "requested_products": [],
        },
    )
    conversation = _upsert_by_key(
        database["conversations"],
        {"client_id": client_id, "customer_id": customer_id},
        {
            "created_at": started_at,
            "updated_at": started_at,
            "customer_id": customer_id,
            "onboarding_id": onboarding["_id"],
            "title": "Business onboarding",
            "status": "active",
        },
    )
    for sequence, answer in enumerate(payload.answers):
        _save_answer(database, conversation, customer_id, sequence, answer)
    return _conversation_response(
        conversation, _read_answers(database, conversation["_id"])
    )


@app.post(
    "/api/v1/conversations/{conversation_id}/answers",
    response_model=ConversationResponse,
)
def save_conversation_answer(
    conversation_id: UUID, payload: AnswerPayload, request: Request
):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversation = database["conversations"].find_one(
        {"client_id": str(conversation_id), "customer_id": customer_id}
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Answer cannot be blank.",
        )
    _save_answer(
        database, conversation, customer_id, payload.sequence, content
    )
    return _conversation_response(
        conversation, _read_answers(database, conversation["_id"])
    )


@app.post("/api/v1/conversations/{conversation_id}/chat", response_model=ConversationResponse)
def send_chat_message(conversation_id: UUID, payload: ChatPayload, request: Request):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversation = _owned_conversation(database, customer_id, conversation_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Enter a message before sending.")

    turn_id = str(payload.id)

    def current_turn(document: dict, answers: list[str]) -> bool:
        for turn in document.get("chat_turns", []):
            if turn["id"] == turn_id:
                if turn["content"] == content and turn["sequence"] == payload.sequence:
                    return False
                raise HTTPException(status_code=409, detail="This message ID is already in use.")
        if document.get("chat_revision", 0) != payload.revision or len(answers) != payload.sequence:
            raise HTTPException(status_code=409, detail="This conversation changed. Reload it and try again.")
        return True

    answers = _read_answers(database, conversation["_id"])
    if not current_turn(conversation, answers):
        return _conversation_response(conversation, answers)
    if conversation.get("application_submitted"):
        raise HTTPException(409, "This draft has already been submitted.")

    recent_turns = [
        {"message": turn["content"], "clarification": turn["clarification"]}
        for turn in conversation.get("chat_turns", [])
        if turn["sequence"] == payload.sequence
    ][-5:]
    try:
        decision = interpret_answer(payload.sequence, content, recent_turns)
    except Exception as error:
        logger.warning("Onboarding guide failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="The onboarding guide is unavailable. Your message can be retried.",
        ) from None

    def persist(session: ClientSession):
        latest = database.conversations.find_one({"_id": conversation["_id"]}, session=session)
        if latest is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        latest_answers = _read_answers(database, latest["_id"], session)
        if not current_turn(latest, latest_answers):
            return _conversation_response(latest, latest_answers)
        if latest.get("application_submitted"):
            raise HTTPException(409, "This draft has already been submitted.")

        saved = database.conversations.find_one_and_update(
            {"_id": latest["_id"]},
            {
                "$inc": {"chat_revision": 1},
                "$set": {"updated_at": datetime.now(timezone.utc)},
                "$push": {
                    "chat_turns": {
                        "$each": [{
                            "id": turn_id,
                            "sequence": payload.sequence,
                            "content": content,
                            "clarification": decision.reply,
                        }],
                        "$slice": -50,
                    },
                },
            },
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if decision.action == "accept":
            _save_answer(database, saved, customer_id, payload.sequence, decision.answer, session)
            latest_answers.append(decision.answer)
        return _conversation_response(saved, latest_answers)

    with database.client.start_session() as session:
        return session.with_transaction(persist)


@app.get(
    "/api/v1/conversations/{conversation_id}/documents",
    response_model=list[DocumentResponse],
)
def list_documents(conversation_id: UUID, request: Request):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversation = _owned_conversation(database, customer_id, conversation_id)
    documents = database["documents"].find(
        {"customer_id": customer_id, "conversation_id": conversation["_id"]}
    ).sort("created_at", 1)
    return [document_response(document) for document in documents]


@app.post(
    "/api/v1/conversations/{conversation_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    conversation_id: UUID,
    request: Request,
    file: UploadFile = File(...),
):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversation = _owned_conversation(database, customer_id, conversation_id)
    return store_upload(database, customer_id, conversation["onboarding_id"], file, conversation["_id"])


@app.get("/api/v1/documents/{document_id}/download")
def download_document(document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    try:
        object_id = ObjectId(document_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    document = database["documents"].find_one(
        {"_id": object_id, "customer_id": customer_id}
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return stream_document(database, document)

@app.delete("/api/v1/conversations/{conversation_id}/documents/{document_id}")
def delete_document(conversation_id: UUID, document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = conversation_actor(database, request.query_params.get("customer_id"))
    conversation = _owned_conversation(database, customer_id, conversation_id)
    try:
        object_id = ObjectId(document_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    document = database["documents"].find_one(
        {
            "_id": object_id,
            "customer_id": customer_id,
            "conversation_id": conversation["_id"],
        }
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    try:
        GridFSBucket(database).delete(document["storage_id"])
    except NoFile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found.",
        ) from None
    database["documents"].delete_one({"_id": object_id})
    return {"deleted": True}
