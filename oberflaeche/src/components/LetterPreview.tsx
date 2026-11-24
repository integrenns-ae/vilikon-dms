import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { Download, FileText } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Dialog } from "@/components/ui/dialog";
import { buttonVariants } from "@/components/ui/button-variants";
import { istVorschau } from "@/lib/api";
import { cn } from "@/lib/utils";
import { T } from "@/texte";

/** True once the element came near the screen: only the letters somebody scrolls to are loaded. */
function useSeen<E extends Element>(): [React.RefObject<E | null>, boolean] {
  const ref = useRef<E>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (seen || !ref.current) return;
    const o = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && setSeen(true), { rootMargin: "200px" });
    o.observe(ref.current);
    return () => o.disconnect();
  }, [seen]);
  return [ref, seen];
}

/** The original of a letter, loaded once and kept as an object URL; `type` is what the server calls it. */
function useOriginal(href: string, wanted: boolean): { url?: string; type: string; failed: boolean } {
  const [state, setState] = useState<{ url?: string; type: string; failed: boolean }>({ type: "", failed: false });
  useEffect(() => {
    if (!wanted || istVorschau) return;  // the example data has no originals
    let gone = false;
    let url: string | undefined;
    fetch(href)
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const blob = await r.blob();
        if (gone) return;
        url = URL.createObjectURL(blob);
        setState({ url, type: blob.type, failed: false });
      })
      .catch(() => { if (!gone) setState({ type: "", failed: true }); });
    return () => {
      gone = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [href, wanted]);
  return state;
}

// pdf.js, loaded only when the first PDF shows up
let pdfjs: Promise<typeof import("pdfjs-dist")> | undefined;
function loadPdfjs() {
  pdfjs ??= Promise.all([import("pdfjs-dist"), import("pdfjs-dist/build/pdf.worker.min.mjs?url")]).then(([lib, worker]) => {
    lib.GlobalWorkerOptions.workerSrc = worker.default;
    return lib;
  });
  return pdfjs;
}

function usePdf(src: string | undefined): { doc?: PDFDocumentProxy; failed: boolean } {
  const [state, setState] = useState<{ src?: string; doc?: PDFDocumentProxy; failed: boolean }>({ failed: false });
  useEffect(() => {
    if (!src) return;
    let gone = false;
    let stop: (() => void) | undefined;
    loadPdfjs().then((lib) => {
      if (gone) return;
      const task = lib.getDocument({ url: src });
      stop = () => void task.destroy();
      return task.promise.then((doc) => { if (!gone) setState({ src, doc, failed: false }); });
    }).catch(() => { if (!gone) setState({ src, failed: true }); });
    return () => {
      gone = true;
      stop?.();
    };
  }, [src]);
  return state.src === src ? state : { failed: false };
}

/** One page of a PDF, drawn `width` CSS pixels wide once it comes near the screen. */
function PdfPage({ doc, nr, width, className, onFailed }: { doc: PDFDocumentProxy; nr: number; width: number; className?: string; onFailed?: () => void }) {
  const [canvas, seen] = useSeen<HTMLCanvasElement>();
  const failed = useRef(onFailed);
  useEffect(() => {
    failed.current = onFailed;
  });
  useEffect(() => {
    if (!seen) return;
    let gone = false;
    let cancel: (() => void) | undefined;
    doc.getPage(nr).then((page) => {
      if (gone || !canvas.current) return;
      const viewport = page.getViewport({ scale: (width / page.getViewport({ scale: 1 }).width) * Math.min(window.devicePixelRatio || 1, 2) });
      canvas.current.width = viewport.width;
      canvas.current.height = viewport.height;
      const task = page.render({ canvas: canvas.current, viewport });
      cancel = () => task.cancel();
      return task.promise;
    }).catch(() => { if (!gone) failed.current?.(); });
    return () => {
      gone = true;
      cancel?.();
    };
  }, [doc, nr, width, seen, canvas]);
  // A4 until the page is drawn, so the pages below do not all count as "on screen" at once
  return <canvas ref={canvas} className={cn("bg-white", className)} style={{ aspectRatio: seen ? undefined : "1 / 1.414" }} />;
}

