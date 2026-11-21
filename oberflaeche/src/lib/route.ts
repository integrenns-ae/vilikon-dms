import { useEffect, useState } from "react";

/**
 * A tiny hash router (#/liste, #/neu, #/eintrag/3): works under any prefix, needs no server rules and no
 * library. `gehe("neu")` navigates; `useRoute()` gives the current path without the leading "#/".
 */
function aktuell(): string {
  return location.hash.replace(/^#\/?/, "");
}

export function gehe(pfad: string) {
  location.hash = "/" + pfad.replace(/^\//, "");
}

export function useRoute(): string {
  const [route, setRoute] = useState(aktuell);
  useEffect(() => {
    const neu = () => setRoute(aktuell());
    window.addEventListener("hashchange", neu);
    return () => window.removeEventListener("hashchange", neu);
  }, []);
  return route;
}
