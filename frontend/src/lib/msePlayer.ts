/**
 * Přehrávač MSE streamu z go2rtc (přes WebSocket proxy aplikace).
 *
 * Protokol: po otevření spojení klient pošle {"type":"mse","value":"<kodeky>"},
 * server odpoví {"type":"mse","value":"video/mp4; codecs=..."} a poté posílá
 * binární fragmenty fMP4. Chyby přicházejí jako {"type":"error","value":"..."}.
 */

export type PlayerStatus = "connecting" | "playing" | "error" | "ended";

type StatusListener = (status: PlayerStatus, message?: string) => void;

const VIDEO_CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0"];
const MAX_QUEUE_BYTES = 16 * 1024 * 1024;
const KEEP_BUFFER_SECONDS = 20;
const LIVE_MAX_DELAY = 2.5;

type MediaSourceCtor = {
  new (): MediaSource;
  isTypeSupported(type: string): boolean;
};

function mediaSourceCtor(): { ctor: MediaSourceCtor; managed: boolean } | null {
  const w = window as unknown as { ManagedMediaSource?: MediaSourceCtor; MediaSource?: MediaSourceCtor };
  if (w.MediaSource) return { ctor: w.MediaSource, managed: false };
  if (w.ManagedMediaSource) return { ctor: w.ManagedMediaSource, managed: true };
  return null;
}

export function translateStreamError(raw: string): string {
  const text = raw.toLowerCase();
  if (text.includes("codecs not matched") || text.includes("codecs not match")) {
    return "Prohlížeč nepodporuje kodek kamery (pravděpodobně H.265). Nastavte stream na H.264 nebo zapněte převod na H.264 u zařízení.";
  }
  if (text.includes("401") || text.includes("unauthorized")) {
    return "Zařízení odmítlo přihlášení k videu (RTSP).";
  }
  if (text.includes("timeout") || text.includes("i/o timeout")) {
    return "Zařízení neodpovídá (vypršel časový limit).";
  }
  if (text.includes("connection refused") || text.includes("no route") || text.includes("unreachable")) {
    return "Zařízení není dosažitelné (RTSP).";
  }
  if (text.includes("404") || text.includes("not found") || text.includes("wrong response")) {
    return "Stream není k dispozici (kamera offline nebo neexistující kanál).";
  }
  return `Video nelze přehrát: ${raw}`;
}

function closeReason(code: number): string | null {
  switch (code) {
    case 4401:
      return "Nejste přihlášeni nebo nemáte oprávnění.";
    case 4404:
      return "Kamera neexistuje nebo je zařízení vypnuté.";
    case 4400:
    case 1008:
      return "Neplatný požadavek na stream.";
    case 1011:
      return "Video služba není dostupná.";
    default:
      return null;
  }
}

