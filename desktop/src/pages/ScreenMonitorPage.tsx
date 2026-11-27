import { useEffect, useRef, useState } from "react";
import { LiveReview } from "../components/LiveReview";
import { SessionPanel } from "../components/SessionPanel";
import { StatusBadge } from "../components/StatusBadge";
import { TrackingPanel } from "../components/TrackingPanel";
import type { ScreenCapture } from "../hooks/useScreenCapture";
import type { SessionState } from "../hooks/useSession";
import { grabFrame } from "../services/screenCapture";
import type { Orientation } from "../types/api";
import type { CapturedFrame } from "../types/capture";

const btn = "rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";

export function ScreenMonitorPage({ capture, session }: { capture: ScreenCapture; session: SessionState }) {
  const { stream, status, source, error, start, stop } = capture;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [frame, setFrame] = useState<CapturedFrame | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [orientation, setOrientation] = useState<Orientation | null>(null);

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, [stream]);

  // Free the previous frame's memory when it is replaced or the page closes.
  useEffect(() => () => { if (frame) URL.revokeObjectURL(frame.url); }, [frame]);

  async function onCapture() {
    if (!videoRef.current) return;
    setFrameError(null);
    try {
      setFrame(await grabFrame(videoRef.current));
    } catch (e) {
      setFrameError(e instanceof Error ? e.message : String(e));
    }
  }

  const sharing = status === "sharing";

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Screen Monitor</h1>
          <p className="text-sm text-slate-400">
            Bạn tự chọn cửa sổ hoặc màn hình để chia sẻ. Khung hình chỉ nằm trong bộ nhớ và chỉ gửi tới backend chạy trên máy này
            (127.0.0.1), không lưu đĩa, không gửi lên Internet.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={start} disabled={status !== "idle"} className={`${btn} bg-emerald-600 hover:bg-emerald-500`}>
            Start Monitoring
          </button>
          <button onClick={stop} disabled={!sharing} className={`${btn} bg-red-600 hover:bg-red-500`}>
            Stop Monitoring
          </button>
          <button onClick={onCapture} disabled={!sharing} className={`${btn} bg-sky-600 hover:bg-sky-500`}>
            Chụp khung hình
          </button>
        </div>
      </header>

      <div className="flex items-center gap-4">
        <StatusBadge status={status} />
        {source && <span className="truncate text-xs text-slate-500">Nguồn: {source}</span>}
      </div>

      {(error || frameError) && (
        <div role="alert" className="rounded-md border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          {error ?? frameError}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <SessionPanel s={session} defaultSide={orientation === "red_top" ? "b" : "w"} />
        <TrackingPanel videoRef={videoRef} sharing={sharing} s={session} onOrientation={setOrientation} />
      </div>

      <LiveReview s={session} />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <h2 className="mb-2 text-sm font-semibold text-slate-400">Xem trực tiếp</h2>
          {stream ? (
            <video ref={videoRef} autoPlay muted playsInline className="w-full rounded bg-black" />
          ) : (
            <Empty text="Chưa chia sẻ. Bấm Start Monitoring và chọn cửa sổ Ziga.vn." />
          )}
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-400">Khung hình đã chụp</h2>
            {frame && (
              <button onClick={() => setFrame(null)} className="text-xs text-slate-400 hover:text-slate-200">
                Xóa
              </button>
            )}
          </div>
          {frame ? (
            <figure>
              <img src={frame.url} alt="Khung hình màn hình đã chụp" className="w-full rounded" />
              <figcaption className="mt-2 text-xs text-slate-500">
                {frame.width}×{frame.height}px · {frame.capturedAt.toLocaleTimeString("vi-VN")}
              </figcaption>
            </figure>
          ) : (
            <Empty text="Chưa có khung hình." />
          )}
        </section>
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="flex aspect-video items-center justify-center rounded border border-dashed border-slate-700 text-sm text-slate-500">{text}</div>;
}
