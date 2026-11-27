// Auto-tracking decision, kept pure so it can be tested without a screen or a backend.
import type { BoardResult } from "../types/api";

export const STABLE_FRAMES = 2;

/** last = placement seen in the previous frame(s), count = how many frames in a row, submitted = last one sent. */
export type Stability = { last: string | null; count: number; submitted: string | null };
export const INITIAL_STABILITY: Stability = { last: null, count: 0, submitted: null };

/**
 * A frame counts only when recognition is complete (no uncertain square, fen_placement present). A placement is
 * submitted once it was identical for STABLE_FRAMES frames in a row and differs from the last submitted one
 * (pieces mid-animation or a hover effect never reach the backend).
 */
export function observeFrame(s: Stability, r: BoardResult): { state: Stability; submit: string | null } {
  const fen = r.low_confidence.length === 0 ? r.fen_placement : null;
  if (!fen) return { state: { ...s, last: null, count: 0 }, submit: null };
  const count = fen === s.last ? s.count + 1 : 1;
  if (count >= STABLE_FRAMES && fen !== s.submitted) return { state: { last: fen, count, submitted: fen }, submit: fen };
  return { state: { ...s, last: fen, count }, submit: null };
}
