import type { ReactNode } from "react";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SaveBar({ dirty, busy, disabled, children }: {
  dirty: boolean;
  busy: boolean;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="sticky bottom-0 z-10 space-y-3 border-t bg-background py-4">
      {children}
      <div className="flex items-center justify-end gap-4">
        {dirty && <span className="text-sm text-muted-foreground">尚未保存</span>}
        <Button type="submit" disabled={busy || disabled || !dirty}><Save />{busy ? "保存中…" : "保存"}</Button>
      </div>
    </div>
  );
}
