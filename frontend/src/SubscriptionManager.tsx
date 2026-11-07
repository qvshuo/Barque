import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowDown, ArrowUp, CalendarIcon, Plus, Trash2 } from "lucide-react";
import { format, parseISO } from "date-fns";
import { zhCN } from "react-day-picker/locale";
import { api, cycleLabels, type Subscription, type SubscriptionGroup, type SubscriptionGroups } from "./api";
import { useNavigationGuard, useUnsavedChanges } from "./UnsavedChanges";
import { Field } from "@/components/form-field";
import { SaveBar } from "@/components/save-bar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

type Currency = { code: string; name: string };
type DraftGroup = SubscriptionGroup & { id: string };
const currencyNames = new Intl.DisplayNames(["zh-CN"], { type: "currency" });
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
const createDraft = (groups: SubscriptionGroup[]): DraftGroup[] => groups.map(group => ({ ...group, id: newId() }));
const toGroups = (draft: DraftGroup[]): SubscriptionGroup[] => draft.map(({ name, subscriptions }) => ({
  name,
  subscriptions: subscriptions.map(item => ({ ...item, category: name })),
}));

function moveEntry<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function OrderActions({ name, index, count, onMove, onDelete }: {
  name: string;
  index: number;
  count: number;
  onMove: (direction: -1 | 1) => void;
  onDelete: () => void;
}) {
  return (
    <div className="ml-auto flex shrink-0 gap-1">
      <Button type="button" variant="ghost" size="icon" aria-label={`${name} 上移`} title="上移" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp /></Button>
      <Button type="button" variant="ghost" size="icon" aria-label={`${name} 下移`} title="下移" disabled={index === count - 1} onClick={() => onMove(1)}><ArrowDown /></Button>
      <Button type="button" variant="ghost" size="icon" aria-label={`${name} 删除`} title="删除" onClick={onDelete}><Trash2 /></Button>
    </div>
  );
}

export function SubscriptionManager() {
  const [snapshot, setSnapshot] = useState<SubscriptionGroups | null>(null);
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [groups, catalog] = await Promise.all([
        api<SubscriptionGroups>("/subscription-groups"),
        api<Currency[]>("/currencies"),
      ]);
      setSnapshot(groups);
      setCurrencies(catalog);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">管理订阅</h1>
      {error && <Alert variant="destructive"><AlertDescription>{error}<Button variant="outline" size="sm" onClick={() => void load()}>重试</Button></AlertDescription></Alert>}
      {loading ? <Skeleton className="h-80 rounded-xl" /> : snapshot && (
        <ManagementForm initial={snapshot} currencies={currencies} />
      )}
    </>
  );
}

function ManagementForm({ initial, currencies }: {
  initial: SubscriptionGroups;
  currencies: Currency[];
}) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState(() => createDraft(initial.categories));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(toGroups(draft)) !== JSON.stringify(saved.categories);
  const markSaved = useUnsavedChanges(dirty);
  const { requestLeave } = useNavigationGuard();
  function updateGroup(id: string, patch: Partial<SubscriptionGroup>) {
    setDraft(previous => previous.map(group => group.id === id ? { ...group, ...patch } : group));
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !dirty) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<SubscriptionGroups>("/subscription-groups", "PUT", {
        categories: toGroups(draft), revision: saved.revision,
      });
      setSaved(result);
      setDraft(previous => result.categories.map((group, index) => ({ ...group, id: previous[index].id })));
      markSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function reload() {
    setBusy(true);
    try {
      const result = await api<SubscriptionGroups>("/subscription-groups");
      setSaved(result);
      setDraft(createDraft(result.categories));
      setError("");
      markSaved();
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={event => void save(event)} className="space-y-5">
      <fieldset disabled={busy} className="min-w-0 space-y-5">
        {draft.map((group, groupIndex) => (
          <Card key={group.id} role="region" aria-label={group.name || "新分类"}>
            <CardHeader className="grid-rows-1 px-4 sm:px-6">
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-0 grow basis-32">
                  <Field label="分类" htmlFor={`category-${group.id}`} required>
                    <Input id={`category-${group.id}`} required maxLength={100} value={group.name} onChange={event => updateGroup(group.id, { name: event.target.value })} />
                  </Field>
                </div>
                <OrderActions name={`${group.name || "新分类"} 分类`} index={groupIndex} count={draft.length}
                  onMove={direction => setDraft(previous => moveEntry(previous, groupIndex, direction))}
                  onDelete={() => setDraft(previous => previous.filter(item => item.id !== group.id))} />
              </div>
            </CardHeader>
            <CardContent className="space-y-3 px-4 sm:px-6">
              {group.subscriptions.map((item, itemIndex) => (
                <div key={item.id} role="group" aria-label={item.name || "新订阅"} className="space-y-4 rounded-lg border p-4">
                  <SubscriptionFields item={item} currencies={currencies}
                    onChange={patch => updateGroup(group.id, { subscriptions: group.subscriptions.map(current => current.id === item.id ? { ...current, ...patch } : current) })}
                    actions={<OrderActions name={item.name || "新订阅"} index={itemIndex} count={group.subscriptions.length}
                      onMove={direction => updateGroup(group.id, { subscriptions: moveEntry(group.subscriptions, itemIndex, direction) })}
                      onDelete={() => updateGroup(group.id, { subscriptions: group.subscriptions.filter(current => current.id !== item.id) })} />} />
                </div>
              ))}
              <Button type="button" variant="outline" onClick={() => updateGroup(group.id, { subscriptions: [...group.subscriptions, {
                id: newId(), name: "", category: group.name, billing_cycle: "month",
                payment_date: format(new Date(), "yyyy-MM-dd"), amount: 0, currency: "CNY", notify_enabled: true,
              }] })}><Plus />添加订阅</Button>
            </CardContent>
          </Card>
        ))}
        <Button type="button" variant="outline" onClick={() => setDraft(previous => [...previous, { id: newId(), name: "", subscriptions: [] }])}><Plus />添加分类</Button>
      </fieldset>
      <SaveBar dirty={dirty} busy={busy}>
        {error && <Alert variant="destructive"><AlertDescription>{error}<Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => requestLeave(reload)}>重新加载</Button></AlertDescription></Alert>}
      </SaveBar>
    </form>
  );
}

