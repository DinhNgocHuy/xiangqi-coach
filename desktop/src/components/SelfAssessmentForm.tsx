import { useState, type FormEvent } from "react";
import type { RiskFlags, SelfAssessment } from "../types/moveReview";

const input = "mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none";
const label = "block text-sm font-medium text-slate-300";
const RISKS: { key: keyof RiskFlags; label: string }[] = [
  { key: "check", label: "Bị chiếu" },
  { key: "capture", label: "Bị bắt quân" },
  { key: "counterattack", label: "Bị phản công" },
];
const POSITIONS: { value: SelfAssessment["position_assessment"]; label: string }[] = [
  { value: "better", label: "Tốt hơn" },
  { value: "equal", label: "Cân bằng" },
  { value: "worse", label: "Kém hơn" },
  { value: null, label: "Chưa đánh giá" },
];
const NO_RISKS: RiskFlags = { check: false, capture: false, counterattack: false };

/** Every field is optional; unanswered fields become ""/[]/null so they are not scored. */
export function SelfAssessmentForm({ onSubmit }: { onSubmit: (sa: SelfAssessment) => void }) {
  const [intention, setIntention] = useState("");
  const [reply, setReply] = useState("");
  const [variations, setVariations] = useState("");
  const [depth, setDepth] = useState("");
  const [risks, setRisks] = useState<RiskFlags | null>(null);
  const [position, setPosition] = useState<SelfAssessment["position_assessment"]>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit({
      intention: intention.trim(),
      predicted_opponent_reply: reply.trim().toLowerCase(),
      predicted_variations: variations.split("\n").map((l) => l.trim().toLowerCase().split(/\s+/).join(" ")).filter(Boolean),
      depth: Number.isInteger(Number.parseInt(depth, 10)) ? Number.parseInt(depth, 10) : null, // coach rejects non-integers
      recognized_risks: risks,
      position_assessment: position,
      skipped: false,
    });
  }

  const skip = () => onSubmit({ intention: "", predicted_opponent_reply: "", predicted_variations: [], depth: null, recognized_risks: null, position_assessment: null, skipped: true });

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label htmlFor="sa-intention" className={label}>Mục đích của nước đi?</label>
        <textarea id="sa-intention" rows={2} maxLength={500} value={intention} onChange={(e) => setIntention(e.target.value)} className={input} />
      </div>
      <div>
        <label htmlFor="sa-reply" className={label}>Bạn dự đoán đối thủ đáp trả thế nào? (UCI, ví dụ h9g7)</label>
        <input
          id="sa-reply"
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          pattern="\s*[a-iA-I][0-9][a-iA-I][0-9]\s*"
          title="Một nước UCI: cột a–i, hàng 0–9, ví dụ h9g7"
          className={input}
        />
      </div>
      <div>
        <label htmlFor="sa-variations" className={label}>Các biến bạn đã tính (mỗi dòng một biến, bắt đầu từ nước đáp trả của đối thủ)</label>
        <textarea id="sa-variations" rows={3} value={variations} onChange={(e) => setVariations(e.target.value)} placeholder="h9g7 h0g2 i9h9" className={`${input} font-mono`} />
      </div>
      <div>
        <label htmlFor="sa-depth" className={label}>Bạn đã tính trước bao nhiêu nước?</label>
        <input id="sa-depth" type="number" min={0} max={30} step={1} value={depth} onChange={(e) => setDepth(e.target.value)} className={`${input} w-32`} />
      </div>
      <fieldset>
        <legend className={label}>Bạn có nhận ra nguy cơ: bị chiếu, bị bắt quân, bị phản công?</legend>
        <div className="mt-2 flex flex-wrap gap-4 text-sm text-slate-300">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={risks === null} onChange={(e) => setRisks(e.target.checked ? null : NO_RISKS)} />
            Tôi chưa xét nguy cơ
          </label>
          {RISKS.map((r) => (
            <label key={r.key} className="flex items-center gap-2">
              <input type="checkbox" checked={risks?.[r.key] ?? false} onChange={(e) => setRisks({ ...(risks ?? NO_RISKS), [r.key]: e.target.checked })} />
              {r.label}
            </label>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-500">Bỏ chọn “Tôi chưa xét nguy cơ” mà không đánh dấu ô nào nghĩa là bạn thấy không có nguy cơ.</p>
      </fieldset>
      <fieldset>
        <legend className={label}>Bạn đánh giá thế cờ sau nước đi (cho bạn)?</legend>
        <div className="mt-2 flex flex-wrap gap-4 text-sm text-slate-300">
          {POSITIONS.map((p) => (
            <label key={p.label} className="flex items-center gap-2">
              <input type="radio" name="sa-position" checked={position === p.value} onChange={() => setPosition(p.value)} />
              {p.label}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex gap-2">
        <button type="submit" className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500">Gửi đánh giá</button>
        <button type="button" onClick={skip} className="rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">Bỏ qua</button>
      </div>
    </form>
  );
}
