export type CaptureStatus = "idle" | "requesting" | "sharing";

/** One still frame kept in memory only (object URL), never written to disk. */
export interface CapturedFrame {
  url: string;
  width: number;
  height: number;
  capturedAt: Date;
}
