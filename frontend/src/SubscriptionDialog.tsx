import { CalendarIcon } from "lucide-react";
import { format, parseISO } from "date-fns";
import { zhCN } from "react-day-picker/locale";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useNavigationGuard, useUnsavedChanges } from "./UnsavedChanges";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { api, cycleLabels, type Subscription } from "./api";
import { Field } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const newSubscription = (): Subscription => {
  const now = new Date();
  const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return {
    id: "",
    name: "",
    category: "",
    billing_cycle: "month",
    payment_date: localDate,
    amount: 0,
    currency: "CNY",
    notify_enabled: true,
  };
};

export function SubscriptionDialog({
  initial,
  onClose,
  onSaved,
  onCloseAutoFocus,
}: {
  initial: Subscription;
  onClose: () => void;
  onSaved: (subscription: Subscription) => void;
  onCloseAutoFocus?: () => void;
}) {
  const [original] = useState(initial);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [currencies, setCurrencies] = useState<{code: string; name: string}[]>([]);
  const [currencyError, setCurrencyError] = useState("");
  const loadCurrencies = () => {
    setCurrencyError("");
    void api<{code: string; name: string}[]>("/currencies").then(setCurrencies).catch(error => setCurrencyError(error.message));
  };
  useEffect(loadCurrencies, []);
  const [draft, setDraft] = useState(initial);
  const [initialNotifyEnabled] = useState(initial.notify_enabled);
  const [amount, setAmount] = useState(String(initial.amount));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const markSaved = useUnsavedChanges(JSON.stringify({...draft, amount: Number(amount)}) !== JSON.stringify(original));
  const { requestLeave } = useNavigationGuard();
  const close = () => requestLeave(onClose);
  const patch = (value: Partial<Subscription>) =>
    setDraft((previous) => ({ ...previous, ...value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { notify_enabled, ...details } = draft;
      const saved = await api<Subscription>(
        `/subscriptions${draft.id ? `/${draft.id}` : ""}`,
        draft.id ? "PUT" : "POST",
        {
          ...details,
          ...(!draft.id || notify_enabled !== initialNotifyEnabled
            ? { notify_enabled }
            : {}),
          amount: Number(amount),
        },
      );
      toast.success(draft.id ? "订阅已更新" : "订阅已添加");
      markSaved();
      onSaved(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) close();
      }}
    >
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto"
        onCloseAutoFocus={(event) => {
          if (onCloseAutoFocus) {
            event.preventDefault();
            onCloseAutoFocus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{draft.id ? "编辑订阅" : "添加订阅"}</DialogTitle>
          <DialogDescription className="sr-only">
            以付款日期为锚点，自动计算每个账期的续费日期。
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <fieldset disabled={busy} className="min-w-0 space-y-5">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field label="订阅名称" htmlFor="subscription-name" required>
              <Input
                id="subscription-name"
                value={draft.name}
                maxLength={200}
                required
                placeholder="e.g. iCloud+"
                onChange={(event) => patch({ name: event.target.value })}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="分类" htmlFor="subscription-category" required>
                <Input
                  id="subscription-category"
                  required
                  maxLength={100}
                  placeholder="e.g. 云服务"
                  value={draft.category}
                  onChange={(event) => patch({ category: event.target.value })}
                />
              </Field>
              <Field label="计费周期" htmlFor="subscription-cycle" required>
                <Select
                  value={draft.billing_cycle}
                  onValueChange={(value) => patch({ billing_cycle: value })}
                >
                  <SelectTrigger aria-required="true" id="subscription-cycle" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(cycleLabels).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field label="付款日期" htmlFor="subscription-date" required>
              <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
                <PopoverTrigger asChild>
                  <Button id="subscription-date" type="button" variant="outline" aria-required="true" className="w-full justify-between font-normal">
                    {draft.payment_date || "e.g. 2026-11-07"}<CalendarIcon className="text-muted-foreground" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar mode="single" locale={zhCN} captionLayout="dropdown" formatters={{formatMonthDropdown: date => format(date, "M月")}} startMonth={new Date(1900, 0)} endMonth={new Date(2100, 11)} selected={parseISO(draft.payment_date)} defaultMonth={parseISO(draft.payment_date)} onSelect={value => { if (value) { patch({ payment_date: format(value, "yyyy-MM-dd") }); setCalendarOpen(false); } }} />
                </PopoverContent>
              </Popover>
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="每期费用" htmlFor="subscription-amount" required>
                <Input
                  id="subscription-amount"
                  placeholder="e.g. 19.99"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="0.01"
                  required
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                />
              </Field>
              <Field label="币种" htmlFor="subscription-currency" required>
                <Select value={draft.currency} onValueChange={currency => patch({ currency })} disabled={!currencies.length}>
                  <SelectTrigger id="subscription-currency" aria-required="true" className="w-full"><SelectValue placeholder="e.g. CNY" /></SelectTrigger>
                  <SelectContent>{currencies.map(({code, name}) => <SelectItem key={code} value={code}>{code} · {new Intl.DisplayNames(["zh-CN"], {type: "currency"}).of(code) || name}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            {currencyError && <Alert variant="destructive"><AlertDescription>无法加载币种：{currencyError}<Button type="button" variant="outline" size="sm" onClick={loadCurrencies}>重试</Button></AlertDescription></Alert>}
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="subscription-notify">续费提醒</Label>
              <Switch
                id="subscription-notify"
                checked={draft.notify_enabled}
                onCheckedChange={(enabled) => patch({ notify_enabled: enabled })}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={close}
                disabled={busy}
              >
                取消
              </Button>
              <Button type="submit" disabled={busy || !currencies.some(item => item.code === draft.currency)}>
                {busy ? "保存中…" : "保存订阅"}
              </Button>
            </DialogFooter>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  );
}
