import { useCallback, useEffect, useState, useRef, type ReactNode } from "react";
import { Bell, BellOff, Plus, Search, LogOut, Check } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  cycleLabels,
  formatTime,
  money,
  type Dashboard,
  type SubscriptionItem,
} from "./api";
import { CategoryMenu } from "@/components/move-menu";
import { SettingsPage } from "./Settings";
import { useNavigationGuard } from "./UnsavedChanges";
import { SubscriptionDialog, newSubscription } from "./SubscriptionDialog";
import { SubscriptionMenu } from "./SubscriptionMenu";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

function progressPresentation(item: SubscriptionItem) {
  const paid = item.button_state.status_kind === "renewed";
  const today = item.days_left === 0;
  const soon = item.button_state.status_kind === "renewal_pending";
  const state = paid ? "本期已续费，不再提醒" : today ? "今天到期" : soon ? "即将到期" : "正常账期";
  return {
    value: today ? 100 : item.progress_percent,
    indicatorClassName: paid ? "bg-[var(--progress-paid)]" : today ? "bg-[var(--progress-urgent)]" : soon ? "bg-[var(--progress-soon)]" : "bg-[var(--progress-normal)]",
    "aria-valuetext": `${state}；账期进度 ${today ? 100 : item.progress_percent}%`,
    title: state,
  };
}

export function EmptyState({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <Card className="border-dashed py-12 text-center">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      {children && (
        <CardContent className="flex justify-center">{children}</CardContent>
      )}
    </Card>
  );
}

