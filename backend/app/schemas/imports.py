from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BroadcastPreviewRequest(BaseModel):
    round_id: str | None = Field(default=None, min_length=8, max_length=8)
    round_url: str | None = Field(default=None, min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    include_pgn_text: bool = False

    @model_validator(mode="after")
    def validate_round_source(self) -> "BroadcastPreviewRequest":
        if self.round_id or self.round_url:
            return self

        raise ValueError("Provide round_id or round_url.")


class BroadcastPreviewGameResponse(BaseModel):
    event_name: str
    white_player: str
    black_player: str
    result: str
    external_id: str | None = None
    game_url: str | None = None
    site_url: str | None = None
    variant: str | None = None
    white_title: str | None = None
    black_title: str | None = None
    white_elo: str | None = None
    black_elo: str | None = None
    white_fide_id: str | None = None
    black_fide_id: str | None = None
    pgn_snippet: str
    pgn_text: str | None = None


class BroadcastQualitySummaryResponse(BaseModel):
    games_analyzed: int
    games_with_titles: int
    games_with_ratings: int
    games_with_fide_ids: int
    average_known_rating: int | None = None
    average_ply_count: float
    short_games_count: int
    setup_games_count: int
    unknown_player_count: int


class BroadcastQualityResponse(BaseModel):
    is_serious_gm_broadcast: bool
    quality_score: int
    confidence: Literal["low", "medium", "high"]
    reasons: list[str]
    blocking_reasons: list[str]
    summary: BroadcastQualitySummaryResponse


class BroadcastPreviewResponse(BaseModel):
    source_type: Literal["broadcast"] = "broadcast"
    source_url: str
    source_host: str = "lichess.org"
    round_id: str
    round_url: str
    tournament_id: str | None = None
    tournament_name: str
    round_name: str
    games_found: int
    games_previewed: int
    quality: BroadcastQualityResponse
    games: list[BroadcastPreviewGameResponse]


class BroadcastImportRequest(BaseModel):
    round_id: str = Field(..., min_length=8, max_length=8)
    external_ids: list[str] = Field(..., min_length=1)
    allow_low_quality: bool = False
    generate_critical_moments: bool = False
    depth: int | None = Field(default=None, ge=1, le=30)
    swing_threshold_cp: int = Field(default=100, ge=1)
    max_moments: int = Field(default=3, ge=1, le=10)
    min_spacing_plies: int = Field(default=8, ge=0, le=200)
    min_remaining_plies: int = Field(default=4, ge=0, le=200)

    @model_validator(mode="after")
    def normalize_external_ids(self) -> "BroadcastImportRequest":
        normalized_external_ids: list[str] = []
        seen_external_ids: set[str] = set()

        self.round_id = self.round_id.strip()
        for external_id in self.external_ids:
            normalized_external_id = external_id.strip()
            if not normalized_external_id:
                continue

            if normalized_external_id in seen_external_ids:
                continue

            seen_external_ids.add(normalized_external_id)
            normalized_external_ids.append(normalized_external_id)

        if not normalized_external_ids:
            raise ValueError("Provide at least one external_id.")

        self.external_ids = normalized_external_ids
        return self


class BroadcastImportedGameResponse(BaseModel):
    id: int
    event_name: str
    white_player: str
    black_player: str
    result: str
    external_id: str | None = None
    source_url: str | None = None
    analysis_requested: bool = False
    critical_moments_generated: bool = False
    generated_moments_count: int = 0
    generated_moment_ply_indexes: list[int] = Field(default_factory=list)
    analysis_error: str | None = None


class BroadcastSkippedGameResponse(BaseModel):
    external_id: str
    reason: str
    existing_game_id: int | None = None


class BroadcastImportResponse(BaseModel):
    source_type: Literal["broadcast"] = "broadcast"
    round_id: str
    round_url: str
    tournament_id: str | None = None
    tournament_name: str
    round_name: str
    quality: BroadcastQualityResponse
    generate_critical_moments: bool = False
    requested_count: int
    imported_count: int
    skipped_count: int
    analyzed_count: int
    total_generated_moments: int
    imported_games: list[BroadcastImportedGameResponse]
    skipped_games: list[BroadcastSkippedGameResponse]
