const page = document.body.dataset.page;
const form = document.querySelector("#management, #settings-form");
let saved = "",
  busy = false,
  noticeTimer;

function feedback(message, error = false) {
  const box = document.querySelector("#feedback");
  box.textContent = message;
  box.hidden = false;
  box.toggleAttribute("data-error", error);
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    box.hidden = true;
  }, 6000);
}

function requireLogin() {
  document.querySelector("#reauth-open").hidden = false;
  const dialog = document.querySelector("#reauth");
  if (!dialog.open) dialog.showModal();
}
async function api(path, method = "GET", data = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      signal: AbortSignal.timeout(30000),
      headers: method === "GET" ? {} : {
        "Content-Type": "application/json",
        "X-Barque-Request": "1"
      },
      body: method === "GET" ? undefined : JSON.stringify(data),
    });
  } catch (error) {
    throw new Error(
      error.name === "TimeoutError" ?
      "请求超时，请刷新页面确认后重试" :
      "网络连接失败，请检查连接后重试",
    );
  }
  if (response.status === 401 && !path.startsWith("/auth/")) {
    requireLogin();
    throw new Error("请重新登录后保存");
  }
  if (!response.ok) {
    const value = await response.json().catch(() => null);
    throw new Error(value?.error || `请求失败 (${response.status})`);
  }
  return response.status === 204 ? undefined : response.json();
}

function confirmAction(title, description, accept = "放弃更改", cancel = "继续编辑") {
  const dialog = document.querySelector("#confirm");
  if (dialog.open) return Promise.resolve(false);
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-description").textContent = description;
  const ok = document.querySelector("#confirm-ok"),
    no = document.querySelector("#confirm-cancel");
  ok.textContent = accept;
  no.textContent = cancel;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    const close = () => {
      ok.onclick = no.onclick = null;
      resolve(dialog.returnValue === "ok");
    };
    dialog.addEventListener("close", close, {
      once: true
    });
    ok.onclick = () => dialog.close("ok");
    no.onclick = () => dialog.close("cancel");
    dialog.showModal();
    no.focus();
  });
}

function groups() {
  return [...document.querySelectorAll("#groups > .editor-group")].map((group) => {
    const name = group.querySelector("[name=category]").value;
    return {
      name,
      subscriptions: [...group.querySelectorAll(".editor")].map((row) => {
        const values = Object.fromEntries(fieldValues(row));
        return {
          ...values,
          id: row.dataset.id,
          category: name,
          amount: Number(values.amount),
          notify_enabled: row.querySelector("[name=notify_enabled]").checked,
        };
      }),
    };
  });
}
// A fieldset cannot be passed to FormData; read its native form controls directly.
function fieldValues(root) {
  return [...root.querySelectorAll("input[name],select[name]")]
    .filter((input) => input.name !== "notify_enabled")
    .map((input) => [input.name, input.value]);
}

function settings() {
  const value = Object.fromEntries(fieldValues(form));
  value.remind_before_days = Number(value.remind_before_days);
  value.check_interval_seconds = Number(value.check_interval_seconds);
  return value;
}

function snapshot() {
  return form ? JSON.stringify(page === "subscriptions" ? groups() : settings()) : "";
}

function dirty() {
  return snapshot() !== saved;
}

