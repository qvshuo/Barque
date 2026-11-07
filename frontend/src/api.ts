export type Settings = {
  timezone: string;
  check_interval_seconds: number;
  remind_before_days: number;
  reminder_time: string;
  notify_url: string;
};
export type Subscription = {
  id: string;
  name: string;
  category: string;
  billing_cycle: string;
  payment_date: string;
  amount: number;
  currency: string;
  notify_enabled: boolean;
};
export type SubscriptionGroup = { name: string; subscriptions: Subscription[] };
export type SubscriptionGroups = { categories: SubscriptionGroup[]; revision: string };
export type SubscriptionItem = Omit<Subscription, "id"> & {
  subscription_id: string;
  renewal_date: string;
  days_left: number;
  progress_percent: number;
  amount_cny: number | null;
  yearly_estimated_cny: number | null;
  button_state: {
    status_kind: string;
    status_label: string;
    action_label: string;
    can_toggle: boolean;
  };
};
export type Dashboard = {
  title: string;
  summary: {
    total_subscription_count: number;
    total_category_count: number;
    expiring_subscription_count: number;
    remind_before_days: number;
    monthly_due_cny: number;
    yearly_estimated_cny: number;
    last_check_at: string | null;
    exchange_rate_updated_at: string | null;
  };
  category_groups: {
    category_name: string;
    subscription_count: number;
    yearly_estimated_cny: number;
    subscription_items: SubscriptionItem[];
  }[];
};
export const cycleLabels: Record<string, string> = {
  week: "每周",
  month: "每月",
  quarter: "每季度",
  year: "每年",
};
const moneyFormatters = new Map<string, Intl.NumberFormat>();
export function money(value: number, currency = "CNY", compact = false) {
  const notation = compact && Math.abs(value) >= 1_000_000 ? "compact" : "standard";
  const key = `${currency}:${notation}`;
  let formatter = moneyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("zh-CN", { style: "currency", currency, notation });
    moneyFormatters.set(key, formatter);
  }
  return formatter.format(value);
}
export const formatTime = (value: string | null) =>
  value ? new Date(value).toLocaleString("zh-CN") : "尚未更新";

export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    signal: AbortSignal.timeout(30_000),
    headers:
      method === "GET"
        ? {}
        : { "Content-Type": "application/json", "X-Barque-Request": "1" },
    body: method === "GET" ? undefined : JSON.stringify(data ?? {}),
  }).catch((error: Error) => {
    if (error.name === "TimeoutError") throw new Error("请求超时，请刷新页面确认后重试");
    throw error;
  });
  if (response.status === 401 && !path.startsWith("/auth/"))
    window.dispatchEvent(new Event("barque:unauthorized"));
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.error || `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
