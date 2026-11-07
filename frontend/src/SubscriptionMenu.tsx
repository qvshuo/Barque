import { useRef, useState } from "react";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type Subscription } from "./api";
import { MoveMenuItems, type MoveActions } from "@/components/move-menu";
import { SubscriptionDialog } from "./SubscriptionDialog";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function SubscriptionMenu({
  subscription,
  onSaved,
  onDeleted,
  pending,
  move,
}: {
  subscription: Subscription;
  onSaved: (subscription: Subscription) => void | Promise<void>;
  onDeleted: (id: string) => void;
  pending?: boolean;
  move: MoveActions;
}) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api(`/subscriptions/${subscription.id}`, "DELETE");
      setDeleting(false);
      onDeleted(subscription.id);
      toast.success("订阅已删除");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={trigger}
            variant="ghost"
            size="icon-sm"
            aria-label={`${subscription.name} 操作`}
            aria-busy={pending}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          onCloseAutoFocus={(event) => {
            if (editing || deleting) event.preventDefault();
          }}
        >
          <DropdownMenuItem
            disabled={pending}
            onSelect={() => setEditing(true)}
          >
            <Pencil />
            编辑
          </DropdownMenuItem>
          <MoveMenuItems {...move} canForward={!pending && move.canForward} canBackward={!pending && move.canBackward} />
          <DropdownMenuItem
            variant="destructive"
            disabled={pending}
            onSelect={() => {
              setError("");
              setDeleting(true);
            }}
          >
            <Trash2 />
            删除
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {editing && (
        <SubscriptionDialog
          initial={subscription}
          onClose={() => setEditing(false)}
          onCloseAutoFocus={() => trigger.current?.focus()}
          onSaved={(saved) => {
            setEditing(false);
            onSaved(saved);
          }}
        />
      )}
      <AlertDialog
        open={deleting}
        onOpenChange={(open) => {
          if (!busy) setDeleting(open);
        }}
      >
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            trigger.current?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>删除「{subscription.name}」？</AlertDialogTitle>
            <AlertDialogDescription>
              此订阅将被删除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => void remove()}
            >
              {busy ? "删除中…" : "确认删除"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