const symbol = <FileText className="m-auto h-5 w-5 text-label" />;

function PdfThumb({ src }: { src: string }) {
  const { doc, failed } = usePdf(src);
  const [broken, setBroken] = useState(false);
  if (!doc || failed || broken) return symbol;
  return <PdfPage doc={doc} nr={1} width={88} className="w-full" onFailed={() => setBroken(true)} />;
}

const MAX_PAGES = 30;

function PdfView({ src }: { src: string }) {
  const { doc, failed } = usePdf(src);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (box.current) setWidth(Math.min(box.current.clientWidth - 24, 900));
  }, []);
  return (
    <div ref={box} className="min-h-40 rounded-[var(--radius)] bg-muted px-3 py-3">
      {failed ? <Alert tone="warning">{T.mail.previewFailed}</Alert> : doc && width > 0 && (
        <div className="flex flex-col items-center gap-3">
          {Array.from({ length: Math.min(doc.numPages, MAX_PAGES) }, (_, i) => (
            <div key={i} style={{ width }}><PdfPage doc={doc} nr={i + 1} width={width} className="w-full shadow" /></div>
          ))}
          {doc.numPages > MAX_PAGES && <p className="text-xs text-muted-foreground">{T.mail.previewMorePages(MAX_PAGES, doc.numPages)}</p>}
        </div>
      )}
    </div>
  );
}

/**
 * A letter's original as a small picture (a PDF's first page, or the photo); a click shows the whole letter large in
 * a dialog, with a download. `href` is the page's own file route, `name` what the dialog and the download call it.
 */
export function LetterPreview({ href, name, className }: { href: string; name: string; className?: string }) {
  const [box, seen] = useSeen<HTMLButtonElement>();
  const [open, setOpen] = useState(false);
  const [broken, setBroken] = useState(false);
  const { url, type, failed } = useOriginal(href, seen);
  const pdf = type === "application/pdf";
  const image = type.startsWith("image/") && !broken;
  return (
    <>
      <button ref={box} type="button" title={T.mail.preview(name)} aria-label={T.mail.preview(name)}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className={cn("flex h-14 w-11 shrink-0 items-start overflow-hidden rounded border border-border bg-muted hover:border-primary", className)}>
        {url && image ? <img src={url} alt="" onError={() => setBroken(true)} className="h-full w-full object-cover" />
          : url && pdf ? <PdfThumb src={url} />
          : symbol}
      </button>
      {/* the dialog sits inside the table row in React's tree: its clicks must not count as a click on the row */}
      <span onClick={(e) => e.stopPropagation()}>
        <Dialog offen={open} schliessen={() => setOpen(false)} titel={name} className="max-w-4xl">
        {/* only while open: a closed dialog draws nothing, so its pages would never count as seen */}
        {open && (
          <div className="space-y-3">
            {url && (
              <a href={url} download={`${name}${pdf ? ".pdf" : type.startsWith("image/") ? `.${type.split("/")[1]}` : ""}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                <Download className="h-4 w-4" /> {T.mail.download}
              </a>
            )}
            {failed || istVorschau || (url && !pdf && !image) ? <Alert tone="warning">{istVorschau ? T.mail.previewExample : T.mail.previewFailed}</Alert>
              : !url ? <p className="text-sm text-muted-foreground">{T.mail.previewLoading}</p>
              : pdf ? <PdfView src={url} />
              : <img src={url} alt={name} onError={() => setBroken(true)} className="mx-auto max-h-[75vh] max-w-full object-contain" />}
          </div>
        )}
      </Dialog>
      </span>
    </>
  );
}