export class MsePlayer {
  private ws: WebSocket | null = null;
  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private queue: Uint8Array[] = [];
  private queueBytes = 0;
  private objectUrl: string | null = null;
  private destroyed = false;
  private failed = false;
  private status: PlayerStatus = "connecting";

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly path: string,
    private readonly onStatus: StatusListener,
    private readonly live: boolean,
  ) {}

  start(): void {
    const found = mediaSourceCtor();
    if (!found) {
      this.fail("Tento prohlížeč nepodporuje přehrávání videa (Media Source Extensions).");
      return;
    }
    this.setStatus("connecting");
    const mediaSource = new found.ctor();
    this.mediaSource = mediaSource;
    if (found.managed) {
      (this.video as HTMLVideoElement & { disableRemotePlayback: boolean }).disableRemotePlayback = true;
    }
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.addEventListener("playing", this.onPlaying);
    mediaSource.addEventListener("sourceopen", this.onSourceOpen, { once: true });
    this.objectUrl = URL.createObjectURL(mediaSource);
    this.video.src = this.objectUrl;
  }

  destroy(): void {
    this.destroyed = true;
    this.video.removeEventListener("playing", this.onPlaying);
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close(1000);
      }
      this.ws = null;
    }
    if (this.sourceBuffer) {
      this.sourceBuffer.removeEventListener("updateend", this.onUpdateEnd);
      this.sourceBuffer = null;
    }
    this.queue = [];
    this.queueBytes = 0;
    try {
      this.video.pause();
      this.video.removeAttribute("src");
      this.video.load();
    } catch {
      /* element už mohl být odpojen */
    }
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
    this.mediaSource = null;
  }

  private setStatus(status: PlayerStatus, message?: string): void {
    if (this.destroyed) return;
    this.status = status;
    this.onStatus(status, message);
  }

  private fail(message: string): void {
    if (this.failed || this.destroyed) return;
    this.failed = true;
    this.setStatus("error", message);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.close(1000);
  }

  private onPlaying = (): void => {
    if (this.status !== "playing") this.setStatus("playing");
  };

  private onSourceOpen = (): void => {
    if (this.destroyed) return;
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${scheme}//${window.location.host}${this.path}`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      const codecs = this.supportedCodecs();
      if (!codecs) {
        this.fail("Tento prohlížeč neumí přehrát video H.264 ani H.265. Použijte Chrome, Edge, Safari nebo Firefox.");
        return;
      }
      ws.send(JSON.stringify({ type: "mse", value: codecs }));
    };
    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string") this.onText(event.data);
      else this.onData(new Uint8Array(event.data as ArrayBuffer));
    };
    ws.onclose = (event: CloseEvent) => {
      if (this.destroyed || this.failed) return;
      const reason = closeReason(event.code);
      if (reason) this.fail(reason);
      else this.setStatus("ended", this.live ? "Spojení se streamem bylo ukončeno." : "Přehrávání skončilo.");
    };
  };

  private supportedCodecs(): string {
    const found = mediaSourceCtor();
    if (!found) return "";
    return VIDEO_CODECS.filter((codec) => found.ctor.isTypeSupported(`video/mp4; codecs="${codec}"`)).join(",");
  }

  private onText(text: string): void {
    let message: { type?: string; value?: string };
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (message.type === "mse" && typeof message.value === "string") {
      this.setupBuffer(message.value);
    } else if (message.type === "error") {
      this.fail(translateStreamError(String(message.value ?? "")));
    }
  }

  private setupBuffer(mime: string): void {
    const mediaSource = this.mediaSource;
    if (!mediaSource || mediaSource.readyState !== "open" || this.sourceBuffer) return;
    try {
      const buffer = mediaSource.addSourceBuffer(mime);
      buffer.mode = "segments";
      buffer.addEventListener("updateend", this.onUpdateEnd);
      this.sourceBuffer = buffer;
    } catch {
      this.fail(`Prohlížeč nepodporuje formát videa (${mime}).`);
    }
  }

  private onData(data: Uint8Array): void {
    const buffer = this.sourceBuffer;
    if (!buffer || this.failed) return;
    if (buffer.updating || this.queue.length > 0) {
      this.queue.push(data);
      this.queueBytes += data.byteLength;
      if (this.queueBytes > MAX_QUEUE_BYTES) {
        this.fail("Video nestíhá – příliš pomalé zpracování nebo připojení.");
      }
      return;
    }
    this.append(data);
  }

  private append(data: Uint8Array): void {
    const buffer = this.sourceBuffer;
    if (!buffer) return;
    try {
      buffer.appendBuffer(data);
    } catch (err) {
      if (err instanceof DOMException && err.name === "QuotaExceededError") {
        this.queue.unshift(data);
        this.queueBytes += data.byteLength;
        this.trim(true);
        return;
      }
      this.fail("Chyba dekódování videa.");
    }
  }

  private trim(force: boolean): boolean {
    const buffer = this.sourceBuffer;
    if (!buffer || buffer.updating || buffer.buffered.length === 0) return false;
    const start = buffer.buffered.start(0);
    const end = buffer.buffered.end(buffer.buffered.length - 1);
    const removeTo = Math.min(end - KEEP_BUFFER_SECONDS / 2, this.video.currentTime - 2);
    if ((force || end - start > KEEP_BUFFER_SECONDS * 2) && removeTo > start) {
      try {
        buffer.remove(start, removeTo);
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }

  private onUpdateEnd = (): void => {
    const buffer = this.sourceBuffer;
    if (!buffer || buffer.updating || this.destroyed) return;
    if (this.queue.length > 0) {
      const total = this.queueBytes;
      const merged = new Uint8Array(total);
      let offset = 0;
      for (const chunk of this.queue) {
        merged.set(chunk, offset);
        offset += chunk.byteLength;
      }
      this.queue = [];
      this.queueBytes = 0;
      this.append(merged);
      return;
    }
    if (this.trim(false)) return;
    if (buffer.buffered.length === 0) return;

    const start = buffer.buffered.start(0);
    const end = buffer.buffered.end(buffer.buffered.length - 1);
    const video = this.video;
    if (video.currentTime < start) {
      video.currentTime = start;
    } else if (this.live && end - video.currentTime > LIVE_MAX_DELAY) {
      // Živý obraz: dohnat zpoždění, aby obraz neujížděl za realitou.
      video.currentTime = Math.max(start, end - 0.5);
    }
    if (video.paused) {
      video.play().catch(() => {
        /* autoplay může být dočasně blokován – zkusí se při dalších datech */
      });
    }
  };
}
