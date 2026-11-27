import { afterEach, describe, expect, it, vi } from "vitest";
import { describeCaptureError, requestScreenShare } from "./screenCapture";

describe("describeCaptureError", () => {
  it("maps known DOMException names to user messages", () => {
    expect(describeCaptureError(new DOMException("x", "NotAllowedError"))).toMatch(/hủy hoặc từ chối/);
    expect(describeCaptureError(new DOMException("x", "NotSupportedError"))).toMatch(/WebView2/);
    expect(describeCaptureError(new DOMException("x", "NotReadableError"))).toMatch(/Hệ điều hành/);
  });

  it("falls back to the error message, then to a generic text", () => {
    expect(describeCaptureError(new Error("boom"))).toBe("boom");
    expect(describeCaptureError("weird")).toMatch(/không xác định/);
  });
});

describe("requestScreenShare", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("rejects with NotSupportedError when getDisplayMedia is missing", async () => {
    vi.stubGlobal("navigator", { mediaDevices: undefined });
    await expect(requestScreenShare()).rejects.toMatchObject({ name: "NotSupportedError" });
  });

  it("requests video only, never audio", async () => {
    const getDisplayMedia = vi.fn().mockResolvedValue("stream");
    vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia } });
    await expect(requestScreenShare()).resolves.toBe("stream");
    expect(getDisplayMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: false }));
  });
});
