// Rule-based move review. Never invents moves: every move in the output comes from engine data or the player's input.
import type { MoveEvaluation } from "../types/api";
import type { EngineAnalysis, MoveReview, PlayedMove, RiskFlags, SelfAssessment, ThinkingComponent } from "../types/moveReview";

export const THINKING_WEIGHTS: Record<ThinkingComponent, number> = {
  threatAwareness: 20,
  responsePrediction: 25,
  variationCalculation: 25,
  positionEvaluation: 20,
  pieceSafety: 10,
};

export const NO_DATA = "Chưa đủ dữ liệu đánh giá";

const COMPONENTS = Object.keys(THINKING_WEIGHTS) as ThinkingComponent[];
const RISKS: { key: keyof RiskFlags; label: string }[] = [
  { key: "check", label: "bị chiếu" },
  { key: "capture", label: "bị bắt quân" },
  { key: "counterattack", label: "bị phản công" },
];
const POSITION_LABEL = { better: "tốt hơn", equal: "cân bằng", worse: "kém hơn" } as const;
const POSITION_RANK = { worse: -1, equal: 0, better: 1 } as const;

export const TRAINING_TOPICS: Record<ThinkingComponent, string> = {
  threatAwareness: "Nhận diện đe dọa: chiếu, bắt quân",
  responsePrediction: "Dự đoán nước đáp trả mạnh nhất của đối thủ",
  variationCalculation: "Tính biến chính xác và sâu hơn",
  positionEvaluation: "Đánh giá thế cờ: vật chất, an toàn Tướng, hoạt động quân",
  pieceSafety: "An toàn quân cờ: quân không được bảo vệ",
};

const QUESTIONS: Record<ThinkingComponent, string> = {
  threatAwareness: "Sau nước đi này, đối thủ có nước chiếu, bắt quân hay phản công nào không?",
  responsePrediction: "Nếu bạn là đối thủ, bạn sẽ đáp trả bằng nước nào mạnh nhất?",
  variationCalculation: "Bạn có thể đi tiếp biến chính thêm 2–3 nước và kiểm tra từng nước không?",
  positionEvaluation: "Sau nước đi này, bên nào có lợi hơn về vật chất và độ an toàn của Tướng?",
  pieceSafety: "Sau nước đi này, quân nào của bạn không còn được bảo vệ?",
};

const norm = (m: string) => m.trim().toLowerCase();
const fmt = (cp: number) => (cp > 0 ? `+${cp}` : `${cp}`);
const line = (v: string) => v.trim().toLowerCase().split(/\s+/).filter(Boolean);

// ponytail: thresholds (20/50/100/200/300 cp) are provisional until calibrated with real Pikafish data (GĐ4).
export function moveQuality(engine: EngineAnalysis | null): { score: number | null; label: string } {
  if (!engine) return { score: null, label: NO_DATA };
  // Backend cp_loss already handles mate scores (mapped ±30000); raw subtraction is only for engine data without it.
  const loss = Math.max(0, engine.cp_loss ?? engine.eval_before_cp - engine.eval_after_cp);
  const score = loss <= 20 ? 100 : loss >= 300 ? 0 : Math.round((100 * (300 - loss)) / 280);
  const label = loss <= 20 ? "Rất tốt" : loss <= 50 ? "Tốt" : loss <= 100 ? "Thiếu chính xác" : loss <= 200 ? "Sai lầm" : "Sai lầm nghiêm trọng";
  const change = mateChange(engine);
  return { score, label: label + (change?.decisive ? ` — ${change.text}` : "") };
}

const isMate = (m: number | null | undefined): m is number => m !== null && m !== undefined;

/**
 * How a forced mate changed with the move (player's side), or null when no mate is involved.
 * decisive = a winning mate was lost or the player walked into one; other mate changes are only described.
 */
export function mateChange(e: EngineAnalysis): { text: string; decisive: boolean } | null {
  const winBefore = isMate(e.eval_before_mate) && e.eval_before_cp > 0;
  const lostBefore = isMate(e.eval_before_mate) && e.eval_before_cp < 0;
  const winAfter = isMate(e.eval_after_mate) && e.eval_after_cp > 0;
  const lostAfter = isMate(e.eval_after_mate) && e.eval_after_cp < 0;
  if (winBefore && !winAfter) return { text: "bỏ lỡ đường chiếu hết", decisive: true };
  if (lostAfter && !lostBefore) return { text: "đối thủ có đường chiếu hết", decisive: true };
  if (winBefore) return { text: "vẫn giữ được đường chiếu hết", decisive: false };
  if (lostBefore && lostAfter) return { text: "vẫn đang bị đối thủ chiếu hết", decisive: false };
  if (lostBefore) return { text: "thoát khỏi đường chiếu hết của đối thủ", decisive: false };
  if (winAfter) return { text: "tạo ra đường chiếu hết", decisive: false };
  return null;
}

