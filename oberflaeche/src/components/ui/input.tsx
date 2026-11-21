import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "flex h-9 w-full rounded-lg border border-border bg-card px-3 py-1 text-sm placeholder:text-muted-foreground/70 focus-visible:border-signal/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal/30 disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-[80px] w-full rounded-lg border border-border bg-card px-3 py-2 text-sm placeholder:text-muted-foreground/70 focus-visible:border-signal/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal/30 disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1 block text-sm font-semibold", className)} {...p} />;
}

export function Select({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("h-9 rounded-lg border border-border bg-card px-2 text-sm focus-visible:border-signal/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal/30 dark:[&_option]:bg-[#0c1e48]", className)}
      {...p}
    />
  );
}
