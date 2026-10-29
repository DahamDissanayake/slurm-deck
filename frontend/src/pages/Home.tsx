import { useEffect } from "react";

import { useLive } from "../api/live";
import { Link, useLocation } from "../app/navigation";
import { ClusterCard, ClusterTiles, HardwareCard, useStatus } from "../components/ClusterCards";
import { FolderIcon, JobsIcon, PlusIcon, ServerIcon } from "../components/icons";
import { JobCard } from "../components/JobCard";
import { buttonClass } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { cx } from "../components/ui/cx";
import { EmptyState } from "../components/ui/EmptyState";
import { Notice } from "../components/ui/Notice";
import { Skeleton } from "../components/ui/Skeleton";

const QUICK = [
  { href: "/new", label: "New job", icon: <PlusIcon />, variant: "primary" },
  { href: "/files", label: "Upload files", icon: <FolderIcon />, variant: "secondary" },
  { href: "/services", label: "Notebooks and services", icon: <ServerIcon />, variant: "secondary" },
] as const;

/** The dashboard: the cluster now, my jobs, and who else is running. */
export function Home() {
  const { cluster, jobs, banners } = useLive();
  const status = useStatus();
  const { hash } = useLocation();

  // /usage/hardware and /usage/cluster land on their section of this page.
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [hash]);

  return (
    <div className="space-y-6">
      {cluster?.maintenance && <Notice>{cluster.maintenance}</Notice>}
      <ClusterTiles cluster={cluster} />
      <nav aria-label="Quick actions" className="flex flex-wrap gap-2">
        {QUICK.map(({ href, label, icon, variant }) => (
          <Link key={href} href={href}
                className={cx(buttonClass({ variant, size: "md", pill: true }), "gap-2 [&>svg]:h-4 [&>svg]:w-4")}>
            {icon}{label}
          </Link>
        ))}
      </nav>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="My jobs" icon={<JobsIcon />}>
            {banners.length > 0 && (
              <div className="mb-4 space-y-2">
                {banners.map((b) => (
                  <Notice key={b.job_id} alert>
                    Job {b.job_id} ends in {b.minutes_left ?? "a few"} minutes. Extend it from its card.
                  </Notice>
                ))}
              </div>
            )}
            {jobs === null ? <Skeleton variant="row" count={3} label="Loading your jobs" />
              : jobs.length === 0 ? (
                <EmptyState icon={<JobsIcon />} title="No jobs yet"
                            action={<Link href="/new" className={buttonClass({ size: "md", pill: true })}>Start a job</Link>}>
                  Jobs you start show up here with their time left.
                </EmptyState>
              ) : (
                <div className="grid gap-3 md:grid-cols-2">
                  {jobs.map((j) => <JobCard key={j.job_id} job={j} />)}
                </div>
              )}
          </Card>
        </div>
        <div className="space-y-6">
          <div id="hardware" className="scroll-mt-20"><HardwareCard status={status} /></div>
          <div id="cluster" className="scroll-mt-20"><ClusterCard status={status} cluster={cluster} /></div>
        </div>
      </div>
    </div>
  );
}