/** Eval text from the player's side: centipawns, or "chiếu hết" wording when the engine reports a mate. */
export function evalText(cp: number | null, mate?: number | null): string {
  if (cp === null) return "—";
  if (!isMate(mate)) return fmt(cp);
  if (mate === 0) return cp > 0 ? "đã chiếu hết" : "bị chiếu hết";
  return mate > 0 ? `chiếu hết sau ${mate} nước` : `bị chiếu hết sau ${-mate} nước`;
}

/** /engine/evaluate-move → EngineAnalysis. Keeps cp_loss and mate fields so mates are never treated as cp. */
export function fromEvaluation(ev: MoveEvaluation): EngineAnalysis {
  return {
    source: "pikafish",
    eval_before_cp: ev.eval_before_cp,
    eval_after_cp: ev.eval_after_cp,
    best_move: ev.best_move,
    opponent_best_replies: ev.opponent_best_replies,
    principal_variation: ev.principal_variation,
    threats: ev.threats,
    material_at_risk: ev.material_at_risk,
    cp_loss: ev.cp_loss,
    eval_before_mate: ev.eval_before_mate,
    eval_after_mate: ev.eval_after_mate,
  };
}

function engineClass(cp: number): keyof typeof POSITION_RANK {
  return cp > 50 ? "better" : cp < -50 ? "worse" : "equal";
}

/** Longest common prefix (in moves) between the player's lines and the engine PV (which starts after the player's move). */
function matchedPrefix(variations: string[], pv: string[], playerMove: string): number {
  const engineLine = pv.map(norm);
  return Math.max(0, ...variations.map((v) => {
    const moves = line(v);
    if (moves[0] === norm(playerMove)) moves.shift(); // player may start the line with their own move
    let k = 0;
    while (k < moves.length && k < engineLine.length && moves[k] === engineLine[k]) k++;
    return k;
  }));
}

const answeredVariations = (sa: SelfAssessment) => sa.predicted_variations.filter((v) => v.trim() !== "");

export function thinkingComponents(sa: SelfAssessment, engine: EngineAnalysis | null, playerMove = ""): Record<ThinkingComponent, number | null> {
  const none = { threatAwareness: null, responsePrediction: null, variationCalculation: null, positionEvaluation: null, pieceSafety: null };
  if (!engine || sa.skipped) return none;
  const risks = sa.recognized_risks;
  const reply = norm(sa.predicted_opponent_reply);
  const replies = engine.opponent_best_replies.map(norm);
  const variations = answeredVariations(sa);
  const pv = engine.principal_variation;

  let responsePrediction: number | null = null;
  if (reply && replies.length) responsePrediction = reply === replies[0] ? 1 : replies.includes(reply) ? 0.5 : 0;

  let positionEvaluation: number | null = null;
  if (sa.position_assessment) {
    const diff = Math.abs(POSITION_RANK[sa.position_assessment] - POSITION_RANK[engineClass(engine.eval_after_cp)]);
    positionEvaluation = diff === 0 ? 1 : diff === 1 ? 0.5 : 0;
  }

  return {
    threatAwareness: risks ? RISKS.filter((r) => risks[r.key] === engine.threats[r.key]).length / 3 : null,
    responsePrediction,
    variationCalculation: variations.length && pv.length ? Math.min(1, matchedPrefix(variations, pv, playerMove) / Math.min(pv.length, 4)) : null,
    positionEvaluation,
    pieceSafety: risks ? (engine.material_at_risk ? (risks.capture ? 1 : 0) : 1) : null,
  };
}

/** Thinking score never uses move quality: any unanswered component → null. */
export function thinkingScore(components: Record<ThinkingComponent, number | null>): number | null {
  let sum = 0;
  for (const c of COMPONENTS) {
    const v = components[c];
    if (v === null) return null;
    sum += THINKING_WEIGHTS[c] * v;
  }
  return Math.round(sum);
}

type Issue = { weight: number; text: string; note: string };

