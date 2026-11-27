import { describe, expect, it } from "vitest";
import { SAMPLE_MOVES } from "../data/sampleMoves";
import type { EngineAnalysis, PlayedMove, SelfAssessment } from "../types/moveReview";
import type { MoveEvaluation } from "../types/api";
import { buildMoveReview, evalText, fromEvaluation, mateChange, moveQuality, thinkingComponents, thinkingScore } from "./moveReview";

const engine = (over: Partial<EngineAnalysis> = {}): EngineAnalysis => ({
  source: "pikafish",
  eval_before_cp: 30,
  eval_after_cp: 30,
  best_move: "h2e2",
  opponent_best_replies: ["h9g7", "b9c7"],
  principal_variation: ["h9g7", "h0g2", "i9h9", "i0h0", "b9c7"],
  threats: { check: false, capture: true, counterattack: false },
  material_at_risk: true,
  ...over,
});

const blank: SelfAssessment = {
  intention: "",
  predicted_opponent_reply: "",
  predicted_variations: [],
  depth: null,
  recognized_risks: null,
  position_assessment: null,
  skipped: false,
};
const sa = (over: Partial<SelfAssessment> = {}): SelfAssessment => ({ ...blank, ...over });
const full = sa({
  predicted_opponent_reply: "h9g7",
  predicted_variations: ["h9g7 h0g2 i9h9 i0h0"],
  depth: 4,
  recognized_risks: { check: false, capture: true, counterattack: false },
  position_assessment: "equal",
});
const played = (e: EngineAnalysis | null, move = "h2e2"): PlayedMove => ({ move_number: 1, board_before: "a", board_after: "b", player_move: move, engine: e });

describe("moveQuality", () => {
  it("returns null without engine data", () => {
    expect(moveQuality(null)).toEqual({ score: null, label: "Chưa đủ dữ liệu đánh giá" });
  });

  it.each([
    [0, 100, "Rất tốt"],
    [20, 100, "Rất tốt"],
    [50, 89, "Tốt"],
    [100, 71, "Thiếu chính xác"],
    [200, 36, "Sai lầm"],
    [300, 0, "Sai lầm nghiêm trọng"],
    [500, 0, "Sai lầm nghiêm trọng"],
  ])("loss %i → %i %s", (loss, score, label) => {
    expect(moveQuality(engine({ eval_before_cp: 50, eval_after_cp: 50 - loss }))).toEqual({ score, label });
  });

  it("treats an eval gain as zero loss", () => {
    expect(moveQuality(engine({ eval_before_cp: 0, eval_after_cp: 80 })).score).toBe(100);
  });
});

describe("thinkingComponents", () => {
  it("scores every component when all questions are answered", () => {
    expect(thinkingComponents(full, engine())).toEqual({
      threatAwareness: 1,
      responsePrediction: 1,
      variationCalculation: 1,
      positionEvaluation: 1,
      pieceSafety: 1,
    });
    expect(thinkingScore(thinkingComponents(full, engine()))).toBe(100);
  });

  it("is all null without engine or when skipped", () => {
    expect(Object.values(thinkingComponents(full, null)).every((v) => v === null)).toBe(true);
    expect(Object.values(thinkingComponents({ ...full, skipped: true }, engine())).every((v) => v === null)).toBe(true);
  });

  it("threatAwareness counts matching categories", () => {
    const c = thinkingComponents(sa({ recognized_risks: { check: true, capture: false, counterattack: false } }), engine());
    expect(c.threatAwareness).toBeCloseTo(1 / 3);
    expect(thinkingComponents(blank, engine()).threatAwareness).toBeNull();
  });

  it("responsePrediction: best 1, other MultiPV 0.5, else 0, unanswered null", () => {
    const rp = (r: string) => thinkingComponents(sa({ predicted_opponent_reply: r }), engine()).responsePrediction;
    expect(rp(" H9G7 ")).toBe(1);
    expect(rp("b9c7")).toBe(0.5);
    expect(rp("a9a8")).toBe(0);
    expect(rp("  ")).toBeNull();
  });

  it("variationCalculation uses the longest matching prefix, capped at 4", () => {
    const vc = (v: string[], pv?: string[]) =>
      thinkingComponents(sa({ predicted_variations: v }), engine(pv ? { principal_variation: pv } : {})).variationCalculation;
    expect(vc(["h9g7 h0g2 a9a8", "b9c7"])).toBe(0.5);
    expect(vc(["h9g7 h0g2 i9h9 i0h0 a9a8"])).toBe(1);
    expect(vc(["h9g7"], ["h9g7", "h0g2"])).toBe(0.5);
    expect(vc(["", " "])).toBeNull();
    expect(vc(["h9g7"], [])).toBeNull();
  });

  it("positionEvaluation: exact 1, one step 0.5, opposite 0", () => {
    const pe = (p: SelfAssessment["position_assessment"], after: number) =>
      thinkingComponents(sa({ position_assessment: p }), engine({ eval_after_cp: after })).positionEvaluation;
    expect(pe("better", 120)).toBe(1);
    expect(pe("equal", 120)).toBe(0.5);
    expect(pe("worse", 120)).toBe(0);
    expect(pe("equal", -50)).toBe(1);
    expect(pe(null, 0)).toBeNull();
  });

  it("pieceSafety depends on flagging capture when material is at risk", () => {
    const ps = (capture: boolean, atRisk: boolean) =>
      thinkingComponents(sa({ recognized_risks: { check: false, capture, counterattack: false } }), engine({ material_at_risk: atRisk })).pieceSafety;
    expect(ps(true, true)).toBe(1);
    expect(ps(false, true)).toBe(0);
    expect(ps(false, false)).toBe(1);
    expect(thinkingComponents(blank, engine()).pieceSafety).toBeNull();
  });
});

