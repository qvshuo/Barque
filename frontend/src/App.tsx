import { useEffect, useRef, useState } from "react";
import { LogOut } from "lucide-react";
import { api } from "./api";
import { SettingsPage } from "./Settings";
import { SubscriptionsPage } from "./Subscriptions";
import { SubscriptionManager } from "./SubscriptionManager";
import { useNavigationGuard } from "./UnsavedChanges";
import { Button } from "@/components/ui/button";

type Section = "home" | "subscriptions" | "settings";
const navigation: { section: Section; label: string; href: string }[] = [
  { section: "home", label: "首页", href: "/" },
  { section: "subscriptions", label: "管理订阅", href: "#subscriptions" },
  { section: "settings", label: "设置", href: "#settings" },
];

function readSection(): Section {
  if (location.hash === "#settings") return "settings";
  if (location.hash === "#subscriptions" || location.pathname.replace(/\/$/, "") === "/admin")
    return "subscriptions";
  return "home";
}

export function App() {
  const [section, setSection] = useState<Section>(readSection);
  const { requestLeave } = useNavigationGuard();
  const acceptedHash = useRef(section === "home" ? "" : `#${section}`);

  useEffect(() => {
    if (location.pathname.replace(/\/$/, "") === "/admin") {
      history.replaceState(null, "", "/" + location.search + acceptedHash.current);
    }
    const update = () => {
      const next =
        location.hash === "#settings" || location.hash === "#subscriptions" ? location.hash : "";
      const url = (hash: string) => location.pathname + location.search + hash;
      if (next === acceptedHash.current) {
        if (location.hash !== next) history.replaceState(null, "", url(next));
        return;
      }
      history.replaceState(null, "", url(acceptedHash.current));
      requestLeave(() => {
        acceptedHash.current = next;
        history.replaceState(null, "", url(next));
        setSection(
          next === "#settings" ? "settings" : next === "#subscriptions" ? "subscriptions" : "home",
        );
      });
    };
    update();
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, [requestLeave]);

  function navigate(href: string) {
    requestLeave(() => {
      location.hash = href === "/" ? "" : href;
    });
  }

  return (
    <>
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4 sm:gap-6 sm:px-6">
          <a
            href="/"
            aria-label="Barque 首页"
            onClick={(event) => {
              event.preventDefault();
              if (section !== "home") navigate("/");
            }}
            className="flex shrink-0 items-center gap-2 font-medium"
          >
            <img src="/logo.png?v=3" alt="" className="size-8 object-contain" />
            <span className="hidden max-w-40 truncate sm:inline">Barque</span>
          </a>
          <nav aria-label="主导航" className="ml-auto flex items-center gap-1">
            {navigation.map((item) => (
              <Button
                key={item.section}
                variant={section === item.section ? "secondary" : "ghost"}
                size="sm"
                nativeButton={false}
                role="link"
                render={
                  <a
                    href={item.href}
                    aria-current={section === item.section ? "page" : undefined}
                    onClick={(event) => {
                      event.preventDefault();
                      if (section !== item.section) navigate(item.href);
                    }}
                  />
                }
              >
                {item.label}
              </Button>
            ))}
          </nav>
          <Button
            variant="ghost"
            size="icon"
            aria-label="退出登录"
            onClick={() =>
              requestLeave(async () => {
                await api("/auth/logout", "POST");
                window.dispatchEvent(new Event("barque:unauthorized"));
              })
            }
          >
            <LogOut />
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6 sm:py-10">
        {section === "settings" ? (
          <SettingsPage />
        ) : section === "subscriptions" ? (
          <SubscriptionManager />
        ) : (
          <SubscriptionsPage />
        )}
      </main>
    </>
  );
}
