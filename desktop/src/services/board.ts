// Pure board helpers. Placement = board[rank][file], rank 0 = Red back rank (same as the backend).
import type { Placement, Square } from "../types/api";

export const FILES = "abcdefghi";
export const START_PLACEMENT = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR";
export const START_FEN = `${START_PLACEMENT} w - - 0 1`;

/** Vietnamese short name + Chinese character. Uppercase = Red. */
export const PIECES: Record<string, { vi: string; zh: string }> = {
  K: { vi: "Tướng", zh: "帥" }, A: { vi: "Sĩ", zh: "仕" }, B: { vi: "Tượng", zh: "相" }, N: { vi: "Mã", zh: "傌" },
  R: { vi: "Xe", zh: "俥" }, C: { vi: "Pháo", zh: "炮" }, P: { vi: "Tốt", zh: "兵" },
  k: { vi: "Tướng", zh: "將" }, a: { vi: "Sĩ", zh: "士" }, b: { vi: "Tượng", zh: "象" }, n: { vi: "Mã", zh: "馬" },
  r: { vi: "Xe", zh: "車" }, c: { vi: "Pháo", zh: "砲" }, p: { vi: "Tốt", zh: "卒" },
};

export const squareName = (rank: number, file: number) => `${FILES[file]}${rank}`;

/** Accepts a FEN board field or a full FEN. Throws on a malformed placement. */
export function parsePlacement(fen: string): Placement {
  const rows = fen.trim().split(/\s+/)[0].split("/");
  if (rows.length !== 10) throw new Error(`Thế cờ phải có 10 hàng, nhận được ${rows.length}.`);
  return rows.reverse().map((row) => {
    const squares: Square[] = [];
    for (const ch of row) {
      if (/\d/.test(ch)) squares.push(...Array<Square>(Number(ch)).fill(null));
      else if (PIECES[ch]) squares.push(ch);
      else throw new Error(`Ký hiệu quân không hợp lệ: ${ch}`);
    }
    if (squares.length !== 9) throw new Error(`Hàng "${row}" không đủ 9 cột.`);
    return squares;
  });
}

export function toFenPlacement(board: Placement): string {
  return [...board]
    .reverse()
    .map((row) => row.map((sq) => sq ?? "1").join("").replace(/1+/g, (m) => String(m.length)))
    .join("/");
}

export function setSquare(board: Placement, rank: number, file: number, piece: Square): Placement {
  return board.map((row, r) => (r === rank ? row.map((sq, f) => (f === file ? piece : sq)) : row));
}
