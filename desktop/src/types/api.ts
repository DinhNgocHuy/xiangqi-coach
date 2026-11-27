// Shapes of the local FastAPI backend (backend/app/api/*.py, backend/app/schemas/*.py). snake_case on purpose.
import type { EngineAnalysis, MoveExplanation, MoveReview } from "./moveReview";

export type Side = "w" | "b";
export type Square = string | null; // uppercase = Red, lowercase = Black; null = empty
export type Placement = Square[][]; // board[rank][file], rank 0 = Red back rank
export type Orientation = "red_bottom" | "red_top";

export type Health = { status: "ok" | "degraded"; version: string; db: "ok" | "error" };
export type EngineStatus = { available: boolean; running: boolean; name: string | null; message: string | null; last_error: string | null };
export type CoachStatus = { available: boolean; provider: string | null; model: string | null; reason: string | null };

export type Grid = { x: number; y: number; width: number; height: number; cell: number };
export type CalibrateResult = { orientation: Orientation; disc_radius_px: number; grid: Grid };
export type BoardResult = {
  board: Placement;
  confidence: number[][];
  orientation: Orientation | null;
  fen_placement: string | null; // only when nothing is uncertain and the rules check passed
  low_confidence: string[]; // squares like "e0"
  problems: string[];
  grid: Grid;
  timing_ms: number;
};

export type MoveOut = { move_number: number; side: Side; uci: string; fen_before: string; fen_after: string; created_at: string };
export type SessionStatus = "active" | "ended" | "checkmate" | "stalemate";
export type SessionSummary = {
  id: string;
  started_at: string;
  ended_at: string | null;
  note: string | null;
  start_fen: string;
  fen: string;
  side_to_move: Side;
  status: SessionStatus;
  move_count: number;
};
export type SessionDetail = SessionSummary & { moves: MoveOut[] };
export type PositionResult = {
  result: "recorded" | "unchanged" | "inconsistent";
  move: MoveOut | null;
  reason: string | null;
  suggestion: string[] | null; // 2-ply line, the user must confirm it
  session: SessionSummary;
};

/** POST /engine/evaluate-move. Evals are from the mover's side; mate fields tell mapped mates from cp. */
export type MoveEvaluation = Omit<EngineAnalysis, "source" | "cp_loss" | "eval_before_mate" | "eval_after_mate"> & {
  source: string;
  move: string;
  fen_after: string;
  eval_before_mate: number | null;
  eval_after_mate: number | null;
  cp_loss: number;
  depth: number;
  depth_requested: number;
  stable: boolean;
  notes: string[];
  explanation?: MoveExplanation | null;
};

export type StoredReview = {
  session_id: string;
  move_number: number;
  move_quality_score: number | null;
  thinking_quality_score: number | null;
  created_at: string;
  review: MoveReview;
  mistakes: string[];
};

export type CoachFeedback = {
  did_well: string[];
  missed: string[];
  why_it_matters: string;
  what_to_learn: string;
  next_exercise: string;
  questions: string[];
};
export type CoachResponse = {
  source: "llm" | "rules";
  available: boolean;
  reason: string | null;
  feedback: CoachFeedback | null;
  guard: { removed: number; illegal_variations: number; truncated: number };
  model: string | null;
  provider: string | null;
};

export type Mistake = { id: number; session_id: string; move_number: number; component: string; description: string; fen: string; created_at: string };
export type MistakePage = { total: number; limit: number; offset: number; items: Mistake[] };
export type Pattern = {
  component: string;
  label: string;
  count: number;
  share: number | null;
  last_seen: string | null;
  recurring: boolean;
  recent_mistakes: number;
  trend: { week: string; avg_score: number | null; samples: number }[];
  direction: "improving" | "worsening" | "flat" | "insufficient_data";
};
export type Patterns = { total_mistakes: number; reviewed_moves: number; rule: string; message: string | null; components: Pattern[] };

export type PeriodStat = { period: string; reviews: number; avg_thinking: number | null; avg_move_quality: number | null };
export type StatsSummary = {
  message: string | null;
  total_sessions: number;
  total_reviewed_moves: number;
  avg_thinking_score: number | null;
  avg_move_quality: number | null;
  thinking_samples: number;
  move_quality_samples: number;
  null_thinking_reviews: number;
  common_mistakes: { component: string; label: string; count: number }[];
  weekly: PeriodStat[];
  monthly: PeriodStat[];
  skills_to_improve: { component: string; label: string; avg_score: number; samples: number }[];
  skills_message: string | null;
};

export type ExerciseSolution = {
  best_move: string;
  eval_cp: number;
  mate: number | null;
  principal_variation: string[];
  accepted_moves: string[];
  eval_class?: "better" | "equal" | "worse";
  player_eval_cp?: number;
};
export type Exercise = {
  id: number;
  session_id: string;
  move_number: number;
  component: string;
  component_label: string;
  type: string;
  fen: string;
  side_to_move: Side;
  answer_kind: "move" | "eval";
  prompt: string;
  engine_depth: number;
  created_at: string;
  status: "pending" | "done";
  attempts: { answer: string; correct: boolean; created_at: string }[];
  played_move: string | null;
  solution: ExerciseSolution | null; // only after an attempt
};
export type GenerateResult = { created: Exercise[]; skipped: { session_id: string; move_number: number; component: string; reason: string }[]; reason: string | null };
export type AttemptResult = { correct: boolean; explanation: string; exercise: Exercise };

export type Backup = { path: string; size_bytes: number };
