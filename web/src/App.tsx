// The whole app is one page. The address bar holds where you are (#/job/<id>, #/hire or
// #/history), so a reload or another device opens the same job at its current step.

import { useEffect, useState } from "react";
import { TopBar, type Nav } from "./components/Frame";
import { Hire } from "./screens/Hire";
import { History } from "./screens/History";
import { JobScreen } from "./screens/JobScreen";
import { Start } from "./screens/Start";
import { useJob } from "./store";

type View = { name: "start" } | { name: "hire" } | { name: "history" } | { name: "job"; id: string };

function viewFromHash(): View {
  const hash = window.location.hash;
  const job = hash.match(/^#\/job\/([\w-]+)$/);
  if (job) return { name: "job", id: job[1] };
  if (hash === "#/history") return { name: "history" };
  if (hash === "#/hire") return { name: "hire" };
  return { name: "start" };
}

function hashOf(view: View): string {
  return view.name === "job" ? `#/job/${view.id}` : view.name === "start" ? "" : `#/${view.name}`;
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
  const home = () => go({ name: "start" });
  const hire = () => go({ name: "hire" });
  const history = () => go({ name: "history" });
  const open = (id: string) => go({ name: "job", id });

  return (
    <>
      <TopBar onHome={home} onHire={hire} onHistory={history} at={view.name as Nav} />
      <div className="page">
        {view.name === "job" && <JobScreen jobId={view.id} onRestart={home} />}
        {view.name === "history" && <History onOpen={open} onNew={home} />}
        {view.name === "hire" && <Hire onStarted={open} />}
        {view.name === "start" && <Start onStarted={open} onHistory={history} />}
      </div>
    </>
  );
}
