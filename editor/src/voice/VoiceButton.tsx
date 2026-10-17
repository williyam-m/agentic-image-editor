import type { VoiceState } from "./useVoice";

/** Mic button with a live waveform while listening. */
export function VoiceButton({ state, levels, enabled, onClick, compact }: {
  state: VoiceState; levels: number[]; enabled: boolean | null; onClick: () => void; compact?: boolean;
}) {
  const listening = state === "listening";
  const busy = state === "transcribing";
  const title = enabled === false ? "Voice needs ELEVENLABS_API_KEY in .env"
    : listening ? "Listening — stops when you pause (click to stop)" : busy ? "Transcribing…" : "Speak your edit (M)";
  return (
    <button type="button" className={`voice-btn ${state} ${compact ? "compact" : ""}`} onClick={onClick}
      disabled={enabled === false || busy} title={title} aria-label={title} data-testid="voice-btn">
      {listening ? (
        <span className="wave">{levels.slice(-(compact ? 6 : 9)).map((l, i) => <i key={i} style={{ height: `${18 + l * 82}%` }} />)}</span>
      ) : busy ? <span className="spinner" /> : (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden><path fill="currentColor"
          d="M12 15a3.5 3.5 0 0 0 3.5-3.5v-6a3.5 3.5 0 1 0-7 0v6A3.5 3.5 0 0 0 12 15Zm6-3.5a.9.9 0 1 0-1.8 0 4.2 4.2 0 0 1-8.4 0 .9.9 0 1 0-1.8 0 6 6 0 0 0 5.1 5.93V20H8.6a.9.9 0 1 0 0 1.8h6.8a.9.9 0 1 0 0-1.8h-2.5v-2.57A6 6 0 0 0 18 11.5Z" /></svg>
      )}
    </button>
  );
}
