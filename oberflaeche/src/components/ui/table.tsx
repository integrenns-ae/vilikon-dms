import * as React from "react";
import { cn } from "@/lib/utils";

/** A list in rows: sits inside a Card (or alone), scrolls sideways on small screens instead of breaking. */
export function Table({ className, ...p }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)} {...p} />
    </div>
  );
}

export function THead({ className, ...p }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("text-left text-xs font-medium text-muted-foreground", className)} {...p} />;
}

export function TBody(p: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...p} />;
}

/** `onClick` makes the whole row a target (pointer, hover); keep a real button/link inside for keyboards. */
export function TR({ className, onClick, ...p }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      onClick={onClick}
      className={cn("border-b border-border last:border-0", onClick && "cursor-pointer transition-colors hover:bg-muted/60", className)}
      {...p}
    />
  );
}

export function TH({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("whitespace-nowrap px-3 py-2 font-medium", className)} {...p} />;
}

export function TD({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-2.5 align-middle", className)} {...p} />;
}
