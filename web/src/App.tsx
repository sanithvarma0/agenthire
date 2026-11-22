// The whole app is one page. The address bar holds where you are (#/gig, #/hire, #/history
// or #/job/<id>), so a reload or another device opens the same place. The bare address is the
// choice between the two sides.

import { useEffect, useState } from "react";
import { TopBar, type Nav } from "./components/Frame";
import { Choose } from "./screens/Choose";
import { Hire } from "./screens/Hire";
import { History } from "./screens/History";
import { JobScreen } from "./screens/JobScreen";
import { Start } from "./screens/Start";
import { useJob } from "./store";

type View = { name: "choose" } | { name: "gig" } | { name: "hire" } | { name: "history" } | { name: "job"; id: string };

function viewFromHash(): View {
  const hash = window.location.hash;
  const job = hash.match(/^#\/job\/([\w-]+)$/);
  if (job) return { name: "job", id: job[1] };
  if (hash === "#/history") return { name: "history" };
  if (hash === "#/hire") return { name: "hire" };
  if (hash === "#/gig") return { name: "gig" };
  return { name: "choose" };
}

function hashOf(view: View): string {
  return view.name === "job" ? `#/job/${view.id}` : view.name === "choose" ? "" : `#/${view.name}`;
}

export function App() {
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (next: View) => {
    if (next.name !== "job") {
      useJob.getState().close();
      useJob.setState({ jobId: null, job: null, events: [], lastSeq: 0 });
    }
    window.location.hash = hashOf(next);
    setView(next);
    window.scrollTo({ top: 0 });
  };
  const choose = () => go({ name: "choose" });
  const gig = () => go({ name: "gig" });
  const hire = () => go({ name: "hire" });
  const history = () => go({ name: "history" });
  const open = (id: string) => go({ name: "job", id });

  return (
    <>
      <TopBar onHome={choose} onGig={gig} onHire={hire} onHistory={history} at={view.name as Nav} />
      <div className="page">
        {view.name === "job" && <JobScreen jobId={view.id} onRestart={choose} />}
        {view.name === "history" && <History onOpen={open} onNew={choose} />}
        {view.name === "hire" && <Hire onStarted={open} />}
        {view.name === "gig" && <Start onStarted={open} />}
        {view.name === "choose" && <Choose onGig={gig} onIt={hire} onOpen={open} onHistory={history} />}
      </div>
    </>
  );
}
