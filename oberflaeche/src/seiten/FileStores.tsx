import { useState } from "react";
import { HardDrive, KeyRound, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { FileStore } from "@/lib/typen";
import { zeitpunkt } from "@/lib/utils";
import { T } from "@/texte";

/** The owner's view of the scanner folders: does each answer, when was it fetched, "Fetch now", a changed key. */
export function FileStores({ stores, reload }: { stores: FileStore[]; reload: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function post(path: string) {
    setBusy(true);
    try {
      const r = await api<{ text: string }>(path, { method: "POST" });
      toast(r.text);
      setTimeout(reload, 3000); // the pass runs in the background
    } catch (e) {
      toast((e as Error).message || T.fehlerAllgemein, "fehler");
    } finally {
      setBusy(false);
    }
  }

  const fetchNow = stores.length > 0 && (
    <Button size="sm" variant="outline" disabled={busy} onClick={() => post("api/sync")}>
      <RefreshCw className="h-4 w-4" /> {T.stores.fetch}
    </Button>
  );

  return (
    <Card tone="einstellungen">
      <CardHeader>
        <CardTitle icon={HardDrive} aktion={fetchNow}>
          {T.stores.title}
        </CardTitle>
        <CardDescription>{T.stores.text}</CardDescription>
      </CardHeader>
      <CardContent>
        {stores.length === 0 ? (
          <div className="space-y-1">
            <p className="text-sm">{T.stores.none}</p>
            <p className="text-xs text-muted-foreground">{T.stores.noneHelp}</p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {stores.map((s) => (
              <li key={s.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{s.id.toUpperCase()}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.protocol.toUpperCase()} · {s.host}
                    </div>
                  </div>
                  <div className="ml-auto">
                    <StoreBadge store={s} />
                  </div>
                </div>
                {s.error && !s.host_key_new && <p className="text-xs text-destructive">{s.error}</p>}
                {s.host_key_new && (
                  <div className="space-y-2 rounded-[var(--radius)] bg-warning/10 p-3">
                    <p className="text-xs">{T.stores.acceptText}</p>
                    <p className="break-all font-mono text-xs text-muted-foreground">{s.host_key_new}</p>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => post(`api/sources/${encodeURIComponent(s.id)}/trust`)}>
                      <KeyRound className="h-4 w-4" /> {T.stores.accept}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function StoreBadge({ store: s }: { store: FileStore }) {
  if (s.host_key_new) return <Badge tone="warning">{T.stores.newKey}</Badge>;
  if (s.error) return <Badge tone="failed">{T.stores.failed}</Badge>;
  if (!s.last_fetch) return <Badge tone="pending">{T.stores.neverFetched}</Badge>;
  return <Badge tone="ok">{T.stores.lastFetch(zeitpunkt(s.last_fetch))}</Badge>;
}
