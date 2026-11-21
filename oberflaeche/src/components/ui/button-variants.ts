import { cva } from "class-variance-authority";

/** Shared by <Button> and by links that must look like buttons (a Link inside a Button would nest two
 *  interactive elements). */
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold transition-[background-color,box-shadow,color,filter] active:translate-y-px disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal/50",
  {
    variants: {
      variant: {
        default: "knopf-signal text-knopf-text hover:brightness-110",
        secondary: "bg-accent text-primary hover:bg-primary/15",
        outline: "border border-primary/25 bg-card hover:bg-accent dark:border-white/25",
        ghost: "hover:bg-muted",
        destructive: "bg-destructive text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.3)] hover:bg-destructive/90",
      },
      size: { default: "h-9 px-4", sm: "h-8 px-3 text-xs", lg: "h-10 px-6", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);
