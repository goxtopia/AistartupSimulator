/** Shared UI helpers: toasts, modal, formatting. */

export function $(sel, root = document) {
  return root.querySelector(sel);
}
export function $all(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

export function money(n) {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function toast(msg, type = "ok") {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    el.style.transition = "0.3s";
    setTimeout(() => el.remove(), 300);
  }, 2800);
}

export function showModal({ title, body, footer }) {
  const modal = $("#modal");
  $("#modal-title").textContent = title || "";
  const b = $("#modal-body");
  if (typeof body === "string") b.innerHTML = body;
  else {
    b.innerHTML = "";
    if (body) b.appendChild(body);
  }
  const f = $("#modal-footer");
  f.innerHTML = "";
  if (footer) {
    if (typeof footer === "string") f.innerHTML = footer;
    else f.appendChild(footer);
  }
  modal.classList.remove("hidden");
  return new Promise((resolve) => {
    const close = (val) => {
      modal.classList.add("hidden");
      resolve(val);
    };
    $("#modal-close").onclick = () => close(null);
    modal.onclick = (e) => {
      if (e.target === modal) close(null);
    };
    modal._close = close;
  });
}

export function closeModal(val = null) {
  const modal = $("#modal");
  if (modal._close) modal._close(val);
  else modal.classList.add("hidden");
}

export function showView(id) {
  $all(".view").forEach((v) => v.classList.remove("active"));
  const el = $(`#view-${id}`);
  if (el) el.classList.add("active");
}

export function setTab(name) {
  $all(".sidebar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $all(".content .tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${name}`));
  const activeButton = $(`.sidebar button[data-tab="${name}"]`);
  if (activeButton) {
    activeButton.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }
  const content = $(".content");
  if (content) content.scrollTop = 0;
}

export function bindSeg(root, onChange) {
  const buttons = $all("button", root);
  buttons.forEach((b) => {
    b.onclick = () => {
      buttons.forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      onChange(b.dataset.v);
    };
  });
  const on = buttons.find((b) => b.classList.contains("on"));
  return () => (on ? on.dataset.v : buttons[0]?.dataset.v);
}
