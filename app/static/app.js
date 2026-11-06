document.addEventListener("DOMContentLoaded", function () {
  // 三点菜单：开合
  function closeAllMenus(except) {
    document.querySelectorAll("[data-item-menu] .menu-panel").forEach(function (panel) {
      if (!except || panel !== except) {
        panel.hidden = true;
        var t = panel.closest("[data-item-menu]").querySelector(".menu-trigger");
        if (t) t.setAttribute("aria-expanded", "false");
      }
    });
  }
  document.querySelectorAll("[data-item-menu] .menu-trigger").forEach(function (trigger) {
    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      var panel = trigger.closest("[data-item-menu]").querySelector(".menu-panel");
      var isOpen = !panel.hidden;
      closeAllMenus(panel);
      panel.hidden = isOpen;
      trigger.setAttribute("aria-expanded", String(!isOpen));
    });
  });
  document.addEventListener("click", function () { closeAllMenus(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAllMenus(); });

  // 菜单里「标记/取消已续费」提交
  document.querySelectorAll("[data-renewal-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = form.querySelector(".menu-item");
      if (!button || button.disabled) return;
      button.disabled = true;
      fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: new FormData(form),
      })
        .then(function (response) {
          if (!response.ok) throw new Error("toggle failed");
          return response.json();
        })
        .then(function (data) {
          var card = form.closest(".subscription-item");
          // 状态徽标
          var chip = card.querySelector(".status-chip");
          if (chip) {
            chip.textContent = data.status_label;
            chip.className = "status-chip status-" + data.status_kind;
          }
          // 菜单项图标/文案切换（不拼 innerHTML）
          var markIcon = button.querySelector(".menu-icon-mark");
          var unmarkIcon = button.querySelector(".menu-icon-unmark");
          var textNode = button.querySelector(".menu-item-text");
          if (markIcon) markIcon.hidden = !!data.renewed;
          if (unmarkIcon) unmarkIcon.hidden = !data.renewed;
          if (textNode) textNode.textContent = data.action_label;
          // 倒计时主视觉同步换色
          var countdown = card.querySelector(".item-countdown");
          if (countdown) {
            countdown.className = "item-countdown status-" + data.status_kind;
          }
          card.classList.toggle("is-renewed", !!data.renewed);
          button.disabled = false;
          closeAllMenus();
        })
        .catch(function () {
          button.disabled = false;
        });
    });
  });
});
