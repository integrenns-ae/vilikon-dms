import { AppShell } from "@/components/AppShell";
import { ToastProvider } from "@/components/ui/toast";
import { MailPage } from "@/seiten/Mail";

/** One page: the mail. Inside the cockpit the shell shows no navigation of its own. */
export function App() {
  return (
    <ToastProvider>
      <AppShell nav={[]} aktiv="">
        <MailPage />
      </AppShell>
    </ToastProvider>
  );
}
