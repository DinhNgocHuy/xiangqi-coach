import { useCallback, useEffect, useState } from "react";
import { describeCaptureError, requestScreenShare } from "../services/screenCapture";
import type { CaptureStatus } from "../types/capture";

/** Owns the single shared MediaStream. Lives in App so sharing survives page switches. */
export function useScreenCapture() {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stop the old stream's tracks whenever it is replaced, cleared, or the app unmounts.
  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream]);

  const start = useCallback(async () => {
    setRequesting(true);
    setError(null);
    try {
      const s = await requestScreenShare();
      // User may stop sharing from the OS/WebView2 bar instead of our button.
      s.getVideoTracks()[0]?.addEventListener("ended", () => setStream((cur) => (cur === s ? null : cur)));
      setStream(s);
    } catch (e) {
      setError(describeCaptureError(e));
    } finally {
      setRequesting(false);
    }
  }, []);

  const stop = useCallback(() => setStream(null), []);

  const status: CaptureStatus = requesting ? "requesting" : stream ? "sharing" : "idle";
  const source = stream?.getVideoTracks()[0]?.label ?? null;
  return { stream, status, source, error, start, stop };
}

export type ScreenCapture = ReturnType<typeof useScreenCapture>;
