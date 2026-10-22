import { useEffect, useRef, useState } from "react";
import { RefreshCw, VideoOff } from "lucide-react";
import { MsePlayer, type PlayerStatus } from "../lib/msePlayer";
import { Spinner } from "./ui";
import { t } from "../lib/i18n";

interface Props {
  /** Cesta WebSocketu, např. /api/cameras/3/live?quality=sub */
  path: string;
  live: boolean;
  /** Automaticky obnovit spojení (živý obraz). */
  autoReconnect?: boolean;
  onStatus?: (status: PlayerStatus) => void;
  onTime?: (seconds: number) => void;
  className?: string;
}

const RECONNECT_DELAYS = [2000, 4000, 8000, 15000, 30000];
const PERMANENT_ERROR = /kodek|formát|nepodporuje|neumí|oprávnění|neexistuje|přihlášeni|odmítlo/i;

export function StreamPlayer({ path, live, autoReconnect = false, onStatus, onTime, className }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<PlayerStatus>("connecting");
  const [message, setMessage] = useState<string>("");
  const [attempt, setAttempt] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const failures = useRef(0);
  const statusCb = useRef(onStatus);
  statusCb.current = onStatus;
  const timeCb = useRef(onTime);
  timeCb.current = onTime;

  useEffect(() => {
    failures.current = 0;
  }, [path]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let retryTimer: number | undefined;
    const player = new MsePlayer(
      video,
      path,
      (next, msg) => {
        setStatus(next);
        setMessage(msg ?? "");
        statusCb.current?.(next);
        if (next === "playing") failures.current = 0;
        // Chyby, které opakováním nezmizí (kodek, oprávnění), se znovu nezkoušejí.
        const permanent = PERMANENT_ERROR.test(msg ?? "");
        setRetrying((next === "error" || next === "ended") && autoReconnect && !permanent);
        if ((next === "error" || next === "ended") && autoReconnect && !permanent) {
          const delay = RECONNECT_DELAYS[Math.min(failures.current, RECONNECT_DELAYS.length - 1)];
          failures.current += 1;
          retryTimer = window.setTimeout(() => setAttempt((a) => a + 1), delay);
        }
      },
      live,
    );
    const onTimeUpdate = () => timeCb.current?.(video.currentTime);
    video.addEventListener("timeupdate", onTimeUpdate);
    player.start();
    return () => {
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      video.removeEventListener("timeupdate", onTimeUpdate);
      player.destroy();
    };
  }, [path, live, autoReconnect, attempt]);

  return (
    <div className={`player player-${status} ${className ?? ""}`}>
      <video ref={videoRef} muted playsInline autoPlay disablePictureInPicture />
      {status === "connecting" && (
        <div className="player-overlay">
          <Spinner size={26} />
        </div>
      )}
      {(status === "error" || status === "ended") && (
        <div className="player-overlay player-error">
          <VideoOff size={26} aria-hidden />
          <p>{message || t("Video není dostupné.")}</p>
          {retrying ? (
            <small>{t("Opakuji připojení…")}</small>
          ) : (
            <button
              type="button"
              className="btn btn-small btn-ghost"
              onClick={() => {
                failures.current = 0;
                setAttempt((a) => a + 1);
              }}
            >
              <RefreshCw size={14} /> {t("Zkusit znovu")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
