import { expect, test } from "@playwright/test";

const headers = { "X-Barque-Request": "1" };
const password = process.env.BARQUE_TEST_PASSWORD;
if (!password)
  throw new Error("Set BARQUE_TEST_PASSWORD for the isolated test instance");

test.beforeEach(async ({ page, request }) => {
  const response = await request.post("/api/auth/login", {
    headers,
    data: { password },
  });
  expect(response.ok()).toBeTruthy();
  await page.context().addCookies((await request.storageState()).cookies);
});

test("session verification never flashes the login form", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/auth/session", async route => {
    await gate;
    await route.continue();
  });
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("正在验证登录状态…")).toBeVisible();
    await expect(page.getByLabel("密码")).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await expect(page.getByLabel("密码")).toHaveCount(0);
});

test("session verification can be retried after a failure", async ({ page }) => {
  let first = true;
  await page.route("**/api/auth/session", async route => {
    if (first) {
      first = false;
      await route.fulfill({ status: 503, json: { error: "暂时无法连接" } });
    } else await route.continue();
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("暂时无法连接");
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
});

test("cycle markings and edits persist after reload", async ({
  page,
  request,
}) => {
  const name = `E2E iCloud ${Date.now()}`;
  const renamed = `${name} Family`;
  const response = await request.post("/api/subscriptions", {
    headers,
    data: {
      name,
      category: "测试",
      billing_cycle: "month",
      payment_date: new Date().toLocaleDateString("en-CA"),
      amount: 35.88,
      currency: "USD",
      notify_enabled: true,
    },
  });
  expect(response.ok()).toBeTruthy();
  const subscription = await response.json();
  try {
    await page.goto("/");
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(name);
    const renewal = page.getByRole("button", {name: `${name}：标记为已续费`, exact: true});
    const footer = page.locator('[data-slot="card-footer"]').filter({has: renewal});
    const conversion = footer.locator(":scope > span");
    const textStyle = (element: HTMLElement) => { const style = getComputedStyle(element); return [style.fontSize, style.fontWeight, style.color]; };
    expect(await renewal.evaluate(textStyle)).toEqual(await conversion.evaluate(textStyle));
    const conversionBox = await conversion.boundingBox();
    const buttonBox = await renewal.boundingBox();
    expect(buttonBox!.x).toBeGreaterThan(conversionBox!.x + conversionBox!.width);
    expect(Math.abs((buttonBox!.y + buttonBox!.height / 2) - (conversionBox!.y + conversionBox!.height / 2))).toBeLessThan(2);
    await page.getByRole("button", { name: new RegExp(`^${name}：(?:标记为已续费|本期已续费)`)}).click();
    await expect(
      page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]'),
    ).toBeVisible();
    await expect(page.getByRole("button", {name: `${name}：本期已续费，点击撤销`, exact: true})).toHaveAttribute("aria-pressed", "true");
    await page.reload();
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(name);
    await expect(
      page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]'),
    ).toBeVisible();
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await page.getByRole("menuitem", { name: "编辑", exact: true }).click();
    await page.getByLabel("订阅名称").fill(renamed);
    await page.getByRole("button", { name: "保存订阅" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page.reload();
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(renamed);
    await expect(page.getByText(renamed, { exact: true })).toBeVisible();
    await expect(
      page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]'),
    ).toBeVisible();
  } finally {
    expect(
      (
        await request.delete(`/api/subscriptions/${subscription.id}`, {
          headers,
          data: {},
        })
      ).ok(),
    ).toBeTruthy();
  }
});

test("settings are validated, saved and loaded after reload", async ({
  page,
  request,
}) => {
  const original = await (await request.get("/api/settings")).json();
  try {
    await page.goto("/#settings");
    await page.getByRole("link", { name: "设置", exact: true }).click();
    await expect(page.getByLabel("页面标题")).toHaveCount(0);
    await page.getByLabel(/^提前提醒天数/).fill("11");
    await page.getByLabel(/^时区/).fill("Invalid/Timezone");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("IANA");
    await page.getByLabel(/^时区/).fill("Asia/Shanghai");
    await page.getByRole("button", { name: "保存设置", exact: true }).click();
    await expect(page).toHaveTitle("Barque");
    await page.reload();
    await page.getByRole("link", { name: "设置", exact: true }).click();
    await expect(page.getByLabel(/^提前提醒天数/)).toHaveValue("11");
    await expect(
      page.getByRole("button", { name: "发送测试通知" }),
    ).toBeDisabled();
  } finally {
    const response = await request.put("/api/settings", {
      headers,
      data: original,
    });
    expect(response.ok()).toBeTruthy();
  }
});

test("theme always follows the system, including when a legacy preference exists", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("barque-theme", "dark"));
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await expect(page.getByRole("button", { name: "切换主题" })).toHaveCount(0);
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  const light = await page
    .locator("body")
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(
    await page
      .locator("body")
      .evaluate((element) => getComputedStyle(element).backgroundColor),
  ).not.toEqual(light);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("mobile overview and subscription dialog fit the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await expect(
    page.getByRole("link", { name: "我的订阅", exact: true }),
  ).toHaveAttribute("href", "#");
  await expect(
    page.getByRole("button", { name: "刷新概览", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "添加订阅", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.width).toBeLessThanOrEqual(390);
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).not.toBeVisible();
});

