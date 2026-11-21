import { useRef, useState } from "react";
import { Camera, CheckCircle2, Inbox, Loader2, Lock, TriangleAlert } from "lucide-react";
import { Seitenkopf } from "@/components/AppShell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Leer } from "@/components/ui/leer";
import { ZeilenSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useDaten } from "@/lib/daten";
import type { Letter, Mail, Uploaded } from "@/lib/typen";
import { tag, zahl } from "@/lib/utils";
import { T } from "@/texte";
import { FileStores } from "./FileStores";
import { StatusBadge } from "./status";

type View = "review" | "inbox";

/** The mail: upload from the phone, the letters to check and the inbox; for the owner also the file stores. */
export function MailPage() {
  const { daten, laedt, fehler, neuLaden } = useDaten<Mail>("api/documents");
  const [view, setView] = useState<View | null>(null);
  const [reading, setReading] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const review = daten?.review ?? [];
  const inbox = daten?.documents ?? [];
  const shown: View = view ?? (review.length ? "review" : "inbox");
  const rows = shown === "review" ? review : inbox;

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const body = new FormData();
    for (const f of Array.from(files)) body.append("files", f);
    setReading(true);
    try {
      const r = await api<Uploaded>("api/upload", { method: "POST", body });
      toast(r.text, r.status === "error" ? "fehler" : "ok");
      neuLaden();
    } catch (e) {
      toast((e as Error).message || T.fehlerAllgemein, "fehler");
    } finally {
      setReading(false);
      if (picker.current) picker.current.value = "";
    }
  }

  const uploadButton = (
    <Button onClick={() => picker.current?.click()} disabled={reading}>
      {reading ? <Loader2 className="h-4 w-4 motion-safe:animate-spin" /> : <Camera className="h-4 w-4" />}
      {reading ? T.mail.reading : T.mail.upload}
    </Button>
  );

  return (
    <div className="space-y-4">
      <input ref={picker} type="file" accept="image/*,application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
      <Seitenkopf titel={T.mail.title} text={T.mail.text} aktion={uploadButton} />
      {reading && <Alert>{T.mail.readingText}</Alert>}
      {fehler && <Alert tone="error">{fehler}</Alert>}
      {laedt ? (
        <ZeilenSkeleton />
      ) : (
        daten && (
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Tabs
                wert={shown}
                setWert={setView}
                optionen={[
                  { wert: "review", label: T.mail.review, anzahl: review.length },
                  { wert: "inbox", label: T.mail.inbox, anzahl: inbox.length },
                ]}
              />
              <p className="text-xs text-muted-foreground sm:ml-auto">
                {T.mail.pages(zahl(daten.pages.pages), daten.pages.cap ? zahl(daten.pages.cap) : null)}
                {daten.pages.waiting > 0 && ` · ${T.mail.waiting(daten.pages.waiting)}`}
              </p>
            </div>
            {rows.length > 0 ? (
              <Letters rows={rows} />
            ) : shown === "review" ? (
              <Leer icon={CheckCircle2} titel={T.mail.reviewEmptyTitle} text={T.mail.reviewEmptyText} />
            ) : (
              <Leer icon={Inbox} titel={T.mail.inboxEmptyTitle} text={T.mail.inboxEmptyText} aktion={uploadButton} />
            )}
            {daten.owner && <FileStores stores={daten.sources} reload={neuLaden} />}
          </>
        )
      )}
    </div>
  );
}

/** One row per letter; the whole row opens the original in a new tab. */
function Letters({ rows }: { rows: Letter[] }) {
  return (
    <Card>
      <Table>
        <THead>
          <TR>
            <TH className="hidden sm:table-cell">{T.mail.columns.date}</TH>
            <TH>{T.mail.columns.letter}</TH>
            <TH className="hidden md:table-cell">{T.mail.columns.kind}</TH>
            <TH>{T.mail.columns.status}</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((l) => {
            const href = `api/documents/${encodeURIComponent(l.id)}/file`;
            const meta = [l.subject ? l.sender : null, l.file_number ? T.mail.fileNumber(l.file_number) : null].filter(Boolean);
            return (
              <TR key={l.id} onClick={() => window.open(href, "_blank", "noopener")}>
                <TD className="hidden whitespace-nowrap align-top text-muted-foreground sm:table-cell">{tag(l.date)}</TD>
                <TD className="align-top">
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    title={T.mail.open}
                    className="font-medium hover:text-primary"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {l.subject || l.title}
                  </a>
                  {l.confidential && <Lock aria-label={T.mail.confidential} className="ml-1.5 inline h-3.5 w-3.5 text-warning-foreground md:hidden" />}
                  <div className="text-xs text-muted-foreground">
                    <span className="sm:hidden">
                      {tag(l.date)}
                      {meta.length > 0 && " · "}
                    </span>
                    {meta.join(" · ")}
                  </div>
                  {l.reason && (
                    <div className="mt-1 flex items-start gap-1.5 text-xs text-muted-foreground">
                      <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0 text-warning" />
                      <span>{l.reason}</span>
                    </div>
                  )}
                </TD>
                <TD className="hidden align-top md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {l.kind_text && <Badge>{l.kind_text}</Badge>}
                    {l.confidential && (
                      <Badge tone="warning">
                        <Lock className="mr-1 h-3 w-3" />
                        {T.mail.confidential}
                      </Badge>
                    )}
                  </div>
                </TD>
                <TD className="align-top">
                  <StatusBadge status={l.status} />
                </TD>
              </TR>
            );
          })}
        </TBody>
      </Table>
    </Card>
  );
}
