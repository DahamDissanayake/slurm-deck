import type { ReactNode } from "react";

export const iconButton =
  "inline-flex h-8 w-8 items-center justify-center rounded-sm border border-border text-text-dim " +
  "hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

function Icon({ className = "h-5 w-5", children }: { className?: string; children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      {children}
    </svg>
  );
}

type Props = { className?: string };

export const SunIcon = (p: Props) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);
export const MoonIcon = (p: Props) => (
  <Icon {...p}><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /></Icon>
);
export const KeyIcon = (p: Props) => (
  <Icon {...p}><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M16 7l3 3" /></Icon>
);
export const SignOutIcon = (p: Props) => (
  <Icon {...p}><path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9" /></Icon>
);

// Navigation
export const DashboardIcon = (p: Props) => (
  <Icon {...p}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></Icon>
);
export const PlusIcon = (p: Props) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>;
export const JobsIcon = (p: Props) => (
  <Icon {...p}><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></Icon>
);
export const FolderIcon = (p: Props) => (
  <Icon {...p}><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z" /></Icon>
);
export const EnvIcon = (p: Props) => (
  <Icon {...p}><path d="M12 2l9 5v10l-9 5-9-5V7z" /><path d="M3 7l9 5 9-5M12 12v10" /></Icon>
);
export const ModelIcon = (p: Props) => (
  <Icon {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="12" cy="18" r="2.5" />
    <path d="M8 7.5l3 8.5M16 7.5l-3 8.5M8.5 6h7" /></Icon>
);
export const ServerIcon = (p: Props) => (
  <Icon {...p}><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" />
    <path d="M7 7.5h.01M7 16.5h.01" /></Icon>
);
export const ChartIcon = (p: Props) => <Icon {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>;
export const BellIcon = (p: Props) => (
  <Icon {...p}><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" /><path d="M10 21h4" /></Icon>
);
export const ShieldIcon = (p: Props) => <Icon {...p}><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" /></Icon>;
export const MenuIcon = (p: Props) => <Icon {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Icon>;
export const ChevronDownIcon = (p: Props) => <Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>;
export const ChevronRightIcon = (p: Props) => <Icon {...p}><path d="M9 6l6 6-6 6" /></Icon>;

// States
export const CheckIcon = (p: Props) => <Icon {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>;
export const XIcon = (p: Props) => <Icon {...p}><path d="M6 6l12 12M18 6L6 18" /></Icon>;
export const ClockIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
export const PlayIcon = (p: Props) => <Icon {...p}><path d="M7 5l12 7-12 7z" /></Icon>;
export const PauseIcon = (p: Props) => <Icon {...p}><path d="M8 5v14M16 5v14" /></Icon>;
export const StopIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M8 12h8" /></Icon>;
export const AlertIcon = (p: Props) => (
  <Icon {...p}><path d="M12 3l10 18H2z" /><path d="M12 10v4M12 17.5h.01" /></Icon>
);
export const InfoIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 7.5h.01" /></Icon>;
export const DotIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="4" fill="currentColor" /></Icon>;

// Actions
export const RefreshIcon = (p: Props) => (
  <Icon {...p}><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4" /></Icon>
);
export const MoreIcon = (p: Props) => <Icon {...p}><path d="M5 12h.01M12 12h.01M19 12h.01" strokeWidth={3} /></Icon>;
export const UploadIcon = (p: Props) => <Icon {...p}><path d="M12 15V3M7 8l5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></Icon>;
export const DownloadIcon = (p: Props) => <Icon {...p}><path d="M12 3v12M7 10l5 5 5-5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></Icon>;
export const TrashIcon = (p: Props) => (
  <Icon {...p}><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" /></Icon>
);
export const SearchIcon = (p: Props) => <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></Icon>;
export const GridIcon = (p: Props) => (
  <Icon {...p}><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" />
    <rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></Icon>
);
export const ListIcon = (p: Props) => <Icon {...p}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></Icon>;
export const EditIcon = (p: Props) => <Icon {...p}><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></Icon>;
export const ExternalIcon = (p: Props) => <Icon {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" /></Icon>;
export const TerminalIcon = (p: Props) => (
  <Icon {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M12 15h5" /></Icon>
);
export const GpuIcon = (p: Props) => (
  <Icon {...p}><rect x="6" y="6" width="12" height="12" rx="1.5" /><rect x="9.5" y="9.5" width="5" height="5" />
    <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></Icon>
);
export const MemoryIcon = (p: Props) => (
  <Icon {...p}><rect x="2" y="7" width="20" height="10" rx="1.5" /><path d="M6 10v4M10 10v4M14 10v4M18 10v4M6 17v3M18 17v3" /></Icon>
);
export const ThermometerIcon = (p: Props) => (
  <Icon {...p}><path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z" /></Icon>
);
export const BoltIcon = (p: Props) => <Icon {...p}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></Icon>;

// File types
const Page = ({ className, children }: Props & { children?: ReactNode }) => (
  <Icon className={className}><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z" />
    <path d="M14 3v5h5" />{children}</Icon>
);
export const FileIcon = (p: Props) => <Page {...p} />;
export const FileTextIcon = (p: Props) => <Page {...p}><path d="M8.5 13h7M8.5 16.5h5" /></Page>;
export const FileCodeIcon = (p: Props) => <Page {...p}><path d="M10 12l-2 2.5 2 2.5M14 12l2 2.5-2 2.5" /></Page>;
export const FileImageIcon = (p: Props) => <Page {...p}><circle cx="10" cy="12" r="1.5" /><path d="M7 18l3.5-3 2.5 2 2-1.5 2 2.5" /></Page>;
export const FileArchiveIcon = (p: Props) => <Page {...p}><path d="M10 4v2M10 8v2M10 12v2M9 16h2v2H9z" /></Page>;
export const FileDataIcon = (p: Props) => <Page {...p}><path d="M8 12h8M8 15h8M8 18h8M11 12v6" /></Page>;

const EXT: [RegExp, (p: Props) => JSX.Element][] = [
  [/\.(py|ipynb|sh|js|ts|tsx|c|cpp|h|cu|r|jl|go|rs|java)$/i, FileCodeIcon],
  [/\.(png|jpe?g|gif|svg|webp|bmp|tiff?)$/i, FileImageIcon],
  [/\.(zip|tar|gz|tgz|bz2|xz|7z|rar)$/i, FileArchiveIcon],
  [/\.(csv|tsv|json|ya?ml|parquet|h5|hdf5|npy|npz|pt|pth|ckpt|safetensors)$/i, FileDataIcon],
  [/\.(txt|md|log|out|err|rst|toml|cfg|ini)$/i, FileTextIcon],
];

/** The icon for a file name, by extension; folders get the folder icon. */
export function fileIcon(name: string, isDir = false): (p: Props) => JSX.Element {
  if (isDir) return FolderIcon;
  return EXT.find(([re]) => re.test(name))?.[1] ?? FileIcon;
}
