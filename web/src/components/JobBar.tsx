/* Live progress for Companies House downloads, on every page. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job } from "../api";

export function duration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "";
  if (sec < 60) return "under a minute";
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  if (h === 0) return `${m} min`;
  return `${h} h ${m.toString().padStart(2, "0")} min`;
}

export function elapsed(since?: string, until?: string | null) {
  if (!since) return 0;
  return Math.max(0, ((until ? new Date(until).getTime() : Date.now()) - new Date(since).getTime()) / 1000);
}

/** Polls the current job: every 4 seconds while one runs, otherwise every 30. */
export function useJob() {
  const [job, setJob] = useState<Job | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    api.jobCurrent().then((j) => live && setJob(j)).catch(() => {});
    const t = setTimeout(() => setTick((x) => x + 1), job?.running ? 4000 : 30000);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);
  return { job, refresh: () => setTick((x) => x + 1) };
}

export default function JobBar() {
  const { job } = useJob();
  if (!job) return null;
  const recent = job.finished_at && Date.now() - new Date(job.finished_at).getTime() < 10 * 60 * 1000;
  if (!job.running && !recent) return null;
  const pct = Number(job.pct ?? 0);
  if (!job.running) {
    const ok = job.status === "done" && !job.error;
    return (
      <Link to="/import" className={`jobbar ${ok ? "ok" : "bad"}`}>
        {ok ? "Data refresh finished" : job.status === "cancelled" ? "Data refresh stopped" : "Data refresh finished with problems"}
        <span className="faint">· details</span>
      </Link>
    );
  }
  return (
    <Link to="/import" className="jobbar" title={job.detail ?? ""}>
      <span className="jb-text">
        <b>{job.stage ?? "Starting"}</b>
        <span className="faint"> · step {(job.stage_index ?? 0) + 1} of {job.stage_total}</span>
      </span>
      <span className="jb-track"><i style={{ width: `${Math.max(pct, 2)}%` }} /></span>
      <span className="jb-pct">{Math.round(pct)}%</span>
      <span className="faint jb-eta">{job.eta_seconds ? `about ${duration(job.eta_seconds)} left` : "working out time left…"}</span>
    </Link>
  );
}
