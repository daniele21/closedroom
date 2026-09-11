export const DEFAULT_BROWSER_UPLOAD_MAX_PENDING_BYTES = 64 * 1024 * 1024;
export const DEFAULT_BROWSER_UPLOAD_MAX_PENDING_CHUNKS = 24;

export type BrowserUploadBacklogSnapshot = {
  pendingBytes: number;
  pendingChunks: number;
  maxPendingBytes: number;
  maxPendingChunks: number;
  saturated: boolean;
  highWaterBytes: number;
  highWaterChunks: number;
};

export class BrowserUploadBacklog {
  private pendingBytes = 0;
  private pendingChunks = 0;
  private highWaterBytes = 0;
  private highWaterChunks = 0;

  constructor(
    private readonly maxPendingBytes = DEFAULT_BROWSER_UPLOAD_MAX_PENDING_BYTES,
    private readonly maxPendingChunks = DEFAULT_BROWSER_UPLOAD_MAX_PENDING_CHUNKS,
  ) {
    if (maxPendingBytes < 1 || maxPendingChunks < 1) {
      throw new Error('Browser upload backlog limits must be positive.');
    }
  }

  accept(bytes: number): BrowserUploadBacklogSnapshot {
    const normalizedBytes = Math.max(0, Math.floor(bytes));
    this.pendingBytes += normalizedBytes;
    this.pendingChunks += 1;
    this.highWaterBytes = Math.max(this.highWaterBytes, this.pendingBytes);
    this.highWaterChunks = Math.max(this.highWaterChunks, this.pendingChunks);
    return this.snapshot();
  }

  release(bytes: number): BrowserUploadBacklogSnapshot {
    const normalizedBytes = Math.max(0, Math.floor(bytes));
    this.pendingBytes = Math.max(0, this.pendingBytes - normalizedBytes);
    this.pendingChunks = Math.max(0, this.pendingChunks - 1);
    return this.snapshot();
  }

  reset(): void {
    this.pendingBytes = 0;
    this.pendingChunks = 0;
    this.highWaterBytes = 0;
    this.highWaterChunks = 0;
  }

  snapshot(): BrowserUploadBacklogSnapshot {
    return {
      pendingBytes: this.pendingBytes,
      pendingChunks: this.pendingChunks,
      maxPendingBytes: this.maxPendingBytes,
      maxPendingChunks: this.maxPendingChunks,
      saturated:
        this.pendingBytes > this.maxPendingBytes ||
        this.pendingChunks > this.maxPendingChunks,
      highWaterBytes: this.highWaterBytes,
      highWaterChunks: this.highWaterChunks,
    };
  }
}
