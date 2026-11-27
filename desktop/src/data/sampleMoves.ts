// Hand-written SAMPLE values, NOT Pikafish output: evals, best moves and threats are illustrative only.
// ponytail: replace with real moves (GĐ3) and Pikafish analysis (GĐ4) when those phases land.
import type { PlayedMove } from "../types/moveReview";

const START = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";
// After 1. h2e2 (pháo đầu) h9g7 (mã 8 tiến 7).
const AFTER_1 = "rnbakab1r/9/1c4nc1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR w - - 2 2";
const noThreats = { check: false, capture: false, counterattack: false };

export const SAMPLE_MOVES: PlayedMove[] = [
  {
    // Good: central cannon.
    move_number: 1,
    board_before: START,
    board_after: "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR b - - 1 1",
    player_move: "h2e2",
    engine: {
      source: "sample",
      eval_before_cp: 20,
      eval_after_cp: 25,
      best_move: "h2e2",
      opponent_best_replies: ["h9g7", "b9c7", "h7e7"],
      principal_variation: ["h9g7", "h0g2", "i9h9", "i0h0"],
      threats: noThreats,
      material_at_risk: false,
    },
  },
  {
    // Blunder: cannon takes the centre pawn, the g7 horse takes the cannon back.
    move_number: 2,
    board_before: AFTER_1,
    board_after: "rnbakab1r/9/1c4nc1/p1p1C1p1p/9/9/P1P1P1P1P/1C7/9/RNBAKABNR b - - 0 2",
    player_move: "e2e6",
    engine: {
      source: "sample",
      eval_before_cp: 30,
      eval_after_cp: -320,
      best_move: "h0g2",
      opponent_best_replies: ["g7e6", "i9h9"],
      principal_variation: ["g7e6", "h0g2", "i9h9"],
      threats: { check: false, capture: true, counterattack: false },
      material_at_risk: true,
    },
  },
  {
    // No engine data yet.
    move_number: 2,
    board_before: AFTER_1,
    board_after: "rnbakab1r/9/1c4nc1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C1N2/9/RNBAKAB1R b - - 3 2",
    player_move: "h0g2",
    engine: null,
  },
];
