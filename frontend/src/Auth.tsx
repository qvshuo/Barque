import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api } from "./api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type AuthStatus = { authenticated: boolean };

export function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      setStatus(await api<AuthStatus>("/auth/session"));
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }
  useEffect(() => {
    void load();
    const unauthorized = () => {
      setStatus({ authenticated: false });
      setPassword("");
      setError("");
    };
    window.addEventListener("barque:unauthorized", unauthorized);
    return () =>
      window.removeEventListener("barque:unauthorized", unauthorized);
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await api<AuthStatus>(
        "/auth/login",
        "POST",
        { password },
      );
      setPassword("");
      setStatus(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (status && !status.authenticated) {
      document.title = "Barque";
      document.getElementById("access-password")?.focus();
    }
  }, [status]);
  if (status?.authenticated) return children;
  if (!status) return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-8">
      {error && (
        <div className="w-full max-w-xs space-y-3">
          <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>
          <Button type="button" className="w-full" onClick={() => { setError(""); void load(); }}>重试</Button>
        </div>
      )}
    </main>
  );
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-8">
      <form
        className="w-full max-w-xs space-y-3"
        onSubmit={(event) => void submit(event)}
      >
        <Input
          id="access-password"
          name="password"
          type="password"
          aria-label="密码"
          placeholder="密码"
          autoComplete="current-password"
          autoFocus
          required
          disabled={busy}
          maxLength={256}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Button
          type="submit"
          className="w-full"
          disabled={busy}
        >
          {busy ? "登录中…" : "登录"}
        </Button>
      </form>
    </main>
  );
}