export function App() {
  const readSection = () =>
    location.hash === "#settings" ? "settings" : "overview";
  const [section, setSection] = useState(readSection);
  const { requestLeave } = useNavigationGuard();
  const acceptedHash = useRef(location.hash === "#settings" ? "#settings" : "");
  useEffect(() => {
    const update = () => {
      const next = location.hash === "#settings" ? "#settings" : "";
      const url = (hash: string) => location.pathname + location.search + hash;
      if (next === acceptedHash.current) { if (location.hash !== next) history.replaceState(null, "", url(next)); return; }
      history.replaceState(null, "", url(acceptedHash.current));
      requestLeave(() => {
        acceptedHash.current = next;
        history.replaceState(null, "", url(next));
        setSection(next === "#settings" ? "settings" : "overview");
      });
    };
    update();
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, [requestLeave]);
  return (
    <>
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <a href="/" onClick={event => { event.preventDefault(); if (section !== "overview") requestLeave(() => { location.hash = ""; }); }} className="flex min-w-0 items-center gap-2 font-medium">
            <img
              src="/logo.png"
              alt=""
              className="size-8 object-contain"
            />
            <span className="hidden max-w-40 truncate sm:inline">Barque</span>
          </a>
          <nav aria-label="主导航" className="ml-auto flex items-center gap-1">
            {[
              ["overview", "我的订阅"],
              ["settings", "设置"],
            ].map(([value, label]) => (
              <Button
                key={value}
                variant={section === value ? "secondary" : "ghost"}
                size="sm"
                asChild
              >
                <a
                  href={value === "overview" ? "#" : `#${value}`}
                  aria-current={section === value ? "page" : undefined}
                  onClick={event => { event.preventDefault(); if (section !== value) requestLeave(() => { location.hash = value === "settings" ? "settings" : ""; }); }}
                >
                  {label}
                </a>
              </Button>
            ))}
          </nav>
          <Button
            variant="ghost"
            size="icon"
            aria-label="退出登录"
            onClick={() => requestLeave(async () => { await api("/auth/logout", "POST"); window.dispatchEvent(new Event("barque:unauthorized")); })}
          >
            <LogOut />
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6 sm:py-10">
        {section === "settings" ? (
          <SettingsPage />
        ) : (
          <SubscriptionsPage />
        )}
      </main>
    </>
  );
}

function SubscriptionsPage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [pending, setPending] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [moving, setMoving] = useState(false);
  const [notifying, setNotifying] = useState<string | null>(null);
  const requestId = useRef(0);
  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const data = await api<Dashboard>("/dashboard");
      if (id !== requestId.current) return;
      setDashboard(data);
      setError("");
    } catch (err) {
      if (id === requestId.current) setError((err as Error).message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    let scheduled: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      if (document.hidden) return;
      clearTimeout(scheduled);
      scheduled = setTimeout(() => void load(), 100);
    };
    const interval = setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearTimeout(scheduled);
      clearInterval(interval);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);
  async function mark(item: SubscriptionItem, renewed: boolean) {
    setPending(item.subscription_id);
    try {
      await api("/renewal-status", "PUT", {
        subscription_id: item.subscription_id,
        payment_date: item.payment_date,
        renewal_date: item.renewal_date,
        renewed,
      });
      toast.success(renewed ? "本期已续费，不再提醒" : "已撤销续费");
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setPending(null);
    }
  }
  async function toggleNotification(item: SubscriptionItem) {
    setNotifying(item.subscription_id);
    try {
      const enabled = !item.notify_enabled;
      await api(`/subscriptions/${item.subscription_id}/notifications`, "PUT", { enabled });
      await load();
      toast.success(enabled ? "已开启续费提醒" : "已关闭续费提醒");
    } catch (error) { toast.error((error as Error).message); }
    finally { setNotifying(null); }
  }
  async function move(kind: "category" | "subscription", target: string, direction: "forward" | "backward") {
    setMoving(true);
    try {
      await api("/order", "PUT", { kind, target, direction });
      await load();
    } catch (error) { toast.error((error as Error).message); }
    finally { setMoving(false); }
  }
  const canSort = !search.trim() && category === "all" && !moving && pending === null && notifying === null;
  const summary = dashboard?.summary;
  const groups = dashboard?.category_groups
    .filter((group) => category === "all" || category === group.category_name)
    .map((group) => ({
      ...group,
      subscription_items: group.subscription_items.filter((item) =>
        `${item.name} ${item.category}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
      ),
    }))
    .filter((group) => group.subscription_items.length);
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            我的订阅
          </h1>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setAdding(true)}>
            <Plus />
            添加订阅
          </Button>
        </div>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>无法加载订阅</AlertTitle>
          <AlertDescription className="flex items-center gap-4">
            {error}
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重试
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!dashboard && loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[1, 2, 3, 4].map((n) => (
            <Skeleton key={n} className="h-32 rounded-xl" />
          ))}
        </div>
      ) : (
        summary && (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              ["订阅总数", String(summary.total_subscription_count)],
              ["即将到期", String(summary.expiring_subscription_count)],
              ["本月待付", money(summary.monthly_due_cny)],
              ["预计年支出", money(summary.yearly_estimated_cny)],
            ].map(([label, value]) => (
              <Card key={label} className="py-4 sm:py-6">
                <CardHeader className="px-4 sm:px-6">
                  <CardDescription>{label}</CardDescription>
                  <CardTitle className="break-all text-xl tabular-nums sm:text-2xl">
                    {value}
                  </CardTitle>
                </CardHeader>
              </Card>
            ))}
          </div>
        )
      )}
      {dashboard &&
        (summary!.total_subscription_count === 0 &&
        !search &&
        category === "all" ? (
          <EmptyState title="暂无订阅" />
        ) : (
          <>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="relative flex-1">
                <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
                <Input
                  aria-label="搜索订阅"
                  placeholder="搜索订阅"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="w-full sm:w-44" aria-label="筛选分类">
                  <SelectValue placeholder="全部分类" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部分类</SelectItem>
                  {category !== "all" &&
                    !dashboard.category_groups.some(
                      (group) => group.category_name === category,
                    ) && <SelectItem value={category}>{category}</SelectItem>}
                  {dashboard.category_groups.map((group) => (
                    <SelectItem
                      key={group.category_name}
                      value={group.category_name}
                    >
                      {group.category_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {!groups?.length && (
              <EmptyState
                title="没有匹配的订阅"
                description="试试其他关键词或分类。"
              />
            )}
            {groups?.map((group, groupIndex) => (
              <section
                key={group.category_name}
                className="space-y-4"
                aria-label={group.category_name}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-medium">
                    {group.category_name}
                  </h2>
                  <CategoryMenu name={group.category_name} canForward={canSort && groupIndex > 0} canBackward={canSort && groupIndex < groups.length - 1} onMove={direction => void move("category", group.category_name, direction)} />
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                    {group.subscription_items.length} 个订阅，约 {money(group.yearly_estimated_cny)} / 年
                  </span>
                </div>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  {group.subscription_items.map((item, itemIndex) => (
                    <Card key={item.subscription_id} className="gap-3">
                      <CardHeader className="grid-rows-1">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 space-y-2">
                            <CardTitle className="break-words text-base font-medium">
                              {item.name}
                            </CardTitle>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button variant="ghost" size="icon-sm" className="text-muted-foreground" aria-label={`${item.name}：续费提醒已${item.notify_enabled ? "开启" : "关闭"}`} aria-pressed={item.notify_enabled} title={`续费提醒已${item.notify_enabled ? "开启" : "关闭"}`} disabled={moving || notifying !== null || pending !== null} onClick={() => void toggleNotification(item)}>
                              {item.notify_enabled ? <Bell className="size-4" /> : <BellOff className="size-4" />}
                            </Button>
                            <SubscriptionMenu
                              subscription={{
                                ...item,
                                id: item.subscription_id,
                              }}
                              pending={moving || pending !== null || notifying !== null}
                              move={{ canForward: canSort && itemIndex > 0, canBackward: canSort && itemIndex < group.subscription_items.length - 1, onMove: direction => void move("subscription", item.subscription_id, direction) }}
                              onSaved={() => load()}
                              onDeleted={() => void load()}
                            />
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div>
                          <span className="text-2xl font-semibold tabular-nums tracking-tight">
                            {money(item.amount, item.currency)}
                          </span>
                          <span className="ml-2 inline-block whitespace-nowrap text-xs font-normal text-muted-foreground">
                            /{" "}
                            {cycleLabels[item.billing_cycle].replace("每", "")}
                          </span>
                        </div>
                        <div className="space-y-2">
                          <div className="flex justify-between gap-2 text-sm">
                            <span className="text-xs tabular-nums text-muted-foreground">
                              {item.renewal_date}
                            </span>
                            <span className="text-sm font-medium tabular-nums text-foreground">
                              {item.days_left === 0
                                ? "今天到期"
                                : `${item.days_left} 天后到期`}
                            </span>
                          </div>
                          <Progress
                            {...progressPresentation(item)}
                            className="h-1.5 bg-muted"
                            aria-label={`${item.name} 账期进度`}
                          />
                        </div>
                      </CardContent>
                      <CardFooter className="mt-auto flex-wrap justify-between gap-4 text-xs font-normal tabular-nums text-muted-foreground">
                        {item.currency !== "CNY" && <span>
                          {item.amount_cny === null ? "汇率待更新" : `约 ${money(item.amount_cny)}`}
                        </span>}
                        <Button
                          variant="link"
                          className="ml-auto h-auto justify-end gap-1 px-0 py-1 has-[>svg]:px-0 text-xs font-normal text-muted-foreground hover:text-foreground hover:no-underline"
                          aria-label={`${item.name}：${item.button_state.status_kind === "renewed" ? "本期已续费，点击撤销" : "标记为已续费"}`}
                          aria-pressed={item.button_state.status_kind === "renewed"}
                          aria-busy={pending === item.subscription_id}
                          disabled={moving || pending !== null || notifying !== null}
                          title={item.button_state.status_kind === "renewed" ? "点击撤销本期续费" : "标记后，本期不再提醒"}
                          onClick={() => void mark(item, item.button_state.status_kind !== "renewed")}
                        >
                          {item.button_state.status_kind === "renewed" && <Check className="size-3.5" />}
                          {item.button_state.status_kind === "renewed" ? "本期已续费" : "标记为已续费"}
                        </Button>
                      </CardFooter>
                    </Card>
                  ))}
                </div>
              </section>
            ))}
          </>
        ))}
      {summary && (
        <p className="text-xs text-muted-foreground">
          上次检查：{formatTime(summary.last_check_at)} · 汇率更新：
          {formatTime(summary.exchange_rate_updated_at)}
          {dashboard?.category_groups.some((group) =>
            group.subscription_items.some((item) => item.amount_cny === null),
          )
            ? " · 部分外币汇率暂不可用，合计暂未包含这些订阅"
            : ""}
        </p>
      )}
      {adding && (
        <SubscriptionDialog
          initial={newSubscription()}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            void load();
          }}
        />
      )}
    </>
  );
}