describe("buildMoveReview", () => {
  it("does not infer good thinking from a good move when the assessment is skipped", () => {
    const r = buildMoveReview("s", played(engine({ eval_after_cp: 30 }), "h2e2"), { ...blank, skipped: true });
    expect(r.move_quality_score).toBe(100);
    expect(r.thinking_quality_score).toBeNull();
    expect(r.strengths).toEqual([]);
    expect(r.next_training_topic).toBe("Hoàn thành phần tự đánh giá để nhận chủ đề luyện tập");
    expect(r.confidence).toBe("low");
  });

  it("partial answers: total null, answered components still scored", () => {
    const r = buildMoveReview("s", played(engine()), sa({ predicted_opponent_reply: "h9g7", position_assessment: "worse" }));
    expect(r.thinking_quality_score).toBeNull();
    expect(r.thinking_components.responsePrediction).toBe(1);
    expect(r.thinking_components.positionEvaluation).toBe(0.5);
    expect(r.strengths).toContain("Bạn đã dự đoán đúng phản ứng mạnh nhất của đối thủ (h9g7).");
    expect(r.next_training_topic).toMatch(/Đánh giá thế cờ/);
  });

  it("keeps at most 3 missed threats, most important first, without revealing engine moves", () => {
    const r = buildMoveReview(
      "s",
      played(engine({ threats: { check: true, capture: true, counterattack: true }, eval_after_cp: -300 })),
      sa({
        predicted_opponent_reply: "a9a8",
        predicted_variations: ["a9a8"],
        depth: 5,
        recognized_risks: { check: false, capture: false, counterattack: false },
        position_assessment: "better",
      }),
    );
    expect(r.missed_threats).toHaveLength(3);
    expect(r.missed_threats[0]).toMatch(/bị bắt quân/);
    expect(r.missed_threats[1]).toBe("Bạn dự đoán a9a8, nhưng đó chưa phải phản ứng mạnh nhất của đối thủ.");
    expect(r.missed_threats.join(" ").match(/[a-i]\d[a-i]\d/g)).toEqual(["a9a8"]); // only the player's own input
    expect(r.learning_notes[0]).toBe("Thế cờ thay đổi từ +30 xuống -300 (mất 330 điểm).");
    expect(r.guiding_questions.length).toBeGreaterThanOrEqual(1);
    expect(r.guiding_questions.length).toBeLessThanOrEqual(3);
  });

  it("ignores a leading player move in the variation", () => {
    const c = thinkingComponents(sa({ predicted_variations: ["h2e2 h9g7 h0g2 i9h9 i0h0"] }), engine(), "h2e2");
    expect(c.variationCalculation).toBe(1);
    const r = buildMoveReview("s", played(engine()), sa({ predicted_variations: ["H2E2 h9g7 h0g2"], depth: 2 }));
    expect(r.missed_threats).toEqual([]);
  });

  it("does not repeat learning notes for several overestimated risks", () => {
    const r = buildMoveReview(
      "s",
      played(engine({ threats: { check: false, capture: false, counterattack: false }, material_at_risk: false })),
      sa({ recognized_risks: { check: true, capture: true, counterattack: true } }),
    );
    expect(r.missed_threats).toHaveLength(3);
    expect(new Set(r.learning_notes).size).toBe(r.learning_notes.length);
    expect(r.learning_notes).toHaveLength(4);
  });

  it("gives a neutral topic when every answered component is perfect", () => {
    expect(buildMoveReview("s", played(engine()), full).next_training_topic).toBe("Duy trì: tiếp tục tự đánh giá đầy đủ ở các nước khó hơn");
  });

  it("reports overclaimed depth against the matched prefix", () => {
    const r = buildMoveReview("s", played(engine()), sa({ predicted_variations: ["h9g7 h0g2 a9a8"], depth: 6 }));
    expect(r.missed_threats).toContain("Bạn nói đã tính 6 nước nhưng biến của bạn chỉ khớp với engine 2 nước.");
  });

  it("only mentions moves from engine data or player input", () => {
    const answers = [blank, full, { ...blank, skipped: true }, sa({ predicted_opponent_reply: "c6c5", predicted_variations: ["c6c5 c3c4"], depth: 3 })];
    for (const move of SAMPLE_MOVES) {
      for (const a of answers) {
        const r = buildMoveReview("s", move, a);
        const allowed = new Set([
          move.player_move,
          a.predicted_opponent_reply,
          ...a.predicted_variations.flatMap((v) => v.split(/\s+/)),
          ...(move.engine ? [move.engine.best_move, ...move.engine.opponent_best_replies, ...move.engine.principal_variation] : []),
        ]);
        const text = [...r.strengths, ...r.missed_threats, ...r.learning_notes, ...r.guiding_questions].join(" ");
        for (const m of text.match(/[a-i]\d[a-i]\d/g) ?? []) expect(allowed).toContain(m);
      }
    }
  });

  it("without engine: null quality and an explicit note", () => {
    const r = buildMoveReview("s", played(null), full);
    expect(r.move_quality_score).toBeNull();
    expect(r.engine_evaluation_before).toBeNull();
    expect(r.learning_notes).toContain("Chưa có dữ liệu engine đã xác thực cho nước này.");
    expect(r.next_training_topic).toMatch(/Chưa có dữ liệu engine/);
    expect(r.confidence).toBe("low");
  });

  it("confidence: sample → low, pikafish with 5 answers → high, 3–4 answers → medium, <3 → low", () => {
    expect(buildMoveReview("s", played(engine({ source: "sample" })), full).confidence).toBe("low");
    expect(buildMoveReview("s", played(engine()), full).confidence).toBe("high");
    expect(buildMoveReview("s", played(engine()), { ...full, predicted_variations: [] }).confidence).toBe("medium");
    expect(buildMoveReview("s", played(engine()), sa({ predicted_opponent_reply: "h9g7", position_assessment: "equal" })).confidence).toBe("low");
  });

  it("fills the snake_case record", () => {
    const now = new Date("2026-01-01T00:00:00Z");
    const r = buildMoveReview("sess", SAMPLE_MOVES[1], full, now);
    expect(r).toMatchObject({
      session_id: "sess",
      move_number: 2,
      player_move: "e2e6",
      engine_evaluation_before: 30,
      engine_evaluation_after: -320,
      move_quality_score: 0,
      created_at: "2026-01-01T00:00:00.000Z",
    });
  });
});

