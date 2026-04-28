from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GameBase(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=255)
    white_player: str = Field(..., min_length=1, max_length=255)
    black_player: str = Field(..., min_length=1, max_length=255)
    result: str = Field(..., min_length=1, max_length=20)
    pgn_text: str = Field(..., min_length=1)


class GameResponse(GameBase):
    id: int
    source_type: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    round_id: str | None = None
    tournament_id: str | None = None
    pgn_hash: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecentBroadcastGameResponse(BaseModel):
    id: int
    display_event_name: str
    event_name: str
    white_player: str
    black_player: str
    result: str
    critical_moments_count: int
    created_at: datetime
    source_type: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    round_id: str | None = None
    tournament_id: str | None = None


class BroadcastSessionGameResponse(RecentBroadcastGameResponse):
    critical_moments: list["CriticalMomentResponse"] = Field(default_factory=list)


class BroadcastSessionResponse(BaseModel):
    games: list[BroadcastSessionGameResponse] = Field(default_factory=list)


class GameImportResponse(BaseModel):
    pgn_dir: str
    files_found: int
    imported_count: int
    skipped_count: int


class CriticalMomentCreateRequest(BaseModel):
    ply_index: int = Field(..., ge=1)
    moment_number: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=255)
    label: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    is_active: bool = True


class CriticalMomentDevSeedRequest(BaseModel):
    ply_indexes: list[int] = Field(default_factory=lambda: [26, 55], min_length=1)


class CriticalMomentResponse(BaseModel):
    id: int
    game_id: int
    ply_index: int
    moment_number: int
    title: str | None
    label: str | None
    notes: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GamePositionResponse(BaseModel):
    ply_index: int
    fullmove_number: int
    san_move: str
    from_square: str
    to_square: str
    fen: str
    side_to_move: Literal["w", "b"]


class GamePositionDetailResponse(BaseModel):
    game_id: int
    event_name: str
    white_player: str
    black_player: str
    result: str
    ply_index: int
    fullmove_number: int
    san_move: str
    from_square: str
    to_square: str
    fen: str
    side_to_move: Literal["w", "b"]
    next_moves: list[str]


BroadcastSessionGameResponse.model_rebuild()
