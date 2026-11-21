import * as React from "react";
import { HelpCircle } from "lucide-react";
import { Tipp } from "@/components/ui/tipp";
import { cn } from "@/lib/utils";

/** The screen-reader name of the „?“ – the cockpit sets it in its language (Layout); apps keep the default. */
export const HilfeLabelContext = React.createContext("?");

/** The „?“ behind which explanations wait – the page stays calm, the owner reads them when he wants. */
export function Hilfe({ children, className }: { children: React.ReactNode; className?: string }) {
  const label = React.useContext(HilfeLabelContext);
  return (
    <Tipp label={label} inhalt={children} breit className={cn("align-middle", className)}>
      <HelpCircle className="h-4 w-4" />
    </Tipp>
  );
}
