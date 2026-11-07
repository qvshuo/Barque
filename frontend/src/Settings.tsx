import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, EyeOff, Send, Download, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, type Settings } from "./api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Field } from "@/components/form-field";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { useUnsavedChanges } from "./UnsavedChanges";

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      const config = await api<Settings>("/settings");
      setSettings(config);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
        设置
      </h1>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>无法加载设置</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-4">
            {error}
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重试
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {loading ? (
        <Skeleton className="h-80 w-full rounded-xl" />
      ) : (
        settings && (
          <section>
            <SettingsForm
              initial={settings}
              onSaved={(value) => {
                setSettings(value);
              }}
            />
          </section>
        )
      )}
    </>
  );
}

function SettingsForm({
  initial,
  onSaved,
}: {
  initial: Settings;
  onSaved: (settings: Settings) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const fileInput = useRef<HTMLInputElement>(null);
  const [importData, setImportData] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const markSaved = useUnsavedChanges(dirty);
  const patch = (value: Partial<Settings>) =>
    setDraft((previous) => ({ ...previous, ...value }));
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || testing || !dirty) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api<Settings>("/settings", "PUT", draft);
      setDraft(saved);
      markSaved();
      onSaved(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function exportConfig() {
    try {
      const data = await api<unknown>("/configuration");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "barque-config.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { toast.error((err as Error).message); }
  }
  async function selectFile(file: File | undefined) {
    if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("配置文件不能超过 2 MB");
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("配置文件格式无效");
      setImportData(parsed);
    } catch { toast.error("无法读取配置文件，请选择有效的 JSON 文件（不超过 2 MB）"); }
  }
  async function importConfig() {
    setBusy(true);
    try {
      const saved = await api<Settings>("/configuration", "PUT", importData);
      setDraft(saved);
      markSaved();
      onSaved(saved);
      toast.success("配置已导入并生效");
    } catch (err) { toast.error((err as Error).message); }
    finally { setBusy(false); setImportData(null); }
  }
  async function test() {
    setTesting(true);
    try {
      await api("/test-notification", "POST");
      toast.success("测试通知已发送，请查看你的设备");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setTesting(false);
    }
  }
  return (
    <form
      onSubmit={(event) => void save(event)}
      className="space-y-6"
    >
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <fieldset disabled={busy || testing} className="space-y-6 min-w-0">
        <Card>
          <CardHeader>
            <CardTitle>应用设置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <Field
              label="时区"
              htmlFor="app-timezone"
              required
            >
              <Input
                id="app-timezone"
                placeholder="例如 Asia/Shanghai"
                value={draft.timezone}
                maxLength={100}
                required
                onChange={(event) => patch({ timezone: event.target.value })}
              />
            </Field>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>续费提醒</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <Field label="Bark 推送地址" htmlFor="notify-url">
              <div className="flex gap-2">
                <Input
                  id="notify-url"
                  type={reveal ? "text" : "password"}
                  value={draft.notify_url}
                  maxLength={2048}
                  autoComplete="off"
                  placeholder="例如 https://api.day.app/your-key"
                  onChange={(event) => patch({ notify_url: event.target.value })}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label={reveal ? "隐藏推送地址" : "显示推送地址"}
                  onClick={() => setReveal((value) => !value)}
                >
                  {reveal ? <EyeOff /> : <Eye />}
                </Button>
              </div>
            </Field>
            <Field label="提醒时间" htmlFor="reminder-time" required>
              <Input id="reminder-time" type="time" required value={draft.reminder_time} onChange={(event) => patch({ reminder_time: event.target.value })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="提前提醒天数" htmlFor="remind-days" required>
                <Input
                  id="remind-days"
                  placeholder="例如 7"
                  type="number"
                  min="0"
                  max="365"
                  step="1"
                  required
                  value={Number.isNaN(draft.remind_before_days) ? "" : draft.remind_before_days}
                  onChange={(event) =>
                    patch({ remind_before_days: event.target.valueAsNumber })
                  }
                />
              </Field>
              <Field
                label="检查间隔（秒）"
                htmlFor="check-interval"
                required
              >
                <Input
                  id="check-interval"
                  placeholder="例如 3600"
                  type="number"
                  min="10"
                  max="86400"
                  step="1"
                  required
                  value={Number.isNaN(draft.check_interval_seconds) ? "" : draft.check_interval_seconds}
                  onChange={(event) =>
                    patch({ check_interval_seconds: event.target.valueAsNumber })
                  }
                />
              </Field>
            </div>
          </CardContent>
          <CardFooter>
            <Button
              type="button"
              variant="outline"
              disabled={testing || busy || !initial.notify_url || dirty}
              onClick={() => void test()}
            >
              <Send />
              {testing ? "发送中…" : "发送测试通知"}
            </Button>
          </CardFooter>
        </Card>
        <Card>
          <CardHeader><CardTitle>备份与恢复</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <input ref={fileInput} type="file" accept=".json,application/json" className="sr-only" tabIndex={-1} onChange={event => { void selectFile(event.target.files?.[0]); event.target.value = ""; }} />
            <Button type="button" variant="outline" disabled={busy || testing || dirty} onClick={() => fileInput.current?.click()}><Upload />导入</Button>
            <Button type="button" variant="outline" disabled={busy || testing || dirty} onClick={() => void exportConfig()}><Download />导出</Button>
          </CardContent>
        </Card>
        <AlertDialog open={importData !== null} onOpenChange={open => { if (!open && !busy) setImportData(null); }}>
          <AlertDialogContent>
            <AlertDialogHeader><AlertDialogTitle>导入并覆盖配置？</AlertDialogTitle><AlertDialogDescription>当前应用设置和订阅将被文件中的配置覆盖。此操作无法撤销。</AlertDialogDescription></AlertDialogHeader>
            <AlertDialogFooter><AlertDialogCancel disabled={busy}>取消</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={event => { event.preventDefault(); void importConfig(); }}>{busy ? "导入中…" : "确认导入"}</AlertDialogAction></AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <div className="flex items-center gap-4">
          <Button type="submit" disabled={busy || testing || !dirty}>
            {busy ? "保存中…" : "保存设置"}
          </Button>
          {dirty && <p className="text-sm text-muted-foreground">尚未保存</p>}
        </div>
      </fieldset>
    </form>
  );
}