describe("engine evaluation mapping and mate handling", () => {
  const ev: MoveEvaluation = {
    ...engine(),
    source: "pikafish",
    eval_before_cp: 29995, // mate in 5 mapped by the backend
    eval_after_cp: 150,
    move: "h2e2",
    fen_after: "x",
    eval_before_mate: 5,
    eval_after_mate: null,
    cp_loss: 2000, // clamped by the backend, not 29845
    depth: 12,
    depth_requested: 12,
    stable: true,
    notes: [],
  };

  it("keeps only EngineAnalysis fields plus cp_loss and mate", () => {
    const e = fromEvaluation(ev);
    expect(e).toMatchObject({ source: "pikafish", cp_loss: 2000, eval_before_mate: 5, eval_after_mate: null, best_move: "h2e2" });
    expect(e).not.toHaveProperty("fen_after");
    expect(e).not.toHaveProperty("depth");
  });

  it("moveQuality prefers backend cp_loss over raw subtraction", () => {
    expect(moveQuality(engine({ eval_before_cp: 50, eval_after_cp: -500, cp_loss: 40 })).score).toBe(100 - 7);
    expect(moveQuality(fromEvaluation(ev))).toEqual({ score: 0, label: "Sai lầm nghiêm trọng — bỏ lỡ đường chiếu hết" });
  });

  it("still winning by mate after the move is not a loss", () => {
    const e = fromEvaluation({ ...ev, eval_after_cp: 29996, eval_after_mate: 4, cp_loss: 0 });
    expect(moveQuality(e)).toEqual({ score: 100, label: "Rất tốt" });
  });

  it("walking into a mate is flagged", () => {
    const e = fromEvaluation({ ...ev, eval_before_cp: 20, eval_before_mate: null, eval_after_cp: -29997, eval_after_mate: -3, cp_loss: 2020 });
    expect(moveQuality(e).label).toBe("Sai lầm nghiêm trọng — đối thủ có đường chiếu hết");
  });

  it("evalText uses chiếu hết wording for mates", () => {
    expect(evalText(35)).toBe("+35");
    expect(evalText(null)).toBe("—");
    expect(evalText(29995, 5)).toBe("chiếu hết sau 5 nước");
    expect(evalText(-29997, -3)).toBe("bị chiếu hết sau 3 nước");
    expect(evalText(30000, 0)).toBe("đã chiếu hết");
  });

  it("review notes never print mapped mate scores as centipawns", () => {
    const r = buildMoveReview("s", played(fromEvaluation(ev)), full);
    expect(r.learning_notes[0]).toBe("Thế cờ thay đổi từ chiếu hết sau 5 nước xuống +150 (mất lợi thế quyết định: bỏ lỡ đường chiếu hết).");
    expect(r.learning_notes.join(" ")).not.toMatch(/2999/);
    expect(r.missed_threats.join(" ")).not.toMatch(/2999/);
  });
});

