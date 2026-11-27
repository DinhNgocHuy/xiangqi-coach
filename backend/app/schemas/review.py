"""MoveReview as produced by desktop/src/services/moveReview.ts (snake_case, stored as JSON)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Score01 = float | None
Text = Annotated[str, Field(max_length=500)]
COMPONENTS = ("threatAwareness", "responsePrediction", "variationCalculation", "positionEvaluation", "pieceSafety")


class ThinkingComponents(BaseModel):
    # All five keys are required; null = the player did not answer that part.
    threatAwareness: Score01 = Field(ge=0, le=1)
    responsePrediction: Score01 = Field(ge=0, le=1)
    variationCalculation: Score01 = Field(ge=0, le=1)
    positionEvaluation: Score01 = Field(ge=0, le=1)
    pieceSafety: Score01 = Field(ge=0, le=1)


class MoveReviewIn(BaseModel):
    """Required fields are validated; UI-only extras (engine, self_assessment, …) are kept as-is."""

    model_config = ConfigDict(extra="allow")

    session_id: str = Field(max_length=64)
    move_number: int = Field(ge=1)
    board_before: str = Field(max_length=200)
    board_after: str = Field(max_length=200)
    player_move: str = Field(max_length=5)
    move_quality_score: float | None = Field(ge=0, le=100)
    thinking_quality_score: float | None = Field(ge=0, le=100)
    thinking_components: ThinkingComponents
    strengths: list[Text] = Field(default=[], max_length=20)
    missed_threats: list[Text] = Field(default=[], max_length=20)
    learning_notes: list[Text] = Field(default=[], max_length=20)
    next_training_topic: str = Field(default="", max_length=500)
    confidence: Literal["low", "medium", "high"]
    created_at: str = Field(max_length=40)


class StoredReview(BaseModel):
    session_id: str
    move_number: int
    move_quality_score: float | None
    thinking_quality_score: float | None
    created_at: str
    review: dict  # the MoveReview JSON as submitted
    mistakes: list[str]  # components recorded as thinking mistakes for this move
