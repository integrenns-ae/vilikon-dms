import { Badge } from "@/components/ui/badge";
import type { Status } from "@/lib/typen";
import { T } from "@/texte";

const TONE: Record<Status, string> = { new: "running", waiting: "pending", done: "ok", review: "warning", error: "failed" };

export function StatusBadge({ status }: { status: Status }) {
  return <Badge tone={TONE[status]}>{T.status[status]}</Badge>;
}
