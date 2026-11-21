/** What the DMS server answers on `api/documents` (app/main.py: page_documents). */
export type Status = "new" | "waiting" | "done" | "review" | "error";

export interface Letter {
  id: string;
  kind: string | null;
  kind_text: string;
  sender: string | null;
  subject: string | null;
  title: string;
  date: string;
  file_number: string | null;
  status: Status;
  reason: string;
  confidential: boolean;
}

export interface FileStore {
  id: string;
  protocol: string;
  host: string;
  error: string;
  last_fetch: string | null;
  host_key_new: string;
}

export interface Pages {
  month: string;
  pages: number;
  cap: number | null;
  own_key: boolean;
  waiting: number;
}

export interface Mail {
  review: Letter[];
  documents: Letter[];
  pages: Pages;
  owner: boolean;
  sources: FileStore[];
}

export interface Uploaded {
  id: string;
  duplicate: boolean;
  status: Status;
  text: string;
}
