import type { CapturedFrame } from "../types/capture";

/** Opens the OS/WebView2 picker; the user chooses a screen or window. Nothing is captured without that choice. */
export async function requestScreenShare(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new DOMException("getDisplayMedia is unavailable", "NotSupportedError");
  }
  // Low frame rate: we only need still frames, so keep CPU/GPU usage small.
  return navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { max: 10 } }, audio: false });
}

export async function grabFrame(video: HTMLVideoElement): Promise<CapturedFrame> {
  const { blob, width, height } = await grabFrameBlob(video);
  return { url: URL.createObjectURL(blob), width, height, capturedAt: new Date() };
}

/** Same still frame as grabFrame, as a PNG Blob (for upload). No object URL is created, so nothing to revoke. */
export async function grabFrameBlob(video: HTMLVideoElement): Promise<{ blob: Blob; width: number; height: number }> {
  const { videoWidth: width, videoHeight: height } = video;
  if (!width || !height) throw new Error("Chưa nhận được hình ảnh từ nguồn chia sẻ, hãy thử lại sau giây lát.");

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Không tạo được canvas 2D để chụp khung hình.");
  ctx.drawImage(video, 0, 0, width, height);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Không mã hóa được khung hình.");
  return { blob, width, height };
}

export function describeCaptureError(err: unknown): string {
  const name = err instanceof DOMException || err instanceof Error ? err.name : "";
  switch (name) {
    case "NotAllowedError":
      return "Bạn đã hủy hoặc từ chối chia sẻ màn hình.";
    case "NotSupportedError":
      return "WebView hiện tại không hỗ trợ chia sẻ màn hình. Hãy chạy ứng dụng trên Windows 10/11 có WebView2.";
    case "NotFoundError":
      return "Không tìm thấy màn hình hoặc cửa sổ nào để chia sẻ.";
    case "NotReadableError":
    case "AbortError":
      return "Hệ điều hành không cho phép đọc nguồn hình ảnh. Hãy thử chọn lại cửa sổ khác.";
  }
  return err instanceof Error && err.message ? err.message : "Lỗi không xác định khi chia sẻ màn hình.";
}
