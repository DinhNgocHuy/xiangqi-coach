import { afterEach, describe, expect, it, vi } from "vitest";
import { BACKEND_URL, BackendError, Cancelled, api, request, retryWhileOffline } from "./backend";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("backend request", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("sends X-XQC-Client and JSON on POST, not on GET", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(json({ ok: 1 })));
    vi.stubGlobal("fetch", fetch);
    await api.addMove("s1", "h2e2");
    await api.health();
    const [url, post] = fetch.mock.calls[0];
    expect(url).toBe(`${BACKEND_URL}/sessions/s1/moves`);
    expect(post).toMatchObject({ method: "POST", headers: { "X-XQC-Client": "1", "Content-Type": "application/json" }, body: '{"uci":"h2e2"}' });
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "GET", headers: {} });
  });

  it("sends the header on DELETE and the raw PNG as image/png", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(json({})));
    vi.stubGlobal("fetch", fetch);
    await api.undoMove("s1");
    const png = new Blob(["x"], { type: "image/png" });
    await api.readBoard(png);
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "DELETE", headers: { "X-XQC-Client": "1" } });
    const [url, upload] = fetch.mock.calls[1];
    expect(url).toBe(`${BACKEND_URL}/vision/board`);
    expect(upload).toMatchObject({ method: "POST", headers: { "X-XQC-Client": "1", "Content-Type": "image/png" } });
    expect(upload.body).toBe(png);
  });

  it("uses FastAPI detail as the error message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Không tìm thấy buổi tập." }, 404)));
    await expect(api.getSession("x")).rejects.toMatchObject({ name: "BackendError", status: 404, message: "Không tìm thấy buổi tập." });
  });

  it("joins validation errors and falls back to a status text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: [{ msg: "too long" }, { msg: "missing" }] }, 422)));
    await expect(request("/x")).rejects.toThrow("Dữ liệu không hợp lệ: too long; missing");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 500 })));
    await expect(request("/x")).rejects.toThrow(/Lỗi backend \(500\)/);
  });

  it("maps a network failure to the offline message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = (await request("/health").catch((e) => e)) as BackendError;
    expect(err).toBeInstanceOf(BackendError);
    expect(err.message).toMatch(/^Backend chưa chạy/);
    expect(err.status).toBeNull();
  });

  it("aborts after the timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_u: string, init: RequestInit) =>
      new Promise((_r, reject) => init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))));
    const p = request("/slow", { timeoutMs: 2000 }).catch((e: Error) => e);
    await vi.advanceTimersByTimeAsync(2000);
    expect(((await p) as Error).message).toBe("Backend không phản hồi sau 2 giây.");
  });
});

describe("cancel and retry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("rejects with Cancelled when the caller aborts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_u: string, init: RequestInit) =>
      new Promise((_r, reject) => init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))));
    const ctrl = new AbortController();
    const p = request("/x", { signal: ctrl.signal }).catch((e) => e);
    ctrl.abort();
    expect(await p).toBeInstanceOf(Cancelled);
    await expect(request("/x", { signal: ctrl.signal })).rejects.toBeInstanceOf(Cancelled); // already aborted
  });

  it("retries only while offline", async () => {
    vi.useFakeTimers();
    const fn = vi.fn()
      .mockRejectedValueOnce(new BackendError("off", null))
      .mockRejectedValueOnce(new BackendError("off", null))
      .mockResolvedValue("ok");
    const p = retryWhileOffline(fn, undefined, 5, 100);
    await vi.advanceTimersByTimeAsync(200);
    expect(await p).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(3);

    const http = vi.fn().mockRejectedValue(new BackendError("404", 404));
    await expect(retryWhileOffline(http, undefined, 5, 100)).rejects.toMatchObject({ status: 404 });
    expect(http).toHaveBeenCalledTimes(1);
  });

  it("gives up after the last try or when cancelled", async () => {
    vi.useFakeTimers();
    const off = vi.fn().mockRejectedValue(new BackendError("off", null));
    const p = retryWhileOffline(off, undefined, 3, 100).catch((e) => e);
    await vi.advanceTimersByTimeAsync(300);
    expect(((await p) as Error).message).toBe("off");
    expect(off).toHaveBeenCalledTimes(3);

    const ctrl = new AbortController();
    const q = retryWhileOffline(off, ctrl.signal, 10, 100).catch((e) => e);
    ctrl.abort();
    await vi.advanceTimersByTimeAsync(100);
    expect(await q).toBeInstanceOf(Error);
  });
});
