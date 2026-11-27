import { describe, expect, it } from "vitest";
import type { BoardResult } from "../types/api";
import { INITIAL_STABILITY, observeFrame, type Stability } from "./autoMonitor";
import { START_FEN, START_PLACEMENT, parsePlacement, setSquare, squareName, toFenPlacement } from "./board";

describe("board helpers", () => {
  it("parses rank 0 as the Red back rank and round-trips", () => {
    const b = parsePlacement(START_FEN);
    expect(b).toHaveLength(10);
    expect(b[0].join("")).toBe("RNBAKABNR");
    expect(b[9][4]).toBe("k");
    expect(b[2][1]).toBe("C");
    expect(b[5].every((s) => s === null)).toBe(true);
    expect(toFenPlacement(b)).toBe(START_PLACEMENT);
  });

  it("rejects malformed placements", () => {
    expect(() => parsePlacement("9/9")).toThrow(/10 hàng/);
    expect(() => parsePlacement(START_PLACEMENT.replace("RNBAKABNR", "RNBAKABN"))).toThrow(/9 cột/);
    expect(() => parsePlacement(START_PLACEMENT.replace("RNBAKABNR", "RNBAKABNX"))).toThrow(/không hợp lệ/);
  });

  it("setSquare edits one square without mutating the input", () => {
    const b = parsePlacement(START_PLACEMENT);
    const moved = setSquare(setSquare(b, 2, 7, null), 2, 4, "C"); // h2e2
    expect(toFenPlacement(moved)).toBe("rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR");
    expect(toFenPlacement(b)).toBe(START_PLACEMENT);
    expect(moved[0]).toBe(b[0]); // untouched ranks are shared
  });

  it("names squares file letter + rank", () => {
    expect(squareName(0, 0)).toBe("a0");
    expect(squareName(9, 8)).toBe("i9");
  });
});

const frame = (fen: string | null, low: string[] = []): BoardResult => ({
  board: [], confidence: [], orientation: "red_bottom", fen_placement: fen, low_confidence: low, problems: [],
  grid: { x: 0, y: 0, width: 1, height: 1, cell: 1 }, timing_ms: 1,
});

function run(frames: BoardResult[], s: Stability = INITIAL_STABILITY) {
  const sent: string[] = [];
  for (const f of frames) {
    const r = observeFrame(s, f);
    s = r.state;
    if (r.submit) sent.push(r.submit);
  }
  return { sent, s };
}

describe("observeFrame", () => {
  it("submits after 2 identical complete frames, once", () => {
    expect(run([frame("A"), frame("A"), frame("A"), frame("A")]).sent).toEqual(["A"]);
  });

  it("ignores incomplete frames and resets the streak", () => {
    expect(run([frame("A"), frame(null), frame("A")]).sent).toEqual([]);
    expect(run([frame("A"), frame("A", ["e0"]), frame("A")]).sent).toEqual([]);
  });

  it("needs the same placement twice in a row", () => {
    expect(run([frame("A"), frame("B"), frame("A"), frame("B")]).sent).toEqual([]);
    expect(run([frame("A"), frame("A"), frame("B"), frame("B"), frame("A"), frame("A")]).sent).toEqual(["A", "B", "A"]);
  });

  it("can resubmit after the caller clears submitted (failed request)", () => {
    const { s } = run([frame("A"), frame("A")]);
    expect(run([frame("A")], { ...s, submitted: null }).sent).toEqual(["A"]);
  });
});
