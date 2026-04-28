from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Position
from app.schemas.position import PositionDevSeedRequest, PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])
SessionDep = Annotated[Session, Depends(get_db)]


def get_start_of_today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


@router.get("", response_model=list[PositionResponse])
def list_positions(db: SessionDep) -> list[Position]:
    statement = select(Position).order_by(Position.created_at.desc(), Position.id.desc())
    return list(db.scalars(statement).all())


@router.get("/today", response_model=list[PositionResponse])
def list_today_positions(db: SessionDep) -> list[Position]:
    start_of_day_utc = get_start_of_today_utc()
    statement = (
        select(Position)
        .where(Position.created_at >= start_of_day_utc)
        .order_by(Position.created_at.desc(), Position.id.desc())
    )
    return list(db.scalars(statement).all())


@router.get("/featured", response_model=PositionResponse)
def get_featured_position(db: SessionDep) -> Position:
    start_of_day_utc = get_start_of_today_utc()

    featured_statement = (
        select(Position)
        .where(
            Position.created_at >= start_of_day_utc,
            Position.is_featured.is_(True),
        )
        .order_by(Position.created_at.desc(), Position.id.desc())
        .limit(1)
    )
    featured_position = db.scalar(featured_statement)
    if featured_position is not None:
        return featured_position

    fallback_statement = (
        select(Position)
        .where(Position.created_at >= start_of_day_utc)
        .order_by(Position.created_at.desc(), Position.id.desc())
        .limit(1)
    )
    latest_today_position = db.scalar(fallback_statement)
    if latest_today_position is not None:
        return latest_today_position

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No positions available for today.",
    )


@router.post(
    "/dev-seed",
    response_model=PositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dev_seed(
    payload: PositionDevSeedRequest,
    db: SessionDep,
) -> Position:
    position = Position(**payload.model_dump())
    db.add(position)
    db.commit()
    db.refresh(position)
    return position
