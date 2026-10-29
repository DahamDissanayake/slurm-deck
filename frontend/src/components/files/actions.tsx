import type { ReactNode } from "react";

import { ARCHIVE, type Entry } from "../../api/files";
import { DownloadIcon, EditIcon, FileArchiveIcon, FolderIcon, MoveIcon, TrashIcon } from "../icons";

export const EDIT_MAX = 1024 * 1024;

export type FileAction = {
  id: "open" | "download" | "edit" | "rename" | "move" | "extract" | "delete";
  label: string; icon: ReactNode; danger?: boolean;
};
export type FileHandlers = Record<FileAction["id"], () => void>;

/** What can be done with `selected`, in the order the selection bar and the
 * context menu list it. Write actions only exist in a writable area. */
export function actionsFor(selected: Entry[], writable: boolean): FileAction[] {
  if (selected.length === 0) return [];
  const one = selected.length === 1 ? selected[0] : null;
  const allFiles = selected.every((e) => e.type !== "dir");
  const out: FileAction[] = [];
  if (one?.type === "dir") out.push({ id: "open", label: "Open", icon: <FolderIcon /> });
  if (allFiles) out.push({ id: "download", label: "Download", icon: <DownloadIcon /> });
  if (writable) {
    if (one && one.type === "file" && one.size <= EDIT_MAX) out.push({ id: "edit", label: "Edit", icon: <EditIcon /> });
    if (one) out.push({ id: "rename", label: "Rename", icon: <EditIcon /> });
    out.push({ id: "move", label: "Move", icon: <MoveIcon /> });
    if (selected.every((e) => e.type === "file" && ARCHIVE.test(e.name))) {
      out.push({ id: "extract", label: "Extract", icon: <FileArchiveIcon /> });
    }
    out.push({ id: "delete", label: "Delete", icon: <TrashIcon />, danger: true });
  }
  return out;
}
