import { expect, test, type APIRequestContext } from "@playwright/test";
import type { SubscriptionGroups } from "../src/api";

const headers = { "X-Barque-Request": "1" };
const password = process.env.BARQUE_TEST_PASSWORD;
if (!password) throw new Error("Set BARQUE_TEST_PASSWORD for the isolated test instance");
let prefix = "";

async function snapshot(request: APIRequestContext): Promise<SubscriptionGroups> {
  const response = await request.get("/api/subscription-groups");
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function seed(request: APIRequestContext) {
  const current = await snapshot(request);
  const create = (name: string) => ({
    id: crypto.randomUUID().replaceAll("-", ""), name, category: `${prefix} A`,
    billing_cycle: "month", payment_date: new Date().toLocaleDateString("en-CA"),
    amount: 21, currency: "CNY", notify_enabled: true,
  });
  const items = [create(`${prefix} One`), create(`${prefix} Two`)];
  const response = await request.put("/api/subscription-groups", {
    headers, data: { ...current, categories: [...current.categories,
      { name: `${prefix} A`, subscriptions: items }, { name: `${prefix} B`, subscriptions: [] }],
    },
  });
  expect(response.ok()).toBeTruthy();
  return items;
}

test.beforeEach(async ({ page, request }) => {
  prefix = `E2E ${Date.now()}`;
  const response = await request.post("/api/auth/login", { headers, data: { password } });
  expect(response.ok()).toBeTruthy();
  await page.context().addCookies((await request.storageState()).cookies);
});

test.afterEach(async ({ request }) => {
  expect((await request.post("/api/auth/login", { headers, data: { password } })).ok()).toBeTruthy();
  const current = await snapshot(request);
  if (!current.categories.some(group => group.name.startsWith(prefix))) return;
  const response = await request.put("/api/subscription-groups", {
    headers, data: { ...current, categories: current.categories.filter(group => !group.name.startsWith(prefix)) },
  });
  expect(response.ok()).toBeTruthy();
});

test("session verification never flashes the login form", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/auth/session", async route => { await gate; await route.continue(); });
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("main")).toBeEmpty();
    await expect(page.getByLabel("密码", { exact: true })).toHaveCount(0);
  } finally { release(); }
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
});

test("session verification can be retried after a failure", async ({ page }) => {
  let first = true;
  await page.route("**/api/auth/session", async route => {
    if (first) { first = false; await route.fulfill({ status: 503, json: { error: "暂时无法连接" } }); }
    else await route.continue();
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("暂时无法连接");
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
});

test("all tabs share site authentication and logout revokes access", async ({ page }) => {
  await page.context().clearCookies();
  for (const path of ["/", "/#subscriptions", "/#settings"]) {
    await page.goto(path);
    await expect(page.getByLabel("密码", { exact: true })).toBeVisible();
    await expect(page.getByRole("navigation")).toHaveCount(0);
    for (const api of ["dashboard", "settings", "subscription-groups"]) expect((await page.request.get(`/api/${api}`)).status()).toBe(401);
  }
  await page.getByLabel("密码", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "设置", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "管理订阅", exact: true }).click();
  await expect(page.getByRole("heading", { name: "管理订阅" })).toBeVisible();
  await page.getByRole("link", { name: "首页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByLabel("密码", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/subscription-groups")).status()).toBe(401);
});

test("management is an editor without dashboard metrics or renewal actions", async ({ page, request }) => {
  await seed(request);
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link")).toHaveText(["首页", "管理订阅", "设置"]);
  await expect(nav.getByRole("link", { name: "管理订阅" })).toHaveAttribute("href", "#subscriptions");
  await expect(page.getByText("预计年支出", { exact: true })).toBeVisible();
  await nav.getByRole("link", { name: "管理订阅" }).click();
  await expect(page.getByRole("heading", { name: "管理订阅" })).toBeVisible();
  for (const label of ["订阅总数", "即将到期", "本月待付", "预计年支出", "搜索订阅"]) await expect(page.getByText(label, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /标记为已续费/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await page.reload();
  await expect(nav.getByRole("link", { name: "管理订阅" })).toHaveAttribute("aria-current", "page");
  await nav.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByLabel(/^时区/)).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "管理订阅" })).toBeVisible();
});

