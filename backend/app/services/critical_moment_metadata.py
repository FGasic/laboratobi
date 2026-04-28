from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.services.critical_moment_validation import (
    CriticalMomentReviewValidation,
    EQUIVALENT_BAND_CP,
    OBJECTIVE_GAP_THRESHOLD_CP,
)

logger = logging.getLogger("uvicorn.error")


def apply_critical_moment_validation_metadata(
    *,
    moment: Any,
    validation: CriticalMomentReviewValidation,
    review_payload: dict[str, Any] | None,
) -> None:
    moment.validation_status = "valid" if validation.is_valid else "invalid"
    moment.validation_invalid_reason = validation.invalid_reason
    moment.validation_played_move_san = (
        review_payload.get("played_move_san") if review_payload is not None else None
    )
    moment.validation_engine_best_move = (
        review_payload.get("engine_best_move") if review_payload is not None else None
    )
    moment.validation_engine_principal_variation_count = (
        len(review_payload.get("engine_principal_variation") or [])
        if review_payload is not None
        else 0
    )
    moment.validation_best_eval_cp = validation.best_eval_cp
    moment.validation_played_eval_cp = validation.played_eval_cp
    moment.validation_objective_gap_cp = validation.objective_gap_cp
    moment.validation_objective_gap_depth = validation.objective_gap_depth
    moment.validation_equivalent_move_band_reject = (
        validation.equivalent_move_band_reject
    )
    moment.validation_borderline_recheck = validation.borderline_recheck
    moment.validation_depth24_gap_cp = validation.depth24_gap_cp
    moment.validated_at = datetime.now(timezone.utc)


def has_valid_critical_moment_metadata(moment: Any) -> bool:
    return (
        moment.validation_status == "valid"
        and moment.validation_invalid_reason is None
        and moment.validation_engine_best_move is not None
        and (moment.validation_engine_principal_variation_count or 0) > 0
        and (moment.validation_objective_gap_cp or 0) >= OBJECTIVE_GAP_THRESHOLD_CP
        and moment.validation_equivalent_move_band_reject is False
    )


def has_equivalent_or_small_gap_metadata(moment: Any) -> bool:
    return (
        moment.validation_status == "invalid"
        and moment.validation_invalid_reason
        in {"objective_gap_too_small", "equivalent_move_band"}
    ) or (
        moment.validation_objective_gap_cp is not None
        and moment.validation_objective_gap_cp <= EQUIVALENT_BAND_CP
    )


def log_persisted_critical_moment_metadata_validation(
    *,
    game_id: int,
    moment: Any,
    valid: bool,
) -> None:
    logger.info(
        "critical_moment_validation: game_id=%s ply_index=%s valid=%s "
        "reason=%s normalized_played_move=%s normalized_engine_best_move=%s "
        "review_runtime_ok=%s objective_gap_pass=%s "
        "equivalent_move_band_reject=%s best_eval=%s played_eval=%s gap=%s "
        "depth=%s borderline_recheck=%s depth24_gap=%s final_valid=%s "
        "source=persisted_validation_metadata",
        game_id,
        moment.ply_index,
        format_bool(valid),
        moment.validation_invalid_reason or "none",
        moment.validation_played_move_san or "none",
        moment.validation_engine_best_move or "none",
        "true",
        format_bool(
            (moment.validation_objective_gap_cp or 0) >= OBJECTIVE_GAP_THRESHOLD_CP
        ),
        format_bool(moment.validation_equivalent_move_band_reject is True),
        format_optional_int(moment.validation_best_eval_cp),
        format_optional_int(moment.validation_played_eval_cp),
        format_optional_int(moment.validation_objective_gap_cp),
        format_optional_int(moment.validation_objective_gap_depth),
        format_bool(moment.validation_borderline_recheck is True),
        format_optional_int(moment.validation_depth24_gap_cp),
        format_bool(valid),
    )


def format_bool(value: bool) -> str:
    return "true" if value else "false"


def format_optional_int(value: int | None) -> str:
    return str(value) if value is not None else "none"
