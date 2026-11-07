import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

type Action = () => void | Promise<void>;
type Guard = { register: (id: string, dirty: boolean) => void; requestLeave: (action: Action) => void };
const Context = createContext<Guard | null>(null);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const changes = useRef(new Set<string>());
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<{ action: Action } | null>(null);
  const register = useCallback((id: string, value: boolean) => {
    if (value) changes.current.add(id); else changes.current.delete(id);
    setDirty(changes.current.size > 0);
  }, []);
  const requestLeave = useCallback((action: Action) => {
    if (changes.current.size) setPending({ action });
    else void Promise.resolve().then(action).catch(error => toast.error((error as Error).message));
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const block = (event: BeforeUnloadEvent) => {
      if (!changes.current.size) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", block);
    return () => window.removeEventListener("beforeunload", block);
  }, [dirty]);
  async function discard() {
    if (!pending) return;
    const action = pending.action;
    const previous = new Set(changes.current);
    changes.current.clear(); setDirty(false); setPending(null);
    try { await action(); }
    catch (error) { changes.current = previous; setDirty(previous.size > 0); toast.error((error as Error).message); }
  }
  const value = useMemo(() => ({ register, requestLeave }), [register, requestLeave]);
  return <Context.Provider value={value}>{children}<AlertDialog open={!!pending} onOpenChange={open => { if (!open) setPending(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>放弃未保存的更改？</AlertDialogTitle><AlertDialogDescription>离开后，这些更改将不会保存。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>继续编辑</AlertDialogCancel><Button variant="destructive" onClick={() => void discard()}>放弃更改</Button></AlertDialogFooter></AlertDialogContent></AlertDialog></Context.Provider>;
}

export function useNavigationGuard() {
  const value = useContext(Context);
  if (!value) throw new Error("Missing unsaved changes provider");
  return value;
}

export function useUnsavedChanges(dirty: boolean) {
  const id = useId();
  const { register } = useNavigationGuard();
  useLayoutEffect(() => { register(id, dirty); return () => register(id, false); }, [dirty, id, register]);
  return useCallback(() => register(id, false), [id, register]);
}