test("inline editing ordering and deletions apply together only after saving", async ({ page, request }) => {
  const items = await seed(request);
  await page.goto("/#subscriptions");
  const group = page.getByRole("region", { name: `${prefix} A`, exact: true });
  await group.getByRole("button", { name: `${prefix} Two 上移`, exact: true }).click();
  const second = group.getByRole("group", { name: `${prefix} Two`, exact: true });
  await second.getByLabel(/^订阅名称/).fill(`${prefix} Renamed`);
  await page.getByRole("group", { name: `${prefix} Renamed`, exact: true }).getByLabel(/^每期费用/).fill("35.88");
  await group.getByLabel(/^分类/).fill(`${prefix} Renamed category`);
  await page.getByRole("button", { name: `${prefix} B 分类 上移`, exact: true }).click();
  let current = await snapshot(request);
  expect(current.categories.find(group => group.name === `${prefix} A`)!.subscriptions.map(item => item.name)).toEqual(items.map(item => item.name));
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  current = await snapshot(request);
  const updated = current.categories.find(group => group.name === `${prefix} Renamed category`)!;
  expect(updated.subscriptions.map(item => item.name)).toEqual([`${prefix} Renamed`, `${prefix} One`]);
  expect(updated.subscriptions[0].amount).toBe(35.88);
  expect(current.categories.findIndex(group => group.name === `${prefix} B`)).toBeLessThan(current.categories.indexOf(updated));
  await page.reload();
  await page.getByRole("button", { name: `${prefix} One 删除`, exact: true }).click();
  expect((await snapshot(request)).categories.find(group => group.name === updated.name)!.subscriptions).toHaveLength(2);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  expect((await snapshot(request)).categories.find(group => group.name === updated.name)!.subscriptions).toHaveLength(1);
  await page.getByRole("link", { name: "首页", exact: true }).click();
  await page.getByLabel("搜索订阅").fill(`${prefix} Renamed`);
  await expect(page.getByText(`${prefix} Renamed`, { exact: true })).toBeVisible();
});

