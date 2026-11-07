import { StrictMode, useEffect, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "@/components/ui/sonner";
import { App } from "./App";
import { AuthGate } from "./Auth";
import { UnsavedChangesProvider } from "./UnsavedChanges";

function SystemTheme({ children }: { children: ReactNode }) {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      document.documentElement.classList.toggle("dark", media.matches);
      document.documentElement.style.colorScheme = media.matches
        ? "dark"
        : "light";
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", media.matches ? "#0a0a0a" : "#ffffff");
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return children;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SystemTheme>
      <AuthGate>
        <UnsavedChangesProvider><App /></UnsavedChangesProvider>
      </AuthGate>
      <Toaster position="bottom-right" />
    </SystemTheme>
  </StrictMode>,
);