function SubscriptionFields({ item, currencies, onChange, actions }: {
  item: Subscription;
  currencies: Currency[];
  onChange: (patch: Partial<Subscription>) => void;
  actions: React.ReactNode;
}) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const id = (field: string) => `${field}-${item.id}`;
  return (
    <>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 grow basis-32">
          <Field label="订阅名称" htmlFor={id("name")} required>
            <Input id={id("name")} required maxLength={200} placeholder="例如 iCloud+" value={item.name} onChange={event => onChange({ name: event.target.value })} />
          </Field>
        </div>
        {actions}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="计费周期" htmlFor={id("cycle")} required>
          <Select value={item.billing_cycle} onValueChange={billing_cycle => onChange({ billing_cycle })}>
            <SelectTrigger id={id("cycle")} className="w-full" aria-required="true"><SelectValue /></SelectTrigger>
            <SelectContent>{Object.entries(cycleLabels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="付款日期" htmlFor={id("date")} required>
          <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
            <PopoverTrigger asChild><Button id={id("date")} type="button" variant="outline" className="w-full justify-between font-normal" aria-required="true">{item.payment_date}<CalendarIcon className="text-muted-foreground" /></Button></PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar mode="single" locale={zhCN} captionLayout="dropdown" formatters={{ formatMonthDropdown: date => format(date, "M月") }} startMonth={new Date(1900, 0)} endMonth={new Date(2100, 11)} selected={parseISO(item.payment_date)} defaultMonth={parseISO(item.payment_date)} onSelect={value => { if (value) { onChange({ payment_date: format(value, "yyyy-MM-dd") }); setCalendarOpen(false); } }} />
            </PopoverContent>
          </Popover>
        </Field>
        <Field label="每期费用" htmlFor={id("amount")} required>
          <Input id={id("amount")} type="number" min="0" max="1000000000" step="0.01" required value={Number.isNaN(item.amount) ? "" : item.amount} onChange={event => onChange({ amount: event.target.valueAsNumber })} />
        </Field>
        <Field label="币种" htmlFor={id("currency")} required>
          <Select value={item.currency} onValueChange={currency => onChange({ currency })}>
            <SelectTrigger id={id("currency")} className="w-full" aria-required="true"><SelectValue /></SelectTrigger>
            <SelectContent>{currencies.map(({ code, name }) => <SelectItem key={code} value={code}>{code} · {currencyNames.of(code) || name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </div>
      <div className="flex items-center justify-between gap-4">
        <Label htmlFor={id("notify")}>续费提醒</Label>
        <Switch id={id("notify")} checked={item.notify_enabled} onCheckedChange={notify_enabled => onChange({ notify_enabled })} />
      </div>
    </>
  );
}