test("new categories and subscriptions use inline shadcn date and currency selectors", async ({ page, request }) => {
  await page.goto("/#subscriptions");
  await page.getByRole("button", { name: "添加分类", exact: true }).click();
  await page.getByRole("region", { name: "新分类", exact: true }).getByLabel(/^分类/).fill(`${prefix} New`);
  const group = page.getByRole("region", { name: `${prefix} New`, exact: true });
  await group.getByRole("button", { name: "添加订阅", exact: true }).click();
  await group.getByLabel(/^订阅名称/).fill(`${prefix} Added`);
  await group.getByLabel(/^付款日期/).click();
  const calendar = page.locator('[data-slot="calendar"]');
  await expect(calendar).toBeVisible();
  await calendar.locator('select').filter({ has: page.locator('option[value="2000"]') }).selectOption("2000");
  await calendar.locator('select').filter({ has: page.locator('option[value="1"]') }).selectOption("1");
  await calendar.getByRole("button", { name: /29/ }).click();
  await expect(group.getByLabel(/^付款日期/)).toHaveText("2000-02-29");
  await group.getByLabel(/^币种/).click();
  await page.getByRole("option", { name: /^USD/ }).click();
  await group.getByRole("switch", { name: "续费提醒" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  const added = (await snapshot(request)).categories.find(group => group.name === `${prefix} New`)!.subscriptions[0];
  expect(added).toMatchObject({ name: `${prefix} Added`, payment_date: "2000-02-29", currency: "USD", notify_enabled: false });
  await page.reload();
  await expect(page.getByRole("region", { name: `${prefix} New`, exact: true }).getByRole("switch")).not.toBeChecked();
});

test("unsaved management changes guard tab switches and can be discarded", async ({ page, request }) => {
  await seed(request);
  await page.goto("/#subscriptions");
  const item = page.getByRole("group", { name: `${prefix} One`, exact: true });
  await item.getByLabel(/^订阅名称/).fill(`${prefix} Draft`);
  await page.getByRole("link", { name: "首页", exact: true }).click();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByRole("group", { name: `${prefix} Draft`, exact: true })).toBeVisible();
  expect(await page.evaluate(() => { const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; })).toBeTruthy();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByRole("button", { name: "放弃更改", exact: true }).click();
  await expect(page.getByLabel(/^时区/)).toBeVisible();
  await page.getByRole("link", { name: "管理订阅", exact: true }).click();
  await expect(page.getByRole("group", { name: `${prefix} One`, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
});

test("failed batch save retains drafts and can be retried", async ({ page, request }) => {
  await seed(request);
  await page.goto("/#subscriptions");
  await page.getByRole("group", { name: `${prefix} One`, exact: true }).getByLabel(/^每期费用/).fill("42");
  let failed = false;
  await page.route("**/api/subscription-groups", async route => {
    if (route.request().method() === "PUT" && !failed) { failed = true; await route.fulfill({ status: 500, json: { error: "保存失败，请重试" } }); }
    else await route.continue();
  });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("保存失败");
  await expect(page.getByRole("group", { name: `${prefix} One`, exact: true }).getByLabel(/^每期费用/)).toHaveValue("42");
  expect((await snapshot(request)).categories.find(group => group.name === `${prefix} A`)!.subscriptions[0].amount).toBe(21);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  expect((await snapshot(request)).categories.find(group => group.name === `${prefix} A`)!.subscriptions[0].amount).toBe(42);
});

test("concurrent changes are preserved and stale drafts require reloading", async ({ page, request }) => {
  const items = await seed(request);
  await page.goto("/#subscriptions");
  await page.getByRole("group", { name: `${prefix} One`, exact: true }).getByLabel(/^每期费用/).fill("42");
  expect((await request.put(`/api/subscriptions/${items[0].id}/notifications`, { headers, data: { enabled: false } })).ok()).toBeTruthy();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("其他页面更新");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await page.getByRole("button", { name: "放弃更改", exact: true }).click();
  await expect(page.getByRole("group", { name: `${prefix} One`, exact: true }).getByRole("switch")).not.toBeChecked();
  await expect(page.getByRole("group", { name: `${prefix} One`, exact: true }).getByLabel(/^每期费用/)).toHaveValue("21");
});

test("failed reload preserves the draft and its navigation guard", async ({ page, request }) => {
  await seed(request);
  await page.goto("/#subscriptions");
  const amount = page.getByRole("group", { name: `${prefix} One`, exact: true }).getByLabel(/^每期费用/);
  await amount.fill("42");
  let failReload = true;
  await page.route("**/api/subscription-groups", async route => {
    if (route.request().method() === "PUT") await route.fulfill({ status: 500, json: { error: "保存失败" } });
    else if (failReload) await route.fulfill({ status: 503, json: { error: "暂时无法重新加载" } });
    else await route.continue();
  });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("保存失败");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await page.getByRole("button", { name: "放弃更改", exact: true }).click();
  await expect(page.getByText("暂时无法重新加载", { exact: true })).toBeVisible();
  await expect(amount).toHaveValue("42");
  await page.getByRole("link", { name: "首页", exact: true }).click();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(amount).toHaveValue("42");
  failReload = false;
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await page.getByRole("button", { name: "放弃更改", exact: true }).click();
  await expect(amount).toHaveValue("21");
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
});

test("renewal marking stays on the home page and survives management edits", async ({ page, request }) => {
  await seed(request);
  await page.goto("/");
  await page.getByLabel("搜索订阅").fill(`${prefix} One`);
  await page.getByRole("button", { name: `${prefix} One：标记为已续费`, exact: true }).click();
  await expect(page.getByRole("button", { name: `${prefix} One：已付费，点击撤销`, exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("link", { name: "管理订阅", exact: true }).click();
  await page.getByRole("group", { name: `${prefix} One`, exact: true }).getByRole("switch").click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await page.getByRole("link", { name: "首页", exact: true }).click();
  await page.getByLabel("搜索订阅").fill(`${prefix} One`);
  await expect(page.getByRole("button", { name: `${prefix} One：已付费，点击撤销`, exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: `${prefix} One：续费提醒已关闭`, exact: true })).toBeVisible();
});

test("all pages fit narrow screens", async ({ page, request }) => {
  await seed(request);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    for (const [path, heading] of [["/", "我的订阅"], ["/#subscriptions", "管理订阅"], ["/#settings", "设置"]]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      if (path === "/#subscriptions") await expect(page.getByRole("button", { name: "保存", exact: true })).toBeVisible();
      if (path === "/#settings") await expect(page.getByLabel(/^时区/)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    }
  }
});

test("settings validation persistence and unsaved changes remain independent", async ({ page, request }) => {
  const original = await (await request.get("/api/settings")).json();
  try {
    await page.goto("/#settings");
    await page.getByLabel(/^时区/).fill("Invalid/Timezone");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("IANA");
    await page.getByLabel(/^时区/).fill("Asia/Shanghai");
    await page.getByLabel(/^提前提醒天数/).fill("11");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();
    await expect(page.getByText("尚未保存", { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel(/^提前提醒天数/)).toHaveValue("11");
    await page.getByLabel(/^时区/).fill("Europe/London");
    await page.getByRole("link", { name: "管理订阅", exact: true }).click();
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    await expect(page.getByLabel(/^时区/)).toHaveValue("Europe/London");
    await page.getByRole("link", { name: "首页", exact: true }).click();
    await page.getByRole("button", { name: "放弃更改", exact: true }).click();
    await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  } finally { expect((await request.put("/api/settings", { headers, data: original })).ok()).toBeTruthy(); }
});

test("theme follows the system", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("link", { name: "管理订阅", exact: true }).click();
  await expect(page.getByRole("heading", { name: "管理订阅" })).toBeVisible();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