function sync() {
  if (!form) return;
  const changed = dirty();
  if (page === "subscriptions") labels();
  form.querySelector(".savebar").style.visibility = changed ? "visible" : "hidden";
  form.querySelector(".dirty").hidden = !changed;
  form.querySelector(".save").disabled = busy || !changed;
  if (page === "settings") {
    document.querySelector("#import").disabled = document.querySelector("#export").disabled =
      busy || changed;
    document.querySelector("#test-notification").disabled =
      busy || !form.elements.notify_url.value.trim();
  }
}
async function leave(action) {
  if (busy) return;
  if (!dirty() || (await confirmAction("放弃未保存的更改？", "离开后，这些更改将不会保存。"))) {
    const previous = saved;
    saved = snapshot();
    try {
      await action();
      return true;
    } catch (error) {
      saved = previous;
      throw error;
    }
  }
  return false;
}
const confirmation = document.querySelector("#confirm");
confirmation.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const first = document.querySelector("#confirm-cancel"),
    last = document.querySelector("#confirm-ok");
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
window.addEventListener("beforeunload", (event) => {
  if (dirty() || busy) {
    event.preventDefault();
    event.returnValue = "";
  }
});
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[href]");
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button)
    return;
  if ((dirty() || busy) && link.origin === location.origin) {
    event.preventDefault();
    void leave(() => location.assign(link.href));
  }
});
saved = snapshot();
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    if (!dirty()) location.reload();
    else sync();
  }
});
document.querySelector("#logout")?.addEventListener("click", async () => {
  try {
    await leave(async () => {
      busy = true;
      try {
        await api("/auth/logout", "POST");
      } finally {
        busy = false;
      }
      location.reload();
    });
  } catch (error) {
    feedback(error.message, true);
  }
});
document.querySelector("#login-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const login = event.currentTarget,
    button = login.querySelector("button"),
    errorBox = login.querySelector(".error");
  button.disabled = true;
  button.textContent = "登录中…";
  errorBox.hidden = true;
  try {
    await api("/auth/login", "POST", {
      password: login.elements.password.value
    });
    busy = false;
    location.reload();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    busy = false;
    button.disabled = false;
    button.textContent = "登录";
  }
});
const reauth = document.querySelector("#reauth");
document.querySelector("#reauth-open").addEventListener("click", requireLogin);
document.querySelector("#reauth-cancel").addEventListener("click", () => reauth.close());
document.querySelector("#reauth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const login = event.currentTarget,
    button = login.querySelector("[type=submit]"),
    errorBox = login.querySelector(".error");
  if (button.disabled) return;
  button.disabled = true;
  errorBox.hidden = true;
  try {
    await api("/auth/login", "POST", {
      password: login.elements.password.value
    });
    login.reset();
    reauth.close();
    document.querySelector("#reauth-open").hidden = true;
    window.dispatchEvent(new Event("barque:authenticated"));
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
});
reauth.addEventListener("close", () => document.querySelector("#reauth-form").reset());
if (form) {
  saved = snapshot();
  form.addEventListener("input", (event) => {
    if (event.target.name === "currency") event.target.value = event.target.value
      .toUpperCase();
    sync();
  });
  form.addEventListener("change", sync);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !dirty()) return;
    busy = true;
    const fieldset = form.querySelector("fieldset"),
      button = form.querySelector(".save"),
      errorBox = form.querySelector(".error");
    const payload =
      page === "subscriptions" ? {
        categories: groups(),
        revision: form.dataset.revision
      } :
      settings();
    fieldset.disabled = true;
    button.textContent = "保存中…";
    button.disabled = true;
    errorBox.hidden = true;
    try {
      const result = await api(
        page === "subscriptions" ? "/subscription-groups" : "/settings",
        "PUT",
        payload,
      );
      if (page === "subscriptions") applyGroups(result);
      else applySettings(result);
      fieldset.disabled = false;
      saved = snapshot();
      form.querySelector(".reload").hidden = true;
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      if (page === "subscriptions") form.querySelector(".reload").hidden = false;
    } finally {
      fieldset.disabled = false;
      busy = false;
      button.textContent = "保存";
      sync();
    }
  });
  form
    .querySelector(".reload")
    .addEventListener("click", () => void leave(() => location.reload()));
  sync();
}

function labels() {
  for (const entry of document.querySelectorAll("#groups > .editor-group, .editor")) {
    const isGroup = entry.classList.contains("editor-group");
    const value =
      entry.querySelector(isGroup ? "[name=category]" : "[name=name]").value ||
      (isGroup ? "新分类" : "新订阅");
    entry.setAttribute("aria-label", value);
    for (const [action, label] of [
        ["up", "上移"],
        ["down", "下移"],
        ["delete", "删除"],
      ])
      entry
      .querySelector(`.order [data-action=${action}]`)
      .setAttribute("aria-label", `${value}${isGroup ? " 分类" : ""} ${label}`);
  }
}

