// Listen to a phone call as it happens: the browser joins the call's room as a hidden,
// listen-only participant (POST /jobs/{id}/listen) and plays every voice in it, the agent's
// and the person's. One tap starts it, which also lets the browser play sound.

import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { Headphones, VolumeX } from "lucide-react";
import { api } from "../api";

type State = "off" | "joining" | "on" | "failed";

export function ListenLive({ jobId, conversationId, live }: { jobId: string; conversationId: string; live: boolean }) {
  const [state, setState] = useState<State>("off");
  const room = useRef<Room | null>(null);
  const audio = useRef<HTMLDivElement>(null);

  const stop = () => {
    void room.current?.disconnect();
    room.current = null;
    if (audio.current) audio.current.innerHTML = "";
    setState("off");
  };

  // Leave when the call ends, when the next call starts, or when the screen closes.
  useEffect(() => { if (!live) stop(); }, [live]);
  useEffect(() => stop, [conversationId]);

  const start = async () => {
    setState("joining");
    try {
      const access = await api.listen(jobId);
      const r = new Room();
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) audio.current?.appendChild(track.attach());
      });
      r.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => { track.detach().forEach((el) => el.remove()); });
      r.on(RoomEvent.Disconnected, () => setState((s) => (s === "on" ? "off" : s)));
      await r.connect(access.url, access.token, { autoSubscribe: true });
      await r.startAudio();
      setState("on");
    } catch {
      room.current = null;
      setState("failed");
    }
  };

  if (!live) return null;
  return (
    <div className="listen">
      {state === "on" ? (
        <button className="btn ghost sm" onClick={stop}><VolumeX size={15} />Stop listening</button>
      ) : (
        <button className="btn sm" onClick={start} aria-busy={state === "joining"}>
          <Headphones size={15} />{state === "joining" ? "Joining…" : "Listen live"}
        </button>
      )}
      <span className="faint small">
        {state === "on" ? "You are hearing both sides of the call." : state === "failed" ? "Couldn't join the call audio. Try again." : "Hear the agent and the person, live."}
      </span>
      <div ref={audio} hidden />
    </div>
  );
}
