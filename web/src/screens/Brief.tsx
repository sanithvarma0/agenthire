// Brief screen (docs/LLD.md, section 15): a live voice conversation with the assistant in
// the browser, shown as a real-time avatar (the orb until her video arrives, or if she does
// not come). One tap joins: it also lets the browser play sound and ask for the microphone.
// When the user confirms the summary, the brief ends and the search starts by itself.

import { useEffect, useRef, useState } from "react";
import { createLocalAudioTrack, Room, RoomEvent, Track, type LocalAudioTrack, type RemoteTrack } from "livekit-client";
import { CheckCircle2, Mic, MicOff, Sparkles } from "lucide-react";
import { api, type Job, type JobEvent } from "../api";
import { JobLayout, StepRail } from "../components/Frame";
import { useJob } from "../store";

type Phase = "ready" | "connecting" | "live" | "ended" | "failed";

export function Brief({ job }: { job: Job }) {
  const events = useJob((s) => s.events);
  const company = job.side === "company";
  const conversation = job.conversations.find((c) => c.kind === "brief" || c.kind === "role_brief");
  const mine = events.filter((e) => e.conversation_id === conversation?.id);
  const lines = mine.filter((e) => e.type === "agent_said" || e.type === "person_said");
  const ended = mine.some((e) => e.type === "conversation_ended");
  const [phase, setPhase] = useState<Phase>("ready");
  const [problem, setProblem] = useState<string | null>(null);
  const [agentTalking, setAgentTalking] = useState(false);
  const [youTalking, setYouTalking] = useState(false);
  const [hasVideo, setHasVideo] = useState(false);
  const [muted, setMuted] = useState(false);
  const room = useRef<Room | null>(null);
  const mic = useRef<LocalAudioTrack | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLDivElement>(null);

  useEffect(() => () => void room.current?.disconnect(), []);
  useEffect(() => {
    if (ended) {
      setPhase("ended");
      void room.current?.disconnect();
    }
  }, [ended]);

  const talk = async () => {
    setPhase("connecting");
    setProblem(null);
    await room.current?.disconnect();
    room.current = null;
    try {
      // The microphone first: if it is blocked, stop before the assistant joins and talks.
      mic.current = await createLocalAudioTrack({ echoCancellation: true, noiseSuppression: true });
      const access = await api.voice(job.id);
      const r = new Room({ adaptiveStream: true, dynacast: true });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Video && video.current) {
          track.attach(video.current);
          setHasVideo(true);
        } else if (track.kind === Track.Kind.Audio) {
          audio.current?.appendChild(track.attach());
        }
      });
      r.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Video) setHasVideo(false);
        track.detach();
      });
      r.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const me = r.localParticipant.identity;
        setAgentTalking(speakers.some((s) => s.identity !== me));
        setYouTalking(speakers.some((s) => s.identity === me));
      });
      r.on(RoomEvent.Disconnected, () => setPhase((p) => (p === "live" ? "ended" : p)));
      await r.connect(access.url, access.token);
      await r.startAudio();
      await r.localParticipant.publishTrack(mic.current);
      setPhase("live");
    } catch (err) {
      await room.current?.disconnect();
      room.current = null;
      setPhase("failed");
      setProblem(micProblem(err));
    }
  };

  const toggleMute = async () => {
    if (!mic.current) return;
    if (muted) await mic.current.unmute();
    else await mic.current.mute();
    setMuted(!muted);
  };

  const noted: Record<string, string> = {};
  for (const e of mine) if (e.type === "fact_recorded") noted[String(e.payload.name)] = String(e.payload.value);
  const last = lines.at(-1);

  const stage = (
    <>
      <div className="agent-stage">
        <video ref={video} autoPlay playsInline muted style={{ opacity: hasVideo ? 1 : 0, transition: "opacity .4s" }} />
        {!hasVideo && (
          <div className="stage-center">
            {phase === "ready" || phase === "failed" ? (
              <button className="orb" onClick={talk} aria-label="Tap to talk" />
            ) : (
              <div className={`orb ${agentTalking ? "speaking" : ""}`} aria-hidden="true" />
            )}
            <p className="title md" style={{ marginTop: 18 }}>
              {phase === "ready" && "Tap to start talking"}
              {phase === "connecting" && "Your assistant is joining…"}
              {phase === "live" && (agentTalking ? "Speaking…" : youTalking ? "Listening…" : "Your turn")}
              {phase === "ended" && (company ? "Got it. Writing the job description…" : "Got it. Finding people near you…")}
              {phase === "failed" && "Tap to try again"}
            </p>
            {phase === "ready" && <p className="muted small" style={{ margin: 0 }}>Your microphone is used only while you talk to the assistant.</p>}
          </div>
        )}
        {(phase === "live" || hasVideo) && (
          <span className="badge-live"><span className={`dot ${phase === "live" ? "" : "idle"}`} />Your assistant{hasVideo ? " · live" : ""}</span>
        )}
        {hasVideo && last && (
          <div className={`caption ${last.type === "person_said" ? "you" : ""}`}>
            <span className="who">{last.type === "person_said" ? "You" : "Assistant"}</span>
            {String(last.payload.text ?? "")}
          </div>
        )}
      </div>
      {problem && <div className="notice bad" role="alert">{problem}</div>}
      {phase === "live" && (
        <div className="controls">
          <button className={`btn ${muted ? "" : "ghost"}`} onClick={toggleMute}>
            {muted ? <><MicOff size={17} />Unmute</> : <><Mic size={17} />Mute</>}
          </button>
          <span className={`bars ${youTalking ? "on" : ""}`} style={{ color: "var(--user)" }} aria-hidden="true">
            {Array.from({ length: 6 }, (_, i) => <span key={i} style={{ animationDelay: `${i * 90}ms` }} />)}
          </span>
        </div>
      )}
      <div ref={audio} hidden />
    </>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <section className="panel tight">
        <div className="panel-head"><p className="eyebrow">What I have so far</p><Sparkles size={15} className="accent" /></div>
        <div className="facts">
          {company ? (
            <>
              <span className={`fact ${noted.role ? "got" : ""}`}>{noted.role ?? "The role…"}</span>
              <span className={`fact ${noted.must_haves ? "got" : ""}`}>{noted.must_haves ?? "Must-haves…"}</span>
              {noted.experience && <span className="fact got">{noted.experience}</span>}
              {noted.location && <span className="fact got">{noted.location}</span>}
            </>
          ) : (
            <>
              <span className={`fact ${noted.work ? "got" : ""}`}>{noted.work ?? "What needs fixing…"}</span>
              {noted.service && <span className="fact got">{noted.service}</span>}
            </>
          )}
          <span className={`fact ${noted.confirmed ? "got" : ""}`}>
            {noted.confirmed ? <><CheckCircle2 size={13} />Confirmed</> : "Your OK…"}
          </span>
        </div>
        <p className="faint small" style={{ margin: "10px 0 0" }}>{company ? `For ${job.start?.company}` : `Near ${job.start?.area}`}</p>
      </section>
      {lines.length > 0 && (
        <section className="panel tight">
          <p className="eyebrow" style={{ marginBottom: 10 }}>Conversation</p>
          <Transcript lines={lines} them="You" agent="Assistant" />
        </section>
      )}
    </>
  );

  return <JobLayout stage={stage} rail={rail} />;
}

export function Transcript({ lines, them, agent = "Agent" }: { lines: JobEvent[]; them: string; agent?: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" });
  }, [lines.length]);
  return (
    <div className="transcript" ref={box}>
      {lines.map((e) => (
        <p key={e.seq} className={`bubble ${e.type === "agent_said" ? "agent" : "them"}`} style={{ margin: 0 }}>
          <span className="who">{e.type === "agent_said" ? agent : them}</span>
          {String(e.payload.text ?? "")}
        </p>
      ))}
    </div>
  );
}

function micProblem(err: unknown): string {
  const name = (err as { name?: string })?.name ?? "";
  if (name === "NotAllowedError") return "The microphone is blocked. Allow it for this site, then tap the orb again.";
  if (name === "NotFoundError") return "No microphone was found on this device.";
  return `Couldn't start the voice brief: ${(err as Error)?.message ?? String(err)}`;
}