function orderActions() {
  for (const container of document.querySelectorAll("#groups, .editors")) {
    [...container.children].forEach((entry, index, entries) => {
      const actions = entry.querySelector(".order");
      if (!actions) return;
      actions.querySelector("[data-action=up]").disabled = index === 0;
      actions.querySelector("[data-action=down]").disabled = index === entries.length - 1;
    });
  }
}

function applyGroups(result) {
  form.dataset.revision = result.revision;
  [...document.querySelectorAll("#groups > .editor-group")].forEach((group, i) => {
    const value = result.categories[i];
    group.querySelector("[name=category]").value = value.name;
    [...group.querySelectorAll(".editor")].forEach((row, j) => {
      const item = value.subscriptions[j];
      row.dataset.id = item.id;
      for (const input of row.querySelectorAll("[name]")) {
        if (input.type === "checkbox") input.checked = item[input.name];
        else input.value = item[input.name];
      }
    });
  });
  orderActions();
}
if (page === "subscriptions") {
  orderActions();
  const names = new Intl.DisplayNames(["zh-CN"], {
    type: "currency"
  });
  for (const option of document.querySelectorAll("#currencies option"))
    option.textContent = names.of(option.value) || option.textContent;
  form.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || busy) return;
    const action = button.dataset.action;
    if (action === "add-group" || action === "add-subscription") {
      const fragment = document
        .querySelector(action === "add-group" ? "#group-template" :
          "#subscription-template")
        .content.cloneNode(true);
      const root = fragment.firstElementChild;
      if (action === "add-subscription") {
        root.dataset.id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
          byte.toString(16).padStart(2, "0"),
        ).join("");
        const today = new Date();
        root.querySelector("[name=payment_date]").value =
          `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      }
      const target =
        action === "add-group" ?
        document.querySelector("#groups") :
        button.closest(".editor-group").querySelector(".editors");
      target.append(fragment);
      root.querySelector("input").focus();
    } else {
      const entry = button.closest(".editor, .editor-group");
      if (action === "delete") entry.remove();
      if (action === "up" && entry.previousElementSibling)
        entry.previousElementSibling.before(entry);
      if (action === "down" && entry.nextElementSibling) entry.nextElementSibling.after(
        entry);
    }
    orderActions();
    sync();
  });
}

function applySettings(result) {
  for (const [key, value] of Object.entries(result))
    if (form.elements[key]) form.elements[key].value = value;
}
if (page === "settings") {
  document.querySelector("#test-notification").addEventListener("click", async (event) => {
    if (busy) return;
    const url = form.elements.notify_url.value,
      button = event.currentTarget;
    busy = true;
    form.querySelector("fieldset").disabled = true;
    button.textContent = "发送中…";
    // Keep the saved snapshot intact when temporarily disabling controls.
    form.querySelector(".save").disabled = true;
    try {
      await api("/test-notification", "POST", {
        notify_url: url
      });
      feedback("已发送");
    } catch (error) {
      feedback(error.message, true);
    } finally {
      busy = false;
      form.querySelector("fieldset").disabled = false;
      button.textContent = "测试通知";
      sync();
    }
  });
  document.querySelector("#export").addEventListener("click", async () => {
    try {
      const data = await api("/configuration"),
        url = URL.createObjectURL(
          new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json"
          }),
        );
      const link = document.createElement("a");
      link.href = url;
      link.download = "barque-config.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      feedback(error.message, true);
    }
  });
  const input = document.querySelector("#import-file");
  document.querySelector("#import").addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = "";
    if (!file || busy) return;
    let value;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error();
      value = JSON.parse(await file.text());
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    } catch {
      feedback("无法读取配置文件，请选择有效的 JSON 文件（不超过 2 MB）", true);
      return;
    }
    if (
      !(await confirmAction(
        "导入并覆盖配置？",
        "当前应用设置和订阅将被文件中的配置覆盖。此操作无法撤销。",
        "确认导入",
        "取消",
      ))
    )
      return;
    busy = true;
    form.querySelector("fieldset").disabled = true;
    form.querySelector(".save").disabled = true;
    try {
      applySettings(await api("/configuration", "PUT", value));
      form.querySelector("fieldset").disabled = false;
      saved = snapshot();
      form.querySelector(".error").hidden = true;
      feedback("配置已导入并生效");
    } catch (error) {
      feedback(error.message, true);
    } finally {
      busy = false;
      form.querySelector("fieldset").disabled = false;
      sync();
    }
  });
}
if (page === "home") {
  function formatMoney() {
    for (const element of document.querySelectorAll("[data-money]")) {
      const value = Number(element.dataset.money),
        currency = element.dataset.currency || "CNY";
      const compact = element.hasAttribute("data-compact") && Math.abs(value) >= 1000000;
      element.textContent = new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency,
        notation: compact ? "compact" : "standard"
      }).format(value);
    }
  }

  function times() {
    for (const time of document.querySelectorAll("time")) {
      const value = new Date(time.textContent);
      if (!Number.isNaN(value.valueOf())) time.textContent = value.toLocaleString("zh-CN");
    }
  }
  let lastMarkup = null;
  let refreshing = null,
    pending = false,
    timer;
  async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      const response = await fetch("/", {
        headers: {
          "X-Barque-Fragment": "dashboard"
        },
        signal: AbortSignal.timeout(30000),
      });
      if (response.status === 401) {
        requireLogin();
        throw new Error("请重新登录");
      }
      if (!response.ok) throw new Error("无法加载订阅，请刷新后重试");
      const markup = await response.text();
      if (markup === lastMarkup) return;
      const doc = new DOMParser().parseFromString(markup, "text/html"),
        next = doc.querySelector("#dashboard");
      if (!next) {
        requireLogin();
        throw new Error("请重新登录");
      }
      const scroll = window.scrollY;
      const focused = document.activeElement?.closest(".renew")?.dataset;
      document.querySelector("#dashboard").replaceWith(next);
      document.querySelectorAll(".renew").forEach((control) => {
        control.disabled = pending;
      });
      times();
      formatMoney();
      if (focused) {
        [...document.querySelectorAll(".renew")]
          .find((control) => control.dataset.id === focused.id &&
            control.dataset.payment === focused.payment &&
            control.dataset.renewal === focused.renewal)?.focus({ preventScroll: true });
      }
      window.scrollTo({
        top: scroll,
        behavior: "instant"
      });
      lastMarkup = markup;
    })().finally(() => {
      refreshing = null;
    });
    return refreshing;
  }
  times();
  formatMoney();
  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".renew");
    if (!button || pending) return;
    const original = {
      id: button.dataset.id,
      payment: button.dataset.payment,
      renewal: button.dataset.renewal,
      pressed: button.getAttribute("aria-pressed"),
    };
    let completed = false;
    pending = true;
    document.querySelectorAll(".renew").forEach((control) => {
      control.disabled = true;
    });
    try {
      if (refreshing) await refreshing.catch(() => {});
      const current = [...document.querySelectorAll(".renew")]
        .find((control) => control.dataset.id === original.id);
      if (!current || current.dataset.payment !== original.payment ||
        current.dataset.renewal !== original.renewal ||
        current.getAttribute("aria-pressed") !== original.pressed) {
        throw new Error("订阅状态已更新，请重新操作");
      }
      await api("/renewal-status", "PUT", {
        subscription_id: current.dataset.id,
        payment_date: current.dataset.payment,
        renewal_date: current.dataset.renewal,
        renewed: current.getAttribute("aria-pressed") !== "true",
      });
      completed = true;
      // The write succeeded; a failed refresh must not invite another submission.
      await refresh().catch(() => {});
    } catch (error) {
      feedback(error.message, true);
    } finally {
      pending = false;
      document.querySelectorAll(".renew").forEach((control) => {
        control.disabled = false;
        if (completed && control.dataset.id === original.id &&
          control.dataset.payment === original.payment &&
          control.dataset.renewal === original.renewal) {
          control.focus({ preventScroll: true });
        }
      });
    }
  });

  function schedule() {
    if (document.hidden || pending) return;
    clearTimeout(timer);
    timer = setTimeout(() => refresh().catch(() => {}), 100);
  }
  window.addEventListener("barque:authenticated", schedule);
  setInterval(schedule, 60000);
  window.addEventListener("focus", schedule);
  document.addEventListener("visibilitychange", schedule);
}
