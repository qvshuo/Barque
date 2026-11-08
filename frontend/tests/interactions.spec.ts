import { expect, test } from "@playwright/test";

// Run only against a disposable database: every test replaces the configuration.
test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) => {
    throw error;
  });
  const headers = { "X-Barque-Request": "1" };
  const response = await page.request.post("/api/auth/login", {
    headers,
    data: { password: process.env.BARQUE_TEST_PASSWORD || "browser-test-password" },
  });
  expect(response.ok()).toBeTruthy();
  const restored = await page.request.put("/api/configuration", {
    headers,
    data: {
      version: 1,
      settings: {
        timezone: "Asia/Shanghai",
        check_interval_seconds: 3600,
        remind_before_days: 7,
        notify_url: "",
        reminder_time: "09:00",
      },
      categories: Array.from({ length: 7 }, (_, i) => `分类${i + 1}`),
      subscriptions: Array.from({ length: 7 }, (_, i) => ({
        id: (i + 1).toString(16).padStart(32, "0"),
        name: `订阅${i + 1}`,
        category: `分类${i + 1}`,
        billing_cycle: "month",
        payment_date: "2024-01-31",
        amount: 70 - i * 10,
        currency: "CNY",
        notify_enabled: true,
      })),
    },
  });
  expect(restored.ok()).toBeTruthy();
  await page.goto("/");
});

test("其他扇区和图例切换所有前五名以外分类", async ({ page }) => {
  const other = page.getByRole("button", { name: /^其他/ });
  await other.click();
  await expect(page.getByRole("region", { name: "分类1", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "分类6", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "分类7", exact: true })).toBeVisible();
  await other.click();
  await expect(page.getByRole("region", { name: "分类1", exact: true })).toBeVisible();
  await page.locator(".recharts-pie-sector").last().click();
  await expect(other).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("combobox", { name: "筛选分类" })).toContainText("其他");
});

test("Base Select 键盘选择和首页续费标记", async ({ page }) => {
  const select = page.getByRole("combobox", { name: "筛选分类" });
  await expect(select).toContainText("全部分类");
  await select.focus();
  await page.keyboard.press("ArrowDown");
  await page.getByRole("option", { name: "分类2", exact: true }).click();
  await expect(select).toContainText("分类2");
  await expect(select).toBeFocused();
  const renew = page.getByRole("button", { name: "订阅2：标记为已续费" });
  await renew.click();
  await expect(page.getByRole("button", { name: "订阅2：已付费，点击撤销" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "订阅2：已付费，点击撤销" }).click();
  await expect(renew).toHaveAttribute("aria-pressed", "false");
});

test("日期选择器、Switch、草稿导航及格式合法的未知币种保存", async ({ page }) => {
  await page.getByRole("link", { name: "管理订阅", exact: true }).click();
  const group = page.getByRole("group", { name: "订阅1", exact: true });
  const cycle = group.getByRole("combobox", { name: "计费周期" });
  await expect(cycle).toContainText("每月");
  await cycle.click();
  await page.getByRole("option", { name: "每季度", exact: true }).click();
  await expect(cycle).toContainText("每季度");
  const date = group.getByRole("button", { name: "付款日期" });
  await date.click();
  await expect(page.locator('[data-slot="popover-content"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(date).toBeFocused();
  await date.click();
  await page
    .locator('[data-slot="popover-content"]')
    .getByRole("button", { name: /2024年1月30/ })
    .click();
  await expect(date).toContainText("2024-01-30");
  await expect(page.locator('[data-slot="popover-content"]')).toHaveCount(0);
  const toggle = group.getByRole("switch", { name: "续费提醒" });
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await group.getByRole("combobox", { name: "币种" }).fill("ZZZ");
  await page.getByRole("link", { name: "设置", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "继续编辑" })).toBeFocused();
  await dialog.getByRole("button", { name: "继续编辑" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("尚未保存")).toHaveCount(0);
  const response = await page.request.get("/api/subscriptions");
  expect((await response.json())[0].currency).toBe("ZZZ");
});

test("Bark 使用未保存地址并明确反馈成功与失败", async ({ page }) => {
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByLabel("Bark 推送地址", { exact: true }).fill("https://example.com/unsaved-key");
  await page.route("**/api/test-notification", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      notify_url: "https://example.com/unsaved-key",
    });
    await route.fulfill({ json: { message: "测试通知已发送" } });
  });
  await page.getByRole("button", { name: "发送测试通知" }).click();
  await expect(page.getByText("测试通知已发送，请查看你的设备")).toBeVisible();
  await page.route("**/api/test-notification", (route) =>
    route.fulfill({ status: 502, json: { error: "发送失败，请检查 Bark 地址和网络连接" } }),
  );
  await page.getByRole("button", { name: "发送测试通知" }).click();
  await expect(page.getByText("发送失败，请检查 Bark 地址和网络连接")).toBeVisible();
  expect((await (await page.request.get("/api/settings")).json()).notify_url).toBe("");
});

test("JSON 配置通过原有导入导出入口备份恢复", async ({ page }) => {
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("button", { name: /完整数据库/ })).toHaveCount(0);
  const jsonDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出", exact: true }).click();
  const configPath = await (await jsonDownload).path();
  const jsonChooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "导入", exact: true }).click();
  await (await jsonChooser).setFiles(configPath!);
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText("配置已导入并生效")).toBeVisible();
});

test("JSON 导入成功后清除上一次保存错误", async ({ page }) => {
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByRole("textbox", { name: "时区", exact: true }).fill("UTC");
  await page.route("**/api/settings", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({ status: 400, json: { error: "设置保存失败" } });
    } else {
      await route.continue();
    }
  });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("设置保存失败")).toBeVisible();
  await page.getByRole("textbox", { name: "时区", exact: true }).fill("Asia/Shanghai");
  const config = await (await page.request.get("/api/configuration")).json();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "导入", exact: true }).click();
  await (
    await chooser
  ).setFiles({
    name: "config.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(config)),
  });
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText("配置已导入并生效")).toBeVisible();
  await expect(page.getByText("设置保存失败")).toHaveCount(0);
});
