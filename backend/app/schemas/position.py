from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PositionBase(BaseModel):
    fen: str = Field(..., min_length=1)
    side_to_move: Literal["w", "b"]
    solution_moves: list[str] = Field(..., min_length=1)
    event_name: str = Field(..., min_length=1, max_length=255)
    white_player: str = Field(..., min_length=1, max_length=255)
    black_player: str = Field(..., min_length=1, max_length=255)
    is_featured: bool = False


class PositionDevSeedRequest(PositionBase):
    fen: str = "6k1/5ppp/8/8/8/5Q2/5PPP/6K1 w - - 0 1"
    side_to_move: Literal["w", "b"] = "w"
    solution_moves: list[str] = Field(default_factory=lambda: ["Qxf7+"])
    event_name: str = "LaboraTobi Dev Seed"
    white_player: str = "White Trainer"
    black_player: str = "Black Defender"
    is_featured: bool = True


class PositionResponse(PositionBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