test("one password protects overview and management, and logout revokes access", async ({
  page,
}) => {
  await page.context().clearCookies();
  expect((await page.request.get("/api/dashboard")).status()).toBe(401);
  expect((await page.request.get("/api/settings")).status()).toBe(401);
  expect((await page.request.get("/api/subscriptions")).status()).toBe(401);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的订阅" })).not.toBeVisible();
  await expect(page.getByLabel(/^用户名/)).toHaveCount(0);
  await expect(page.locator("input")).toHaveCount(1);
  await expect(page.getByRole("button")).toHaveCount(1);
  await expect(page.locator("main img")).toHaveCount(0);
  await expect(page.getByText("输入访问密码", { exact: true })).toHaveCount(0);
  await page.getByLabel(/^密码/).fill("incorrect");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("密码不正确");
  await page.getByLabel(/^密码/).fill(password!);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "我的订阅" })).toBeVisible();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByLabel("当前密码")).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/");
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByLabel(/^密码/)).toBeVisible();
  expect((await page.request.get("/api/subscriptions")).status()).toBe(401);
  await page.reload();
  await expect(page.getByLabel(/^密码/)).toBeVisible();
});

test("overview actions edit and delete the selected card without navigation or losing filters", async ({
  page,
  request,
}) => {
  const name = `E2E Direct ${Date.now()}`;
  const renamed = `${name} Updated`;
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "添加订阅", exact: true }).click();
    await page.getByLabel(/^订阅名称/).fill(name);
    await page.getByLabel(/^分类/).fill("测试");
    await page.getByLabel(/^每期费用/).fill("12");
    await page.getByRole("button", { name: "保存订阅", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(name);
    expect(new URL(page.url()).hash).toBe("");
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await expect(page.getByRole("menuitemcheckbox")).toHaveCount(0);
    await expect(page.getByRole("menuitem")).toHaveText(["编辑", "删除"]);
    await page.getByRole("menuitem", { name: "编辑", exact: true }).click();
    await expect(page.getByLabel("订阅名称")).toHaveValue(name);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "取消", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: `${name} 操作` }),
    ).toBeFocused();
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await page.getByRole("menuitem", { name: "编辑", exact: true }).click();
    await page.getByLabel("订阅名称").fill(renamed);
    await page.getByRole("button", { name: "保存订阅", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect(page.getByText(renamed, { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "搜索订阅" })).toHaveValue(
      name,
    );
    expect(new URL(page.url()).hash).toBe("");
    await page.getByRole("button", { name: new RegExp(`^${renamed}：(?:标记为已续费|本期已续费)`)}).click();
    await expect(
      page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]'),
    ).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^${renamed}：(?:标记为已续费|本期已续费)`)}).click();
    await expect(
      page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]'),
    ).toHaveCount(0);
    await page.getByRole("button", { name: `${renamed} 操作` }).click();
    await page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "取消", exact: true })
      .click();
    await expect(page.getByText(renamed, { exact: true })).toBeVisible();
    let failed = false;
    await page.route("**/api/subscriptions/*", async (route) => {
      if (route.request().method() === "DELETE" && !failed) {
        failed = true;
        await route.fulfill({
          status: 500,
          json: { error: "删除失败，请重试" },
        });
      } else await route.continue();
    });
    await page.getByRole("button", { name: `${renamed} 操作` }).click();
    await page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    await expect(
      page.getByRole("alertdialog").getByRole("alert"),
    ).toContainText("删除失败");
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByText(renamed, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "搜索订阅" })).toHaveValue(
      name,
    );
    expect(new URL(page.url()).hash).toBe("");
  } finally {
    const items = await (await request.get("/api/subscriptions")).json();
    for (const item of items.filter(
      (item: { name: string }) => item.name === name || item.name === renamed,
    )) {
      await request.delete(`/api/subscriptions/${item.id}`, {
        headers,
        data: {},
      });
    }
  }
});

test("notification preferences live in subscription settings and use bell status icons", async ({
  page,
  request,
}) => {
  const name = `E2E preferences ${Date.now()}`;
  const response = await request.post("/api/subscriptions", {
    headers,
    data: {
      name,
      category: "测试",
      billing_cycle: "month",
      payment_date: new Date().toLocaleDateString("en-CA"),
      amount: 21,
      currency: "CNY",
      notify_enabled: true,
    },
  });
  expect(response.ok()).toBeTruthy();
  const item = await response.json();
  const preferences = `/api/subscriptions/${item.id}/notifications`;
  const paid = page.locator('[role="progressbar"][aria-valuetext*="本期已续费"]');
  try {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "我的订阅", exact: true }),
    ).toBeVisible();
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(name);
    await expect(
      page.getByRole("button", { name: `${name}：续费提醒已开启`, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: `${name}：续费提醒已开启`, exact: true }).click();
    await expect(page.getByRole("button", { name: `${name}：续费提醒已关闭`, exact: true })).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator('[data-sonner-toast]').filter({hasText: "已关闭续费提醒"})).toBeVisible();
    await page.getByRole("button", { name: `${name}：续费提醒已关闭`, exact: true }).click();
    await expect(page.getByRole("button", { name: `${name}：续费提醒已开启`, exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await expect(page.getByRole("menuitemcheckbox")).toHaveCount(0);
    await expect(
      page.getByRole("menuitemcheckbox", { name: "续费提醒", exact: true }),
    ).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.getByRole("button", {name: `${name}：标记为已续费`, exact: true}).click();
    await expect(paid).toBeVisible();
    await expect(
      page.getByRole("button", { name: `${name}：续费提醒已开启`, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await page.getByRole("menuitem", { name: "编辑", exact: true }).click();
    await expect(
      page.getByRole("switch", { name: "续费提醒", exact: true }),
    ).toBeChecked();
    await page.getByRole("switch", { name: "续费提醒", exact: true }).click();
    await page.getByRole("button", { name: "保存订阅", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: `${name}：续费提醒已关闭`, exact: true }),
    ).toBeVisible();
    await expect(paid).toBeVisible();
    await page.getByRole("button", { name: new RegExp(`^${name}：(?:标记为已续费|本期已续费)`)}).click();
    await expect(paid).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: `${name}：续费提醒已关闭`, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: `${name} 操作` }).click();
    await page.getByRole("menuitem", { name: "编辑", exact: true }).click();
    await expect(
      page.getByRole("switch", { name: "续费提醒", exact: true }),
    ).not.toBeChecked();
    expect(
      (
        await request.put(preferences, { headers, data: { enabled: true } })
      ).ok(),
    ).toBeTruthy();
    await page.getByLabel("每期费用").fill("22");
    await page.getByRole("button", { name: "保存订阅", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page.reload();
    await page.getByRole("textbox", { name: "搜索订阅" }).fill(name);
    await expect(
      page.getByRole("button", { name: `${name}：续费提醒已开启`, exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", {name: `${name}：标记为已续费`, exact: true})).toHaveAttribute("aria-pressed", "false");
  } finally {
    await request.delete(`/api/subscriptions/${item.id}`, {
      headers,
      data: {},
    });
  }
});


test("unsaved settings block navigation and browser unload", async ({page}) => {
  await page.goto("/#settings");
  const title = page.getByLabel(/^时区/);
  await title.fill("Europe/London");
  await page.getByRole("link", {name: "我的订阅", exact: true}).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", {name: "继续编辑", exact: true}).click();
  await expect(title).toHaveValue("Europe/London");
  expect(await page.evaluate(() => { const event = new Event("beforeunload", {cancelable: true}); window.dispatchEvent(event); return event.defaultPrevented; })).toBeTruthy();
  const prompt = page.waitForEvent("dialog");
  const reload = page.evaluate(() => location.reload());
  const dialog = await prompt;
  expect(dialog.type()).toBe("beforeunload");
  await dialog.dismiss();
  await reload;
  await expect(title).toHaveValue("Europe/London");
  await page.evaluate(() => { location.hash = ""; });
  await page.getByRole("button", {name: "放弃更改", exact: true}).click();
  await expect(page.getByRole("heading", {name: "我的订阅", exact: true})).toBeVisible();
  expect(await page.evaluate(() => { const event = new Event("beforeunload", {cancelable: true}); window.dispatchEvent(event); return event.defaultPrevented; })).toBeFalsy();
});

test("subscription date and currency use shadcn selectors and edits can be discarded", async ({page, request}) => {
  await page.goto("/");
  await page.getByRole("button", {name: "添加订阅", exact: true}).click();
  await expect(page.locator('input[type="date"]')).toHaveCount(0);
  await page.getByLabel(/^付款日期/).click();
  await expect(page.locator('[data-slot="calendar"]')).toBeVisible();
  await expect(page.locator('[data-slot="calendar"] select')).toHaveCount(2);
  const calendar = page.locator('[data-slot="calendar"]');
  await calendar.locator('select').filter({has: page.locator('option[value="2000"]')}).selectOption("2000");
  await calendar.locator('select').filter({has: page.locator('option[value="1"]')}).selectOption("1");
  await calendar.getByRole("button", {name: /29/}).click();
  await expect(page.getByLabel(/^付款日期/)).toHaveText("2000-02-29");
  await page.getByLabel(/^币种/).click();
  const labels = await page.getByRole("option").allTextContents();
  const codes = labels.map(label => label.slice(0, 3));
  const catalog = await (await request.get("/api/currencies")).json();
  expect(codes).toEqual(catalog.map((item: {code: string}) => item.code));
  await page.getByRole("option", {name: /^USD/}).click();
  await page.getByLabel(/^订阅名称/).fill("Discard me");
  await page.getByRole("button", {name: "取消", exact: true}).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", {name: "放弃更改", exact: true}).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
