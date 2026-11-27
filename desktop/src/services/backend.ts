// Client for the local FastAPI backend. Every call goes to 127.0.0.1 only; nothing leaves the machine.
import type {
  AttemptResult,
  Backup,
  BoardResult,
  CalibrateResult,
  CoachResponse,
  CoachStatus,
  EngineStatus,
  Exercise,
  GenerateResult,
  Health,
  MistakePage,
  MoveEvaluation,
  MoveOut,
  Patterns,
  Placement,
  PositionResult,
  SessionDetail,
  StatsSummary,
  StoredReview,
} from "../types/api";
import type { MoveReview } from "../types/moveReview";

export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8765";
export const TIMEOUT_MS = 15_000;
// Engine search and LLM calls can legitimately take longer than a plain request.
const SLOW_MS = 90_000;

export class BackendError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = "BackendError";
  }
}

const OFFLINE = `Backend chưa chạy hoặc không kết nối được (${BACKEND_URL}). Hãy khởi động backend rồi thử lại.`;

/** FastAPI puts the message in `detail` (string, or a list of validation errors). */
function detailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : "")).filter(Boolean);
    return msgs.length ? `Dữ liệu không hợp lệ: ${msgs.join("; ")}` : null;
  }
  return null;
}

function statusText(status: number): string {
  if (status === 403) return "Backend từ chối yêu cầu (403).";
  if (status === 404) return "Không tìm thấy dữ liệu trên backend (404).";
  if (status === 413) return "Dữ liệu gửi lên quá lớn (413). Hãy chia sẻ cửa sổ nhỏ hơn hoặc chỉ cửa sổ bàn cờ.";
  if (status === 503) return "Dịch vụ backend tạm thời không sẵn sàng (503).";
  if (status >= 500) return `Lỗi backend (${status}). Xem log của backend.`;
  return `Yêu cầu không hợp lệ (${status}).`;
}

export class Cancelled extends Error {
  name = "Cancelled";
}

/** signal: caller-side cancel (e.g. component unmount); rejects with Cancelled, never with an error message. */
type Options = { method?: string; json?: unknown; png?: Blob; timeoutMs?: number; raw?: boolean; signal?: AbortSignal };

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.json !== undefined || opts.png ? "POST" : "GET");
  const headers: Record<string, string> = {};
  // Required by the backend on every mutation (blocks cross-site form posts).
  if (method !== "GET") headers["X-XQC-Client"] = "1";
  let body: BodyInit | undefined;
  if (opts.png) {
    // Vision endpoints take the raw PNG bytes as the body (no multipart).
    headers["Content-Type"] = "image/png";
    body = opts.png;
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }

  if (opts.signal?.aborted) throw new Cancelled();
  const ctrl = new AbortController();
  const timeout = opts.timeoutMs ?? TIMEOUT_MS;
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const cancel = () => ctrl.abort();
  opts.signal?.addEventListener("abort", cancel);
  let res: Response;
  try {
    res = await fetch(BACKEND_URL + path, { method, headers, body, signal: ctrl.signal });
  } catch {
    if (opts.signal?.aborted) throw new Cancelled();
    if (ctrl.signal.aborted) throw new BackendError(`Backend không phản hồi sau ${Math.round(timeout / 1000)} giây.`, null);
    throw new BackendError(OFFLINE, null);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", cancel);
  }

  if (!res.ok) {
    let detail: string | null = null;
    try {
      detail = detailText((await res.json())?.detail);
    } catch {
      // non-JSON error body
    }
    throw new BackendError(detail ?? statusText(res.status), res.status);
  }
  return (opts.raw ? res.blob() : res.json()) as Promise<T>;
}

/**
 * Retries while the backend is unreachable (status null: offline or timed out), e.g. while the sidecar is still
 * starting. HTTP errors and Cancelled are thrown at once.
 */
export async function retryWhileOffline<T>(fn: () => Promise<T>, signal?: AbortSignal, tries = 20, delayMs = 3000): Promise<T> {
  for (let i = 1; ; i++) {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof BackendError) || e.status !== null || i >= tries || signal?.aborted) throw e;
    }
    await new Promise((r) => setTimeout(r, delayMs));
    if (signal?.aborted) throw new Cancelled();
  }
}

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const api = {
  health: () => request<Health>("/health", { timeoutMs: 5000 }),
  engineStatus: () => request<EngineStatus>("/engine/status", { timeoutMs: 5000 }),
  coachStatus: () => request<CoachStatus>("/coach/status", { timeoutMs: 5000 }),

  calibrate: (png: Blob) => request<CalibrateResult>("/vision/calibrate", { png }),
  readBoard: (png: Blob, signal?: AbortSignal) => request<BoardResult>("/vision/board", { png, signal }),

  createSession: (start_fen?: string) => request<SessionDetail>("/sessions", { json: { start_fen: start_fen || null } }),
  getSession: (id: string) => request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),
  submitPosition: (id: string, pos: { fen_placement: string } | { placement: Placement }, signal?: AbortSignal) =>
    request<PositionResult>(`/sessions/${encodeURIComponent(id)}/positions`, { json: pos, signal }),
  addMove: (id: string, uci: string) => request<MoveOut>(`/sessions/${encodeURIComponent(id)}/moves`, { json: { uci } }),
  undoMove: (id: string) => request<MoveOut>(`/sessions/${encodeURIComponent(id)}/moves/last`, { method: "DELETE" }),
  endSession: (id: string) => request<SessionDetail>(`/sessions/${encodeURIComponent(id)}/end`, { method: "POST" }),

  evaluateMove: (fen_before: string, move: string) =>
    request<MoveEvaluation>("/engine/evaluate-move", { json: { fen_before, move }, timeoutMs: SLOW_MS }),
  saveReview: (id: string, review: MoveReview) => request<StoredReview>(`/sessions/${encodeURIComponent(id)}/reviews`, { json: review }),
  listReviews: (id: string) => request<StoredReview[]>(`/sessions/${encodeURIComponent(id)}/reviews`),
  // MoveReview carries every CoachRequest field; extra keys are ignored by the backend.
  coachFeedback: (review: MoveReview, reveal_engine: boolean) =>
    request<CoachResponse>("/coach/move-feedback", {
      // the coach accepts at most 5 variations
      json: { ...review, self_assessment: { ...review.self_assessment, predicted_variations: review.self_assessment.predicted_variations.slice(0, 5) }, reveal_engine },
      timeoutMs: SLOW_MS,
    }),

  patterns: () => request<Patterns>("/journal/patterns"),
  mistakes: (limit = 50) => request<MistakePage>(`/journal/mistakes?limit=${limit}`),
  stats: () => request<StatsSummary>("/stats/summary"),

  generateExercises: (limit = 5) => request<GenerateResult>("/training/generate", { json: { limit }, timeoutMs: SLOW_MS }),
  exercises: () => request<Exercise[]>("/training/exercises"),
  attempt: (id: number, answer: string) => request<AttemptResult>(`/training/exercises/${id}/attempt`, { json: { answer } }),

  exportData: () => request<Blob>("/data/export", { raw: true }),
  backup: () => request<Backup>("/data/backup", { method: "POST" }),
};
