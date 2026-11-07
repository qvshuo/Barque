import { useCallback, useEffect, useState, useRef, type ReactNode } from "react";
import { Bell, BellOff, Search, Check } from "lucide-react";
import { toast } from "sonner";
import { SpendingChart } from "./SpendingChart";
import {
  api,
  cycleLabels,
  formatTime,
  money,
  type Dashboard,
  type SubscriptionItem,
} from "./api";
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
  const state = paid ? "已付费，不再提醒" : today ? "今天到期" : soon ? "即将到期" : "正常账期";
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

export function SubscriptionsPage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
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
      requestId.current++;
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
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setPending(null);
    }
  }
  const summary = dashboard?.summary;
  const groups = dashboard?.category_groups
    .filter((group) => category === null || category === group.category_name)
    .map((group) => {
      const items = group.subscription_items.filter((item) =>
        `${item.name} ${item.category}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
      );
      return {
        ...group,
        subscription_items: items,
        yearly_estimated_cny: items.reduce((total, item) => total + (item.yearly_estimated_cny ?? 0), 0),
      };
    })
    .filter((group) => group.subscription_items.length);
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">我的订阅</h1>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>无法加载订阅</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-4">
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
          <Card>
            <CardContent className="grid grid-cols-2 gap-6 px-4 sm:px-6 lg:grid-cols-4">
            {[
              ["订阅总数", String(summary.total_subscription_count)],
              ["即将到期", String(summary.expiring_subscription_count)],
              ["本月待付", money(summary.monthly_due_cny, "CNY", true), money(summary.monthly_due_cny)],
              ["预计年支出", money(summary.yearly_estimated_cny, "CNY", true), money(summary.yearly_estimated_cny)],
            ].map(([label, value, fullValue = value]) => (
              <div key={label} className="min-w-0 space-y-2">
                  <CardDescription>{label}</CardDescription>
                  <CardTitle className="text-xl tabular-nums sm:text-2xl" title={fullValue} aria-label={fullValue}>
                    {value}
                  </CardTitle>
              </div>
            ))}
            </CardContent>
            {dashboard && <SpendingChart groups={dashboard.category_groups} selected={category} onSelect={setCategory} />}
          </Card>
        )
      )}
      {dashboard &&
        (summary!.total_subscription_count === 0 &&
        !search &&
        category === null ? (
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
              <Select
                value={category === null ? "all" : `category:${category}`}
                onValueChange={value => setCategory(value === "all" ? null : value.slice("category:".length))}
              >
                <SelectTrigger className="w-full sm:w-44" aria-label="筛选分类">
                  <SelectValue placeholder="全部分类" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部分类</SelectItem>
                  {category !== null &&
                    !dashboard.category_groups.some(
                      (group) => group.category_name === category,
                    ) && <SelectItem value={`category:${category}`}>{category}</SelectItem>}
                  {dashboard.category_groups.map((group) => (
                    <SelectItem
                      key={group.category_name}
                      value={`category:${group.category_name}`}
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
            {groups?.map((group) => (
              <section
                key={group.category_name}
                className="space-y-4"
                aria-label={group.category_name}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="min-w-0 wrap-anywhere text-sm font-medium">
                    {group.category_name}
                  </h2>
                  <span className="ml-auto max-w-full wrap-anywhere text-xs tabular-nums text-muted-foreground">
                    {group.subscription_items.length} 个订阅，约 {money(group.yearly_estimated_cny)} / 年
                  </span>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {group.subscription_items.map((item) => (
                    <Card key={item.subscription_id} className="gap-3">
                      <CardHeader className="grid-rows-1">
                        <div className="flex items-start justify-between gap-2">
                          <CardTitle className="min-w-0 text-base font-medium">
                            {item.name}
                          </CardTitle>
                          <span role="img" className="inline-flex size-8 shrink-0 items-center justify-end text-muted-foreground" aria-label={`${item.name}：续费提醒已${item.notify_enabled ? "开启" : "关闭"}`} title={`续费提醒已${item.notify_enabled ? "开启" : "关闭"}`}>
                            {item.notify_enabled ? <Bell className="size-4" /> : <BellOff className="size-4" />}
                          </span>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div>
                          <span className="wrap-anywhere text-2xl font-semibold tabular-nums tracking-tight">
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
                          aria-label={`${item.name}：${item.button_state.status_kind === "renewed" ? "已付费，点击撤销" : "标记为已续费"}`}
                          aria-pressed={item.button_state.status_kind === "renewed"}
                          aria-busy={pending === item.subscription_id}
                          disabled={pending !== null}
                          title={item.button_state.status_kind === "renewed" ? "点击撤销本期续费" : "标记后，本期不再提醒"}
                          onClick={() => void mark(item, item.button_state.status_kind !== "renewed")}
                        >
                          {item.button_state.status_kind === "renewed" && <Check className="size-3.5" />}
                          {item.button_state.status_kind === "renewed" ? "已付费" : "标记为已续费"}
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

    </>
  );
}