export function buildMoveReview(sessionId: string, played: PlayedMove, sa: SelfAssessment, now = new Date()): MoveReview {
  const engine = played.engine;
  const quality = moveQuality(engine);
  const components = thinkingComponents(sa, engine, played.player_move);
  const strengths: string[] = [];
  const issues: Issue[] = [];
  const learning_notes: string[] = [];

  if (!engine) {
    learning_notes.push("Chưa có dữ liệu engine đã xác thực cho nước này.");
  } else {
    const before = engine.eval_before_cp;
    const after = engine.eval_after_cp;
    const loss = engine.cp_loss ?? before - after;
    const b = evalText(before, engine.eval_before_mate);
    const a = evalText(after, engine.eval_after_mate);
    const change = mateChange(engine);
    learning_notes.push(
      loss > 0
        ? `Thế cờ thay đổi từ ${b} xuống ${a} (${change ? (change.decisive ? `mất lợi thế quyết định: ${change.text}` : change.text) : `mất ${loss} điểm`}).`
        : `Thế cờ thay đổi từ ${b} thành ${a} (${change ? change.text : "không mất điểm"}).`,
    );

    const risks = sa.skipped ? null : sa.recognized_risks;
    if (risks) {
      for (const r of RISKS) {
        if (engine.threats[r.key] && !risks[r.key]) {
          const material = r.key === "capture" && engine.material_at_risk;
          issues.push({
            weight: THINKING_WEIGHTS.threatAwareness + (material ? THINKING_WEIGHTS.pieceSafety : 0),
            text: `Bạn chưa nhận ra nguy cơ ${r.label} sau nước đi này${material ? " — quân của bạn có thể bị mất" : ""}.`,
            note: `Trước khi đi, hãy kiểm tra mọi nước đối thủ có thể làm bạn ${r.label}.`,
          });
        } else if (!engine.threats[r.key] && risks[r.key]) {
          issues.push({
            weight: 5,
            text: `Bạn lo ngại nguy cơ ${r.label} nhưng thực tế nguy cơ này không tồn tại.`,
            note: `Lo ngại nguy cơ ${r.label} không có thật có thể khiến bạn bỏ lỡ nước đi chủ động.`,
          });
        }
      }
    }

    if (components.responsePrediction !== null && components.responsePrediction < 1) {
      issues.push({
        weight: THINKING_WEIGHTS.responsePrediction,
        text: `Bạn dự đoán ${norm(sa.predicted_opponent_reply)}, nhưng đó chưa phải phản ứng mạnh nhất của đối thủ.`,
        note: "Trước khi đi, hãy liệt kê 2–3 nước đáp trả mạnh nhất của đối thủ và chọn nước đi chịu được tất cả.",
      });
    }

    if (components.positionEvaluation !== null && components.positionEvaluation < 1 && sa.position_assessment) {
      issues.push({
        weight: THINKING_WEIGHTS.positionEvaluation,
        text: `Bạn đánh giá thế cờ là "${POSITION_LABEL[sa.position_assessment]}" nhưng engine đánh giá "${POSITION_LABEL[engineClass(after)]}" (${b} → ${a}).`,
        note: "So sánh vật chất, độ an toàn của Tướng và hoạt động quân trước khi kết luận thế cờ.",
      });
    }

    const variations = answeredVariations(sa);
    if (!sa.skipped && sa.depth !== null && variations.length && engine.principal_variation.length) {
      const k = matchedPrefix(variations, engine.principal_variation, played.player_move);
      if (sa.depth > k) {
        issues.push({
          weight: THINKING_WEIGHTS.variationCalculation,
          text: `Bạn nói đã tính ${sa.depth} nước nhưng biến của bạn chỉ khớp với engine ${k} nước.`,
          note: "Tính ít nước nhưng chính xác tốt hơn tính nhiều nước nhưng sai ngay từ nhánh đầu.",
        });
      }
    }

    // Strengths: one line per perfect component, always with the reason.
    if (components.threatAwareness === 1) {
      const real = RISKS.filter((r) => engine.threats[r.key]).map((r) => r.label);
      strengths.push(real.length ? `Bạn đã nhận ra đúng nguy cơ: ${real.join(", ")}.` : "Bạn đã đánh giá đúng rằng sau nước đi không có nguy cơ chiếu, bắt quân hay phản công.");
    }
    if (components.responsePrediction === 1) strengths.push(`Bạn đã dự đoán đúng phản ứng mạnh nhất của đối thủ (${norm(sa.predicted_opponent_reply)}).`);
    if (components.variationCalculation === 1) strengths.push("Biến bạn tính khớp với biến chính của engine ở các nước đầu tiên.");
    if (components.positionEvaluation === 1 && sa.position_assessment) {
      strengths.push(`Bạn đánh giá đúng thế cờ sau nước đi là "${POSITION_LABEL[sa.position_assessment]}" (engine ${a}).`);
    }
    if (components.pieceSafety === 1) {
      strengths.push(engine.material_at_risk ? "Bạn đã nhận ra quân của mình có thể bị bắt." : "Nước đi không để quân nào của bạn bị treo.");
    }
  }

  // Stable sort keeps the listed order for equal weights.
  const top = [...issues].sort((a, b) => b.weight - a.weight).slice(0, 3);
  for (const i of top) if (!learning_notes.includes(i.note)) learning_notes.push(i.note);

  const weakest = [...COMPONENTS]
    .filter((c) => components[c] !== 1)
    .sort((a, b) => (components[a] ?? 0) - (components[b] ?? 0) || THINKING_WEIGHTS[b] - THINKING_WEIGHTS[a])
    .slice(0, 3);
  const guiding_questions = weakest.length ? weakest.map((c) => QUESTIONS[c]) : ["Nếu đối thủ đáp trả mạnh nhất, kế hoạch tiếp theo của bạn là gì?"];

  // Topic = answered component that lost the most weighted points.
  const answered = COMPONENTS.filter((c) => components[c] !== null);
  const lost = (c: ThinkingComponent) => THINKING_WEIGHTS[c] * (1 - (components[c] ?? 0));
  const topic = answered.reduce<ThinkingComponent | null>((best, c) => (best === null || lost(c) > lost(best) ? c : best), null);
  const next_training_topic = !engine
    ? "Chưa có dữ liệu engine cho nước này nên chưa đề xuất chủ đề luyện tập"
    : topic === null
      ? "Hoàn thành phần tự đánh giá để nhận chủ đề luyện tập"
      : lost(topic) === 0
        ? "Duy trì: tiếp tục tự đánh giá đầy đủ ở các nước khó hơn"
        : TRAINING_TOPICS[topic];

  return {
    session_id: sessionId,
    move_number: played.move_number,
    board_before: played.board_before,
    board_after: played.board_after,
    player_move: played.player_move,
    player_intention: sa.intention,
    predicted_opponent_reply: sa.predicted_opponent_reply,
    predicted_variations: sa.predicted_variations,
    engine_evaluation_before: engine?.eval_before_cp ?? null,
    engine_evaluation_after: engine?.eval_after_cp ?? null,
    move_quality_score: quality.score,
    thinking_quality_score: thinkingScore(components),
    strengths,
    missed_threats: top.map((i) => i.text),
    learning_notes,
    next_training_topic,
    confidence: !engine || engine.source === "sample" || answered.length < 3 ? "low" : answered.length === 5 && engine.source === "pikafish" ? "high" : "medium",
    created_at: now.toISOString(),
    move_quality_label: quality.label,
    thinking_components: components,
    guiding_questions,
    engine,
    self_assessment: sa,
  };
}

