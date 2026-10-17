// Voice capture → ElevenLabs Scribe v2 (via our backend). Records with MediaRecorder, shows a live
// level meter, and stops by itself ~1.3s after you finish speaking (or on a second click).
import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "listening" | "transcribing" | "error";

const SILENCE_MS = 1300;
const MAX_MS = 25_000;
const SPEECH_LEVEL = 0.045;

export function useVoice(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [levels, setLevels] = useState<number[]>(() => Array(20).fill(0));
  const [error, setError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const rec = useRef<{ stop: () => void } | null>(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  useEffect(() => {
    fetch("/api/voice/status").then((r) => r.json()).then((s) => setEnabled(!!s.enabled)).catch(() => setEnabled(false));
  }, []);

  const start = useCallback(async () => {
    if (rec.current) { rec.current.stop(); return; }
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      setError("Microphone permission was denied");
      setState("error");
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const t0 = performance.now();
    let lastVoice = 0;
    let heard = false;
    let raf = 0;
    let stopped = false;

    const stop = () => {
      if (stopped) return;
      stopped = true;
      cancelAnimationFrame(raf);
      if (recorder.state !== "inactive") recorder.stop();
    };
    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      const rms = Math.sqrt(sum / buf.length);
      setLevels((ls) => [...ls.slice(1), Math.min(1, rms * 9)]);
      const now = performance.now();
      if (rms > SPEECH_LEVEL) { heard = true; lastVoice = now; }
      if ((heard && now - lastVoice > SILENCE_MS) || now - t0 > MAX_MS) { stop(); return; }
      raf = requestAnimationFrame(tick);
    };

    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      rec.current = null;
      setLevels(Array(20).fill(0));
      if (!heard) { setState("idle"); setError("Didn't catch that — try again"); return; }
      setState("transcribing");
      try {
        const form = new FormData();
        form.append("file", new Blob(chunks, { type: recorder.mimeType || "audio/webm" }), "voice.webm");
        const r = await fetch("/api/voice/transcribe", { method: "POST", body: form });
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);
        setState("idle");
        if (body.text) onTextRef.current(body.text);
        else setError("No speech recognised");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    };
    recorder.start(250);
    rec.current = { stop };
    setState("listening");
    raf = requestAnimationFrame(tick);
  }, []);

  return { state, levels, error, enabled, toggle: start, clearError: () => { setError(null); setState("idle"); } };
}
