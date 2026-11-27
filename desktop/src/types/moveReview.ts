// snake_case on purpose: matches the future Python/SQLite backend (GĐ4–6).

export type RiskFlags = { check: boolean; capture: boolean; counterattack: boolean };

/** Player's own answers after the move. Unanswered = "" / [] / null. */
export type SelfAssessment = {
  intention: string;
  predicted_opponent_reply: string; // UCI, "" = not answered
  predicted_variations: string[]; // each a space-separated UCI line
  depth: number | null; // số nước tự nhận đã tính
  recognized_risks: RiskFlags | null; // null = "Tôi chưa xét nguy cơ"
  position_assessment: "better" | "equal" | "worse" | null;
  skipped: boolean;
};

export type EngineAnalysis = {
  source: "pikafish" | "sample";
  eval_before_cp: number; // both evals from the mover's perspective, + = good for player
  eval_after_cp: number;
  best_move: string;
  opponent_best_replies: string[]; // MultiPV after the move, best first
  principal_variation: string[]; // after the move, starts with opponent reply
  threats: RiskFlags; // threats that really exist after the move
  material_at_risk: boolean;
  // From /engine/evaluate-move only. A mate is mapped to ±(30000 − n) cp, so never subtract raw evals then.
  cp_loss?: number;
  eval_before_mate?: number | null; // moves to mate, > 0 = player mates, 0 = mate delivered
  eval_after_mate?: number | null;
};

export type PlayedMove = {
  move_number: number;
  board_before: string; // FEN
  board_after: string;
  player_move: string; // UCI
  engine: EngineAnalysis | null;
};

export type ThinkingComponent = "threatAwareness" | "responsePrediction" | "variationCalculation" | "positionEvaluation" | "pieceSafety";

export type MoveReview = {
  session_id: string;
  move_number: number;
  board_before: string;
  board_after: string;
  player_move: string;
  player_intention: string;
  predicted_opponent_reply: string;
  predicted_variations: string[];
  engine_evaluation_before: number | null;
  engine_evaluation_after: number | null;
  move_quality_score: number | null;
  thinking_quality_score: number | null;
  strengths: string[];
  missed_threats: string[];
  learning_notes: string[];
  next_training_topic: string;
  confidence: "low" | "medium" | "high";
  created_at: string; // ISO
  // UI-only extras
  move_quality_label: string;
  thinking_components: Record<ThinkingComponent, number | null>; // 0..1 each
  guiding_questions: string[];
  engine: EngineAnalysis | null;
  self_assessment: SelfAssessment;
};
