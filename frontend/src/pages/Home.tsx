import { duration } from "../api/jobs";
import { useLive } from "../api/live";
import { Link } from "../app/navigation";
import { ClusterStrip } from "../components/ClusterStrip";
import { JobCard } from "../components/JobCard";
import { Panel } from "../components/Panel";

/** The dashboard: the cluster now, my jobs, and who else is running. */
export function Home() {
  const { cluster, jobs, banners } = useLive();
  const running = (cluster?.queue ?? []).filter((j) => j.state === "RUNNING");
  return (
    <div className="space-y-6">
      {cluster?.maintenance && (
        <p role="status" className="rounded-sm border border-warning p-3 text-warning">
          {cluster.maintenance}
        </p>
      )}
      {banners.map((b) => (
        <p key={b.job_id} role="alert" className="rounded-sm border border-warning p-3 text-warning">
          Job {b.job_id} ends in {b.minutes_left ?? "a few"} minutes. Extend it from its card.
        </p>
      ))}
      <Panel title="Cluster">
        <ClusterStrip cluster={cluster} />
      </Panel>
      <Panel title="My jobs">
        {jobs === null ? <p className="text-sm text-text-dim">Loading…</p>
          : jobs.length === 0 ? (
            <p className="text-sm text-text-dim">
              No jobs running. <Link href="/new" className="text-accent">Start one</Link>.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {jobs.map((j) => <JobCard key={j.job_id} job={j} />)}
            </div>
          )}
      </Panel>
      <Panel title="Who's running">
        {running.length === 0 ? <p className="text-sm text-text-dim">Nobody right now.</p> : (
          <ul className="space-y-1 font-mono text-sm">
            {running.map((j) => (
              <li key={j.job_id}>
                {j.user} · {j.pods} pod{j.pods === 1 ? "" : "s"} · {duration(j.time_left_s)} left
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