describe("mateChange", () => {
  const e = (before: [number, number | null], after: [number, number | null], cp_loss?: number) =>
    engine({ eval_before_cp: before[0], eval_before_mate: before[1], eval_after_cp: after[0], eval_after_mate: after[1], cp_loss });

  it("only a lost winning mate or walking into a mate is decisive", () => {
    expect(mateChange(e([29995, 5], [150, null]))).toEqual({ text: "bỏ lỡ đường chiếu hết", decisive: true });
    expect(mateChange(e([20, null], [-29997, -3]))).toEqual({ text: "đối thủ có đường chiếu hết", decisive: true });
    expect(mateChange(e([29997, 3], [29996, 4]))?.decisive).toBe(false);
    expect(mateChange(e([-29997, -3], [-29998, -2]))).toEqual({ text: "vẫn đang bị đối thủ chiếu hết", decisive: false });
    expect(mateChange(e([-29997, -3], [-50, null]))?.text).toBe("thoát khỏi đường chiếu hết của đối thủ");
    expect(mateChange(e([40, null], [29996, 4]))?.text).toBe("tạo ra đường chiếu hết");
    expect(mateChange(e([40, null], [20, null]))).toBeNull();
  });

  it("mate in 3 → mate in 4 is not reported as a decisive loss, even without backend cp_loss", () => {
    const r = buildMoveReview("s", played(e([29997, 3], [29996, 4])), full);
    expect(r.learning_notes[0]).toBe("Thế cờ thay đổi từ chiếu hết sau 3 nước xuống chiếu hết sau 4 nước (vẫn giữ được đường chiếu hết).");
    expect(moveQuality(e([29997, 3], [29996, 4], 0))).toEqual({ score: 100, label: "Rất tốt" });
  });

  it("already being mated is not labelled as walking into a mate", () => {
    const r = buildMoveReview("s", played(e([-29997, -3], [-29998, -2], 0)), full);
    expect(r.learning_notes[0]).toBe("Thế cờ thay đổi từ bị chiếu hết sau 3 nước thành bị chiếu hết sau 2 nước (vẫn đang bị đối thủ chiếu hết).");
    expect(moveQuality(e([-29997, -3], [-29998, -2], 0)).label).toBe("Rất tốt");
  });
});
