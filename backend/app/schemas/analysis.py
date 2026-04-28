from typing import Literal

from pydantic import BaseModel, Field


class FenEvaluationRequest(BaseModel):
    fen: str = Field(..., min_length=1)
    depth: int | None = Field(default=None, ge=1, le=30)


class FenEvaluationResponse(BaseModel):
    fen: str
    evaluation_cp: int | None
    mate: int | None
    best_move: str | None
    principal_variation: list[str]
    depth_used: int


class GamePositionEvaluationRequest(BaseModel):
    game_id: int = Field(..., ge=1)
    ply_index: int = Field(..., ge=1)
    depth: int | None = Field(default=None, ge=1, le=30)


class GamePositionEvaluationResponse(BaseModel):
    game_id: int
    ply_index: int
    fullmove_number: int
    san_move: str
    fen: str
    side_to_move: Literal["w", "b"]
    evaluation_cp: int | None
    mate: int | None
    best_move: str | None
    principal_variation: list[str]
    depth_used: int


class FindGameCandidatesRequest(BaseModel):
    game_id: int = Field(..., ge=1)
    depth: int | None = Field(default=None, ge=1, le=30)
    swing_threshold_cp: int = Field(default=100, ge=1)


class GameCandidateResponse(BaseModel):
    ply_index: int
    fullmove_number: int
    san_move: str
    fen: str
    side_to_move: Literal["w", "b"]
    evaluation_before_cp: int
    evaluation_after_cp: int
    swing_cp: int


class FindGameCandidatesResponse(BaseModel):
    game_id: int
    depth_used: int
    swing_threshold_cp: int
    evaluation_perspective: Literal["white"] = "white"
    candidate_count: int
    candidates: list[GameCandidateResponse]


class ReviewGameCandidatesRequest(BaseModel):
    game_id: int = Field(..., ge=1)
    depth: int | None = Field(default=None, ge=1, le=30)
    swing_threshold_cp: int = Field(default=100, ge=1)


class ReviewedGameCandidateResponse(BaseModel):
    ply_index: int
    fullmove_number: int
    played_move_san: str
    side_that_played: Literal["w", "b"]
    fen_before: str
    fen_after: str
    evaluation_before_cp: int
    evaluation_after_cp: int
    swing_cp: int
    engine_best_move: str | None
    engine_principal_variation: list[str]


class ReviewGameCandidatesResponse(BaseModel):
    game_id: int
    depth_used: int
    swing_threshold_cp: int
    evaluation_perspective: Literal["white"] = "white"
    candidate_count: int
    candidates: list[ReviewedGameCandidateResponse]


class GenerateCriticalMomentsRequest(BaseModel):
    game_id: int = Field(..., ge=1)
    depth: int | None = Field(default=None, ge=1, le=30)
    swing_threshold_cp: int = Field(default=100, ge=1)
    max_moments: int = Field(default=1, ge=1, le=10)
    min_spacing_plies: int = Field(default=8, ge=0, le=200)
    min_remaining_plies: int = Field(default=4, ge=0, le=200)


class CandidateMomentScoringResponse(BaseModel):
    game_id: int
    ply_index: int
    fullmove_number: int | None
    played_move_san: str | None
    engine_best_move: str | None
    different_move_pass: bool
    minimum_impact_pass: bool
    serious_context_pass: bool
    serious_context_route: str | None
    serious_context_reason: str | None
    not_trivial_pass: bool
    humanly_explainable_pass: bool
    candidate_richness_score: float
    opponent_resource_pressure_score: float
    objective_consequence_clarity_score: float
    difficulty_adequacy_score: float
    primary_theme: str | None
    secondary_themes: list[str]
    transferable_idea_score: float
    transferable_idea_reason: str | None
    swing_cp: int | None
    candidate_count: int | None
    best_move_stability: float | None
    moment_score_partial: float
    moment_score_with_transferable: float
    exclusion_reason: str | None


class GeneratedCriticalMomentResponse(BaseModel):
    moment_number: int
    ply_index: int
    fullmove_number: int
    san_move: str
    swing_cp: int
    objective_scoring: CandidateMomentScoringResponse | None = None
    played_move_san: str | None = None
    engine_best_move: str | None = None
    objective_gap_cp: int | None = None
    transferable_idea_score: float | None = None
    phase: str | None = None
    phase_preference_score: float | None = None
    final_candidate_score: float | None = None


class GenerateCriticalMomentsResponse(BaseModel):
    game_id: int
    depth_used: int
    swing_threshold_cp: int
    max_moments: int
    min_spacing_plies: int
    min_remaining_plies: int
    candidates_found: int
    discarded_same_move_count: int
    discarded_incomplete_review_count: int
    scored_candidates_count: int = 0
    discarded_objective_filter_count: int = 0
    eligible_candidates_count: int
    generated_count: int
    generated_moments: list[GeneratedCriticalMomentResponse]
    candidate_scoring: list[CandidateMomentScoringResponse] = Field(
        default_factory=list
    )


class SanitizeBroadcastSessionRequest(BaseModel):
    depth: int | None = Field(default=None, ge=1, le=30)
    swing_threshold_cp: int = Field(default=100, ge=1)
    max_moments: int = Field(default=1, ge=1, le=10)
    min_spacing_plies: int = Field(default=8, ge=0, le=200)
    min_remaining_plies: int = Field(default=4, ge=0, le=200)


class SanitizedCriticalMomentResponse(BaseModel):
    game_id: int
    moment_id: int | None
    ply_index: int
    action: str
    invalid_reason: str | None = None
    played_move_san: str | None = None
    engine_best_move: str | None = None
    engine_principal_variation_count: int = 0
    best_eval_cp: int | None = None
    played_eval_cp: int | None = None
    objective_gap_cp: int | None = None
    objective_gap_depth: int | None = None
    objective_gap_pass: bool = False
    equivalent_move_band_reject: bool = False
    borderline_recheck: bool = False
    depth24_gap_cp: int | None = None
    phase: str | None = None
    phase_preference_score: float | None = None
    final_candidate_score: float | None = None
    transferable_idea_score: float | None = None


class SanitizedGameResponse(BaseModel):
    game_id: int
    active_before: int
    deactivated_count: int
    regenerated: bool
    active_valid_after: int
    events: list[SanitizedCriticalMomentResponse]


class SanitizeBroadcastSessionResponse(BaseModel):
    games_checked: int
    games_remaining: int
    active_valid_moments: int
    deactivated_count: int
    objective_gap_deactivated_count: int = 0
    equivalent_band_deactivated_count: int = 0
    regenerated_games_count: int
    games: list[SanitizedGameResponse]
