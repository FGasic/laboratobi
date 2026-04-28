from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CriticalMoment(Base):
    __tablename__ = "critical_moments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ply_index: Mapped[int] = mapped_column(Integer, nullable=False)
    moment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    validation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    validation_invalid_reason: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    validation_played_move_san: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    validation_engine_best_move: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    validation_engine_principal_variation_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    validation_best_eval_cp: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    validation_played_eval_cp: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    validation_objective_gap_cp: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    validation_objective_gap_depth: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    validation_equivalent_move_band_reject: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    validation_borderline_recheck: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    validation_depth24_gap_cp: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    ranking_phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ranking_phase_preference_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ranking_final_candidate_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ranking_objective_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ranking_transferable_idea_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ranking_objective_gap_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ranking_difficulty_adequacy_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
