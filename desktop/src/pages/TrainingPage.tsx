import { useState, type FormEvent } from "react";
import { BoardEditor } from "../components/BoardEditor";
import { Card, ErrorText } from "../components/Card";
import { useLoad } from "../hooks/useLoad";
import { api, errorText } from "../services/backend";
import { parsePlacement } from "../services/board";
import type { AttemptResult, Exercise, GenerateResult } from "../types/api";

const btn = "rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";
const EVALS = [
  { value: "better", label: "Tốt hơn" },
  { value: "equal", label: "Cân bằng" },
  { value: "worse", label: "Kém hơn" },
];
const SIDE = { w: "Đỏ", b: "Đen" } as const;

export function TrainingPage() {
  const list = useLoad(api.exercises);
  const [gen, setGen] = useState<GenerateResult | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = list.data?.find((e) => e.id === selectedId) ?? null;

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setGen(await api.generateExercises(5));
      await list.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Luyện tập</h1>
          <p className="text-sm text-slate-400">Bài tập lấy từ chính thế cờ bạn đã đi sai; đáp án do Pikafish tính, không bịa.</p>
        </div>
        <button onClick={generate} disabled={busy} className={`${btn} bg-emerald-600 hover:bg-emerald-500`}>
          {busy ? "Đang tạo bài tập…" : "Tạo bài tập từ lỗi của tôi"}
        </button>
      </header>
      <ErrorText error={error ?? list.error} />
      {gen && (
        <p className="text-sm text-slate-300">
          Đã tạo {gen.created.length} bài tập{gen.skipped.length ? `, bỏ qua ${gen.skipped.length}` : ""}. {gen.reason}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card title="Bài tập">
          {list.data?.length ? (
            <ul className="space-y-1">
              {list.data.map((e) => (
                <li key={e.id}>
                  <button
                    onClick={() => setSelectedId(e.id)}
                    aria-current={e.id === selectedId ? "true" : undefined}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm ${e.id === selectedId ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800"}`}
                  >
                    {e.component_label}
                    <span className="block text-xs text-slate-500">{e.status === "done" ? (e.attempts.some((a) => a.correct) ? "Đã giải đúng" : "Đã làm") : "Chưa làm"}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">{list.loading ? "Đang tải…" : "Chưa có bài tập. Đánh giá vài nước đi rồi bấm tạo bài tập."}</p>
          )}
        </Card>
        {selected ? (
          <ExerciseView key={selected.id} ex={selected} onDone={list.reload} />
        ) : (
          <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-slate-700 text-sm text-slate-500">Chọn một bài tập.</div>
        )}
      </div>
    </div>
  );
}

function ExerciseView({ ex, onDone }: { ex: Exercise; onDone: () => void }) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.attempt(ex.id, answer.trim().toLowerCase()));
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const sol = result?.exercise.solution ?? ex.solution;
  return (
    <Card title={ex.component_label}>
      <div className="space-y-4">
        <p className="text-slate-200">{ex.prompt}</p>
        <p className="text-xs text-slate-500">Lượt đi: {SIDE[ex.side_to_move]}{ex.played_move && ` · nước bạn đã đi: ${ex.played_move}`}</p>
        <BoardEditor initial={parsePlacement(ex.fen)} />
        <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
          {ex.answer_kind === "eval" ? (
            EVALS.map((v) => (
              <label key={v.value} className="flex items-center gap-1 text-sm text-slate-300">
                <input type="radio" name="answer" checked={answer === v.value} onChange={() => setAnswer(v.value)} /> {v.label}
              </label>
            ))
          ) : (
            <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Nước UCI, ví dụ h2e2" aria-label="Nước đi (UCI)"
              pattern="\s*[a-iA-I][0-9][a-iA-I][0-9]\s*" title="Một nước UCI: cột a–i, hàng 0–9"
              className="w-40 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100" />
          )}
          <button type="submit" disabled={busy || !answer.trim()} className={`${btn} bg-sky-700 hover:bg-sky-600`}>Trả lời</button>
        </form>
        <ErrorText error={error} />
        {result && (
          <p role="status" className={result.correct ? "text-emerald-300" : "text-amber-200"}>{result.explanation}</p>
        )}
        {sol && (
          <dl className="space-y-1 font-mono text-sm text-slate-300">
            <div><dt className="inline text-slate-500">Nước tốt nhất: </dt><dd className="inline">{sol.best_move}</dd></div>
            <div><dt className="inline text-slate-500">Biến chính: </dt><dd className="inline">{sol.principal_variation.join(" ")}</dd></div>
          </dl>
        )}
        {ex.attempts.length > 0 && (
          <p className="text-xs text-slate-500">Lần làm trước: {ex.attempts.map((a) => `${a.answer} ${a.correct ? "✓" : "✗"}`).join(", ")}</p>
        )}
      </div>
    </Card>
  );
}
