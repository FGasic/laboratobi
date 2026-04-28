from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    fen: Mapped[str] = mapped_column(Text, nullable=False)
    side_to_move: Mapped[str] = mapped_column(String(1), nullable=False)
    solution_moves: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    white_player: Mapped[str] = mapped_column(String(255), nullable=False)
    black_player: Mapped[str] = mapped_column(String(255), nullable=False)
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