/**
 * Strengths / weaknesses of the move itself, from verified engine data only (works without a self-assessment).
 * Every move named comes from the engine or the player.
 */
export function movePoints(e: EngineAnalysis, playerMove: string): { pros: string[]; cons: string[] } {
  const pros: string[] = [];
  const cons: string[] = [];
  const loss = Math.max(0, e.cp_loss ?? e.eval_before_cp - e.eval_after_cp);
  const change = mateChange(e);
  if (change) (change.decisive || e.eval_after_cp < 0 ? cons : pros).push(`Nước đi ${change.text}.`);
  if (norm(playerMove) === norm(e.best_move)) pros.push("Trùng với nước tốt nhất của engine.");
  else if (loss <= 20) pros.push(`Gần ngang nước tốt nhất của engine (${e.best_move}).`);
  else if (!change?.decisive) cons.push(`Kém nước tốt nhất ${e.best_move} khoảng ${loss} điểm.`);
  if (e.threats.check) cons.push("Sau nước này đối thủ có nước chiếu.");
  if (e.material_at_risk) cons.push("Có quân của bạn có thể bị bắt mất.");
  if (e.threats.counterattack) cons.push("Đối thủ có cơ hội phản công.");
  if (!e.threats.check && !e.threats.capture && !e.threats.counterattack) pros.push("Không để lại nguy cơ bị chiếu, bị bắt quân hay bị phản công.");
  return { pros, cons };
}
