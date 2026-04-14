from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api import schemas
from app.db.session import get_session
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService

router = APIRouter(prefix="/api/v1", tags=["v1"])
DbSession = Annotated[Session, Depends(get_session)]


@router.get("/health", response_model=schemas.HealthResponse, tags=["health"])
async def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok")


@router.post(
    "/repositories",
    response_model=schemas.RepositoryRead,
    status_code=201,
    tags=["repositories"],
)
async def create_repository(
    payload: schemas.RepositoryCreate, session: DbSession
) -> schemas.RepositoryRead:
    return RepositoryService(session).create_repository(payload)


@router.post(
    "/analyses",
    response_model=schemas.AnalysisAccepted,
    status_code=202,
    tags=["analyses"],
)
async def create_analysis(payload: schemas.AnalysisCreate, session: DbSession) -> schemas.AnalysisAccepted:
    return AnalysisService(session).create_analysis(payload)


@router.get(
    "/analyses/{analysis_id}",
    response_model=schemas.AnalysisResult,
    tags=["analyses"],
)
async def get_analysis(analysis_id: UUID, session: DbSession) -> schemas.AnalysisResult:
    return AnalysisService(session).get_analysis(analysis_id)


@router.get(
    "/analyses/{analysis_id}/report",
    response_class=PlainTextResponse,
    tags=["analyses"],
)
async def get_analysis_report(analysis_id: UUID, session: DbSession) -> PlainTextResponse:
    return PlainTextResponse(
        AnalysisService(session).get_report(analysis_id), media_type="text/markdown"
    )
