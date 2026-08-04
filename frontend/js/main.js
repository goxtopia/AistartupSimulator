import { api, setGameId, getGameId } from "./api.js";
import { mountLogo, renderFounderAvatar } from "./logo.js";
import {
  $,
  $all,
  money,
  toast,
  showModal,
  closeModal,
  showView,
  setTab,
  bindSeg,
} from "./ui.js";

const state = {
  catalog: null,
  game: null,
  setup: {
    step: 0,
    founder_name: "",
    founder_gender: "male",
    founder_background: "industrialist",
    country: "usa",
    company_name: "",
    logo: {
      shape: "circle",
      icon: "brain",
      layout: "icon_center",
      palette: "midnight",
      monogram: "",
    },
  },
  researchCat: "model",
};

// ---------- boot ----------
async function boot() {
  try {
    state.catalog = await api.catalog();
  } catch (e) {
    toast("无法加载配置: " + e.message, "err");
    return;
  }
  wireHome();
  wireSetup();
  wireLoad();
  wireGame();
  mountLogo($("#home-logo"), state.setup.logo, state.catalog.logo_parts, 96);

  // try restore session
  if (getGameId()) {
    try {
      const res = await api.state();
      applyState(res.state);
      showView("game");
      return;
    } catch {
      setGameId(null);
    }
  }
  showView("home");
}

// ---------- home ----------
function wireHome() {
  $("#btn-new-game").onclick = () => {
    state.setup.step = 0;
    renderSetup();
    showView("setup");
  };
  $("#btn-load-game").onclick = async () => {
    await renderSaves();
    showView("load");
  };
}

// ---------- setup wizard ----------
function wireSetup() {
  $("#setup-back").onclick = () => showView("home");
  $("#setup-prev").onclick = () => {
    state.setup.step = Math.max(0, state.setup.step - 1);
    renderSetup();
  };
  $("#setup-next").onclick = async () => {
    if (!validateStep(state.setup.step)) return;
    if (state.setup.step >= 3) {
      await createGame();
      return;
    }
    state.setup.step += 1;
    renderSetup();
  };
  bindSeg($("#founder-gender"), (v) => {
    state.setup.founder_gender = v;
    renderFounderAvatar($("#founder-avatar"), v);
  });
  $("#founder-name").oninput = (e) => (state.setup.founder_name = e.target.value.trim());
  $("#company-name").oninput = (e) => {
    state.setup.company_name = e.target.value.trim();
    if (!state.setup.logo.monogram && e.target.value) {
      state.setup.logo.monogram = e.target.value.slice(0, 2).toUpperCase();
      $("#logo-mono").value = state.setup.logo.monogram;
      refreshLogoPreview();
    }
  };

  ["shape", "icon", "layout", "palette"].forEach((k) => {
    $(`#logo-${k}`).onchange = (e) => {
      state.setup.logo[k] = e.target.value;
      refreshLogoPreview();
    };
  });
  $("#logo-mono").oninput = (e) => {
    state.setup.logo.monogram = e.target.value;
    refreshLogoPreview();
  };
}

function validateStep(step) {
  const s = state.setup;
  if (step === 0) {
    if (!s.founder_name) {
      toast("请填写创始人姓名", "err");
      return false;
    }
    if (!s.founder_background) {
      toast("请选择背景", "err");
      return false;
    }
  }
  if (step === 1 && !s.country) {
    toast("请选择国家", "err");
    return false;
  }
  if (step === 2 && !s.company_name) {
    toast("请填写公司名称", "err");
    return false;
  }
  return true;
}

function renderSetup() {
  const step = state.setup.step;
  $all(".setup-step").forEach((el) => el.classList.toggle("hidden", Number(el.dataset.step) !== step));
  $all(".setup-steps span").forEach((el) => el.classList.toggle("on", Number(el.dataset.step) === step));
  $("#setup-prev").disabled = step === 0;
  $("#setup-next").textContent = step === 3 ? "创立公司" : "下一步";

  if (step === 0) renderBackgrounds();
  if (step === 1) renderCountries();
  if (step === 2) {
    fillLogoSelects();
    refreshLogoPreview();
    $("#company-name").value = state.setup.company_name;
  }
  if (step === 3) renderConfirm();
  renderFounderAvatar($("#founder-avatar"), state.setup.founder_gender);
  $("#founder-name").value = state.setup.founder_name;
}

function renderBackgrounds() {
  const list = $("#bg-list");
  const bgs = state.catalog.backgrounds || {};
  list.innerHTML = "";
  Object.values(bgs).forEach((bg) => {
    if (bg.available === false) return;
    const el = document.createElement("button");
    el.type = "button";
    el.className = "choice" + (state.setup.founder_background === bg.id ? " on" : "");
    el.innerHTML = `<div class="t">${bg.name}</div><div class="d">${bg.description}</div>
      <div class="tags">
        <span class="tag">技术 ${bg.stats?.tech_skill ?? "-"}</span>
        <span class="tag">商业 ${bg.stats?.business_skill ?? "-"}</span>
        <span class="tag good">资金加成</span>
        <span class="tag warn">政府关系+</span>
      </div>`;
    el.onclick = () => {
      state.setup.founder_background = bg.id;
      renderBackgrounds();
    };
    list.appendChild(el);
  });
}

function renderCountries() {
  const list = $("#country-list");
  list.innerHTML = "";
  Object.values(state.catalog.countries || {}).forEach((c) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "country-card" + (state.setup.country === c.id ? " on" : "");
    el.style.setProperty("--c", c.color || "#38bdf8");
    const diff = Number(c.difficulty || 1);
    el.innerHTML = `<div class="flag">${c.flag_emoji || ""}</div>
      <div class="nm">${c.name} <span class="muted">${c.name_en || ""}</span></div>
      <div class="desc">${c.description || ""}</div>
      <div class="diff">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= diff ? "on" : ""}"></i>`).join("")}</div>
      <div class="tags mt">
        <span class="tag">资金 ×${c.starting_capital_multiplier}</span>
        <span class="tag">人才 ×${c.talent_pool_size}</span>
      </div>`;
    el.onclick = () => {
      state.setup.country = c.id;
      renderCountries();
    };
    list.appendChild(el);
  });
}

function fillLogoSelects() {
  const parts = state.catalog.logo_parts || {};
  fillSelect(
    $("#logo-shape"),
    (parts.shapes || []).map((x) => [x.id, x.name]),
    state.setup.logo.shape
  );
  fillSelect(
    $("#logo-icon"),
    (parts.icons || []).map((x) => [x.id, x.name]),
    state.setup.logo.icon
  );
  fillSelect(
    $("#logo-layout"),
    (parts.layouts || []).map((x) => [x.id, x.name]),
    state.setup.logo.layout
  );
  fillSelect(
    $("#logo-palette"),
    (parts.palettes || []).map((x) => [x.id, x.id]),
    state.setup.logo.palette
  );
  $("#logo-mono").value = state.setup.logo.monogram || "";
}

function fillSelect(sel, pairs, value) {
  sel.innerHTML = pairs.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
  if (value) sel.value = value;
}

function refreshLogoPreview() {
  const parts = state.catalog.logo_parts;
  mountLogo($("#logo-preview"), state.setup.logo, parts, 160);
  mountLogo($("#home-logo"), state.setup.logo, parts, 96);
}

function renderConfirm() {
  const s = state.setup;
  const c = state.catalog.countries[s.country] || {};
  const bg = state.catalog.backgrounds[s.founder_background] || {};
  mountLogo($("#confirm-logo"), s.logo, state.catalog.logo_parts, 96);
  $("#confirm-company").textContent = s.company_name || "—";
  $("#confirm-summary").innerHTML = `
    <li><span>创始人</span><span>${s.founder_name}（${genderLabel(s.founder_gender)}）</span></li>
    <li><span>背景</span><span>${bg.name || s.founder_background}</span></li>
    <li><span>国家</span><span>${c.flag_emoji || ""} ${c.name || s.country}</span></li>
    <li><span>难度</span><span>${"★".repeat(c.difficulty || 1)}</span></li>
  `;
}

function genderLabel(g) {
  return { male: "男", female: "女", other: "其他" }[g] || g;
}

async function createGame() {
  const s = state.setup;
  try {
    const res = await api.newGame({
      company_name: s.company_name,
      country: s.country,
      founder_name: s.founder_name,
      founder_gender: s.founder_gender,
      founder_background: s.founder_background,
      logo: s.logo,
    });
    setGameId(res.state.game_id);
    applyState(res.state);
    toast("公司成立！");
    showView("game");
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---------- load ----------
function wireLoad() {
  $("#load-back").onclick = () => showView("home");
}

async function renderSaves() {
  const list = $("#save-list");
  list.innerHTML = "<p class='muted'>加载中…</p>";
  try {
    const res = await api.saves();
    const saves = res.saves || [];
    if (!saves.length) {
      list.innerHTML = "<p class='muted'>暂无存档</p>";
      return;
    }
    list.innerHTML = "";
    saves.forEach((sv) => {
      const el = document.createElement("div");
      el.className = "save-item";
      const date = sv.saved_at ? new Date(sv.saved_at * 1000).toLocaleString() : "";
      el.innerHTML = `<div class="info">
          <div class="t">${sv.label || sv.company_name || sv.slot}</div>
          <div class="s">Day ${sv.day} · ${money(sv.capital)} · ${date}</div>
        </div>
        <button class="btn primary sm">读取</button>
        <button class="btn danger sm">删除</button>`;
      el.querySelector(".primary").onclick = async () => {
        try {
          const r = await api.load(sv.slot);
          setGameId(r.state.game_id);
          applyState(r.state);
          toast("读档成功");
          showView("game");
        } catch (e) {
          toast(e.message, "err");
        }
      };
      el.querySelector(".danger").onclick = async () => {
        try {
          await api.deleteSave(sv.slot);
          toast("已删除");
          renderSaves();
        } catch (e) {
          toast(e.message, "err");
        }
      };
      list.appendChild(el);
    });
  } catch (e) {
    list.innerHTML = `<p class="muted">${e.message}</p>`;
  }
}

// ---------- game ----------
function wireGame() {
  $all(".sidebar button").forEach((b) => {
    b.onclick = () => {
      setTab(b.dataset.tab);
      renderAll();
    };
  });
  $("#btn-adv-1").onclick = () => advance(1);
  $("#btn-adv-7").onclick = () => advance(7);
  $("#btn-adv-30").onclick = () => advance(30);
  $("#btn-save").onclick = () => doSave();
  $("#btn-menu").onclick = () => {
    setGameId(null);
    state.game = null;
    showView("home");
  };
  $("#btn-refresh-hr").onclick = async () => {
    try {
      const r = await api.refreshHr();
      applyAction(r);
    } catch (e) {
      toast(e.message, "err");
    }
  };
  bindSeg($("#research-cat"), (v) => {
    state.researchCat = v;
    renderResearch();
  });
  $("#btn-create-ds").onclick = createDataset;
  $("#btn-start-train").onclick = startTraining;
  $("#btn-distill").onclick = startDistill;
  $("#tr-scratch").onchange = (e) => {
    $("#tr-base-wrap").classList.toggle("hidden", e.target.checked);
  };
  $("#di-source").onchange = fillDistillTeachers;
}

async function advance(days) {
  try {
    const r = await api.advance(days);
    applyState(r.state);
    const evs = r.state.tick_events || [];
    if (evs.length) {
      // Prioritize poach alerts
      const poaches = evs.filter((e) => e.type === "poach_success");
      const rest = evs.filter((e) => e.type !== "poach_success");
      poaches.forEach((e) => e.msg && toast(e.msg, "err"));
      rest.slice(-3).forEach((e) => e.msg && toast(e.msg));
    }
    // auto jump to events if queue
    const q = r.state.systems?.events?.queue || [];
    if (q.length) {
      setTab("events");
      renderEvents();
      toast(`有 ${q.length} 个事件待处理`, "ok");
    }
  } catch (e) {
    toast(e.message, "err");
  }
}

async function doSave() {
  const name = state.game?.company?.name || "save";
  const slot = prompt("存档名", name.replace(/\s+/g, "_").slice(0, 24));
  if (!slot) return;
  try {
    await api.save(slot, name);
    toast("存档成功: " + slot);
  } catch (e) {
    toast(e.message, "err");
  }
}

function applyAction(r) {
  if (r.message) toast(r.message, r.ok ? "ok" : "err");
  if (r.state) applyState(r.state);
}

function applyState(g) {
  state.game = g;
  renderAll();
}

function renderAll() {
  if (!state.game) return;
  renderTopbar();
  renderDashboard();
  renderHR();
  renderResearch();
  renderCompute();
  renderTraining();
  renderModels();
  renderMarket();
  renderEvents();
  renderLog();
}

function renderTopbar() {
  const g = state.game;
  const c = g.company;
  mountLogo($("#game-logo"), c.logo || {}, state.catalog.logo_parts, 40);
  $("#game-company").textContent = c.name;
  const country = state.catalog.countries[c.country] || {};
  $("#game-country").textContent = `${country.flag_emoji || ""} ${c.country_name || c.country}`;
  $("#stat-day").textContent = g.day;
  $("#stat-capital").textContent = money(c.capital);
  $("#stat-capital").style.color = c.capital < 0 ? "var(--bad)" : "";
  $("#stat-revenue").textContent = money(g.systems?.market?.daily_revenue || 0);
  $("#stat-emps").textContent = (g.systems?.hr?.employees || []).length;
  const flops = g.systems?.compute?.pool?.flops_tf || 0;
  $("#stat-flops").textContent = `${Number(flops).toFixed(0)} TF`;
}

function renderDashboard() {
  const g = state.game;
  const t = g.company.tendencies || {};
  const labels = {
    openness: "开放性",
    gov_relation: "政府关系",
    public_rep: "公众声誉",
    transparency: "透明性",
    innovation: "创新性",
  };
  $("#tend-bars").innerHTML = Object.entries(labels)
    .map(([k, lab]) => {
      const v = Number(t[k] || 0);
      return `<div class="bar-row"><span class="label">${lab}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, v)}%"></div></div>
        <span class="val">${v.toFixed(0)}</span></div>`;
    })
    .join("");

  const active = [];
  (g.systems?.research?.active || []).forEach((j) => {
    const pct = Math.min(100, (j.progress / j.needed) * 100);
    active.push(`<div class="stack-item"><div class="t">研究 · ${j.name}</div>
      <div class="s">团队 ${j.employee_ids?.length || 0} 人</div>
      <div class="progress"><i style="width:${pct}%"></i></div></div>`);
  });
  (g.systems?.training?.active || []).forEach((j) => {
    const pct = Math.min(100, (j.progress / j.needed) * 100);
    active.push(`<div class="stack-item"><div class="t">训练 · ${j.name}</div>
      <div class="s">${j.params_b}B · ${j.model_type}</div>
      <div class="progress"><i style="width:${pct}%"></i></div></div>`);
  });
  $("#dash-active").innerHTML = active.length ? active.join("") : `<div class="muted">暂无进行中的项目</div>`;

  const f = g.company.founder || {};
  $("#dash-founder").innerHTML = `
    <div style="display:flex;gap:1rem;align-items:center">
      <div id="dash-av"></div>
      <div>
        <div style="font-weight:700">${f.name}</div>
        <div class="muted">${f.background_name || f.background}</div>
        <div class="tags mt">
          <span class="tag">技术 ${f.stats?.tech_skill ?? "-"}</span>
          <span class="tag">商业 ${f.stats?.business_skill ?? "-"}</span>
          <span class="tag">领导 ${f.stats?.leadership ?? "-"}</span>
        </div>
      </div>
    </div>`;
  renderFounderAvatar($("#dash-av"), f.gender || "male");

  const segs = g.systems?.market?.segment_users || {};
  const segMeta = g.systems?.market?.segments || state.catalog.api_segments || {};
  $("#dash-segments").innerHTML = Object.keys(segMeta)
    .map((id) => {
      const n = segs[id] || 0;
      const name = segMeta[id]?.name || id;
      return `<div class="bar-row"><span class="label">${name}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, n / 10)}%"></div></div>
        <span class="val">${Number(n).toFixed(0)}</span></div>`;
    })
    .join("");

  $("#dash-log").innerHTML = (g.log || [])
    .slice(0, 8)
    .map((l) => `<div class="log-line"><span class="d">D${l.day}</span><span class="m">${esc(l.msg)}</span></div>`)
    .join("");
}

function renderHR() {
  const g = state.game;
  const emps = g.systems?.hr?.employees || [];
  const cands = g.systems?.hr?.candidates || [];
  $("#emp-count").textContent = emps.length;
  $("#emp-list").innerHTML = emps.map((p) => personCard(p, true)).join("") || empty("暂无员工，去招聘吧");
  $("#cand-list").innerHTML = cands.map((p) => personCard(p, false)).join("") || empty("人才市场空空如也");

  // bind buttons
  $all("#emp-list [data-act]").forEach((b) => {
    b.onclick = () => hrAct(b.dataset.act, b.dataset.id, b.dataset.extra);
  });
  $all("#cand-list [data-act]").forEach((b) => {
    b.onclick = () => hrAct(b.dataset.act, b.dataset.id);
  });

  const comps =
    g.systems?.competitors?.rivals ||
    g.systems?.competitors?.competitors ||
    g.systems?.market?.competitors ||
    [];
  $("#poach-list").innerHTML = comps
    .map(
      (c) =>
        `<button class="btn sm" data-poach="${c.id}" title="${esc(c.personality || "")}">
          挖角 ${esc(c.name)}
          <span class="muted">（${esc(c.strategy_name || c.strategy || "")} · 员工${c.employee_count ?? "?"}）</span>
        </button>`
    )
    .join("");
  $all("#poach-list [data-poach]").forEach((b) => {
    b.onclick = async () => {
      try {
        const r = await api.poach(b.dataset.poach, 1.5);
        applyAction(r);
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
}

function personCard(p, hired) {
  const skills = Object.entries(p.skills || {})
    .filter(([, v]) => v >= 20)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([k, v]) => {
      const name = state.catalog.skills?.[k]?.name || k;
      return `<span>${name} <b>${Number(v).toFixed(0)}</b></span>`;
    })
    .join("");
  const tags = [];
  if (p.seniority_name) tags.push(`<span class="tag">${p.seniority_name}</span>`);
  if (p.assigned_to) tags.push(`<span class="tag warn">任务中</span>`);
  if (hired) {
    tags.push(`<span class="tag">士气 ${Number(p.morale || 0).toFixed(0)}</span>`);
    tags.push(`<span class="tag ${p.satisfaction < 40 ? "bad" : "good"}">满意度 ${Number(p.satisfaction || 0).toFixed(0)}</span>`);
    (p.hidden_tags_visible || []).forEach((t) => {
      const meta = state.catalog.hidden_tags?.[t];
      tags.push(`<span class="tag hidden-tag" title="${esc(meta?.desc || "")}">${meta?.name || t}</span>`);
    });
  } else {
    tags.push(`<span class="tag">签约奖 ${money(p.signing_bonus)}</span>`);
    tags.push(`<span class="tag">隐藏特质 ?</span>`);
  }
  // prefs top
  const prefs = Object.entries(p.preferences || {})
    .sort((a, b) => (b[1].weight || 0) - (a[1].weight || 0))
    .slice(0, 2)
    .map(([k, v]) => {
      const name = state.catalog.tendencies?.[k]?.name || k;
      return `${name}→${Number(v.ideal).toFixed(0)}`;
    })
    .join(" · ");

  const actions = hired
    ? `<button class="btn sm" data-act="train" data-id="${p.id}">培养</button>
       <button class="btn sm danger" data-act="fire" data-id="${p.id}">解雇</button>`
    : `<button class="btn sm primary" data-act="hire" data-id="${p.id}">雇佣 ${money(p.salary)}/月</button>`;

  return `<div class="person">
    <header>
      <div class="avatar">${esc((p.name || "?").slice(0, 1))}</div>
      <div class="meta">
        <div class="nm">${esc(p.name)}</div>
        <div class="role">${esc(p.role_name || p.role)} · ${money(p.salary)}/月${p.from_company ? " · 来自 " + esc(p.from_company) : ""}</div>
      </div>
      <div class="actions">${actions}</div>
    </header>
    <div class="tags">${tags.join("")}</div>
    <div class="skills-mini">${skills}</div>
    <div class="s muted" style="font-size:0.78rem">倾向：${esc(prefs || "—")}</div>
  </div>`;
}

async function hrAct(act, id) {
  try {
    if (act === "hire") applyAction(await api.hire(id));
    else if (act === "fire") {
      if (!confirm("确认解雇？")) return;
      applyAction(await api.fire(id));
    } else if (act === "train") {
      await trainModal(id);
    }
  } catch (e) {
    toast(e.message, "err");
  }
}

async function trainModal(empId) {
  const skills = state.catalog.skills || {};
  const body = document.createElement("div");
  body.innerHTML = `<p class="muted">选择要培养的技能（消耗资金，提升熟练度）</p>
    <div class="stack" style="max-height:50vh;overflow:auto">
      ${Object.values(skills)
        .map(
          (s) =>
            `<button class="btn" style="justify-content:space-between" data-sk="${s.id}">
              <span>${s.name}</span><span class="muted">$2,000</span>
            </button>`
        )
        .join("")}
    </div>`;
  const p = showModal({ title: "技能培养", body, footer: "" });
  body.querySelectorAll("[data-sk]").forEach((b) => {
    b.onclick = async () => {
      try {
        const r = await api.trainSkill(empId, b.dataset.sk);
        closeModal(true);
        applyAction(r);
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
  await p;
}

function renderResearch() {
  const g = state.game;
  const cat = state.researchCat;
  const items = g.systems?.research?.catalog?.[cat] || [];
  const freeEmps = (g.systems?.hr?.employees || []).filter((e) => !e.assigned_to);

  $("#research-list").innerHTML = items
    .map((r) => {
      const active = r.active;
      let pct = 0;
      if (active) pct = Math.min(100, (active.progress / active.needed) * 100);
      const maxed = r.level >= r.max_level;
      return `<div class="r-card">
        <header><span class="nm">${esc(r.name)}</span><span class="lv">Lv.${r.level}/${r.max_level}</span></header>
        <div class="desc">${esc(r.description || "")}</div>
        ${active ? `<div class="progress"><i style="width:${pct}%"></i></div>
          <div class="s muted">进行中 · 团队 ${active.employee_ids?.length || 0}/${r.team_cap}</div>` : ""}
        <footer>
          <span class="cost">${maxed ? "MAX" : money(r.next_cost) + " · ~" + Math.round(r.next_days_base) + "天"}</span>
          ${
            maxed
              ? ""
              : active
              ? `<button class="btn sm" data-assign="${r.id}">调整团队</button>`
              : `<button class="btn sm primary" data-start="${r.id}" ${freeEmps.length ? "" : ""}>开始</button>`
          }
        </footer>
      </div>`;
    })
    .join("");

  $all("[data-start]").forEach((b) => {
    b.onclick = () => startResearch(b.dataset.start, cat);
  });
  $all("[data-assign]").forEach((b) => {
    b.onclick = () => assignResearch(b.dataset.assign, cat);
  });
}

async function startResearch(id, cat) {
  const emps = pickEmployeesModal("分配研究团队（最多20人）");
  const ids = await emps;
  if (ids === null) return;
  try {
    applyAction(await api.startResearch(id, cat, ids));
  } catch (e) {
    toast(e.message, "err");
  }
}

async function assignResearch(id, cat) {
  const ids = await pickEmployeesModal("调整团队");
  if (ids === null) return;
  try {
    applyAction(await api.assignResearch(id, cat, ids));
  } catch (e) {
    toast(e.message, "err");
  }
}

function pickEmployeesModal(title) {
  const emps = state.game.systems?.hr?.employees || [];
  const body = document.createElement("div");
  if (!emps.length) {
    body.innerHTML = `<p class="muted">暂无员工。可以空队启动（极慢）或先去招聘。</p>`;
  } else {
    body.innerHTML = `<div class="stack" style="max-height:50vh;overflow:auto">
      ${emps
        .map(
          (e) => `<label class="check" style="margin:0">
          <input type="checkbox" value="${e.id}" ${e.assigned_to ? "disabled" : ""} />
          ${esc(e.name)} · ${esc(e.role_name || "")} ${e.assigned_to ? "（忙碌）" : ""}
        </label>`
        )
        .join("")}
    </div>`;
  }
  const footer = document.createElement("div");
  footer.style.cssText = "display:flex;gap:0.5rem;width:100%;justify-content:flex-end";
  footer.innerHTML = `<button class="btn ghost" id="m-cancel">取消</button>
    <button class="btn primary" id="m-ok">确认</button>`;
  const p = showModal({ title, body, footer });
  return new Promise((resolve) => {
    footer.querySelector("#m-cancel").onclick = () => {
      closeModal();
      resolve(null);
    };
    footer.querySelector("#m-ok").onclick = () => {
      const ids = [...body.querySelectorAll("input:checked")].map((i) => i.value);
      closeModal();
      resolve(ids);
    };
    p.then((v) => {
      if (v === null) resolve(null);
    });
  });
}

function renderCompute() {
  const g = state.game;
  const pool = g.systems?.compute?.pool || {};
  $("#pool-summary").innerHTML = `
    <span class="pill">${pool.units || 0} 卡</span>
    <span class="pill">${Number(pool.flops_tf || 0).toFixed(0)} TF</span>
    <span class="pill">${Number(pool.memory_gb || 0).toFixed(0)} GB</span>
    <span class="pill">效率 ×${Number(pool.efficiency || 1).toFixed(2)}</span>
    <span class="pill">占用 ${(Number(pool.busy || 0) * 100).toFixed(0)}%</span>`;

  const chips = g.systems?.compute?.available || [];
  $("#chip-list").innerHTML = chips
    .map((c) => {
      const cloudOnly = c.cloud_only;
      return `<div class="chip-card">
        <h4>${esc(c.name)}</h4>
        <div class="specs">${c.flops_tf} TF · ${c.memory_gb}GB · 拥有 ${c.owned || 0} · 云 ${c.cloud_qty || 0}
          ${c.note ? "<br/>" + esc(c.note) : ""}
        </div>
        <div class="row">
          ${
            cloudOnly
              ? ""
              : `<button class="btn sm primary" data-buy="${c.id}" data-mode="buy">采购 ${money(c.unit_cost)}</button>`
          }
          <button class="btn sm" data-buy="${c.id}" data-mode="cloud">租用 ${money(c.monthly_cloud_cost)}/月</button>
          <input type="number" min="1" max="64" value="1" data-qty="${c.id}" style="width:64px" />
        </div>
      </div>`;
    })
    .join("");

  $all("[data-buy]").forEach((b) => {
    b.onclick = async () => {
      const qty = Number($(`[data-qty="${b.dataset.buy}"]`)?.value || 1);
      try {
        applyAction(await api.purchaseCompute(b.dataset.buy, qty, b.dataset.mode));
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
}

function renderTraining() {
  const g = state.game;
  const dataRes = (g.systems?.research?.catalog?.data || []).map((r) => r.id);
  // weights
  const names = {
    frontier_science: "前沿科学",
    code: "代码",
    creative_writing: "创意写作",
    industrial: "工业",
    admin: "行政",
    nsfw: "NSFW",
  };
  const keys = Object.keys(names).filter((k) => dataRes.includes(k) || true);
  $("#ds-weights").innerHTML = keys
    .map(
      (k) =>
        `<label>${names[k] || k}<input type="number" min="0" max="10" step="0.1" value="1" data-w="${k}" /></label>`
    )
    .join("");

  const dss = g.systems?.training?.datasets || [];
  $("#ds-list").innerHTML =
    dss
      .map(
        (d) =>
          `<div class="stack-item"><div class="t">${esc(d.name)}</div>
        <div class="s">质量 ${d.quality}${d.open_source_base ? " · 开源base" : ""}</div></div>`
      )
      .join("") || empty("无数据集");

  // training form selects
  const types = g.systems?.training?.model_types || state.catalog.model_types || {};
  fillSelect(
    $("#tr-type"),
    Object.values(types).map((t) => [t.id, t.name]),
    $("#tr-type").value
  );
  const presets = g.systems?.training?.param_presets || state.catalog.param_presets || [];
  fillSelect(
    $("#tr-params"),
    presets.map((p) => [p.params_b, p.label]),
    $("#tr-params").value || "7"
  );
  fillSelect(
    $("#tr-ds"),
    dss.map((d) => [d.id, `${d.name} (q=${d.quality})`]),
    $("#tr-ds").value
  );
  fillSelect($("#di-params"), presets.map((p) => [p.params_b, p.label]), $("#di-params").value || "7");
  fillSelect($("#di-ds"), dss.map((d) => [d.id, d.name]), $("#di-ds").value);

  // base models: open + own released
  const bases = [
    ...(g.systems?.training?.open_models || []).map((m) => [m.id, `[开源] ${m.name} (${m.hidden_score})`]),
    ...(g.systems?.training?.models || [])
      .filter((m) => m.released)
      .map((m) => [m.id, `[自有] ${m.name}`]),
  ];
  fillSelect($("#tr-base"), bases.length ? bases : [["", "无可用基座"]], $("#tr-base").value);

  const free = (g.systems?.hr?.employees || []).filter((e) => !e.assigned_to);
  const sel = $("#tr-emps");
  sel.innerHTML = free.map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.role_name || "")}</option>`).join("");

  const active = g.systems?.training?.active || [];
  $("#tr-active").innerHTML =
    active
      .map((j) => {
        const pct = Math.min(100, (j.progress / j.needed) * 100);
        return `<div class="stack-item"><div class="t">${esc(j.name)}</div>
        <div class="s">${j.params_b}B · ${j.model_type} · 天${j.started_day}</div>
        <div class="progress"><i style="width:${pct}%"></i></div></div>`;
      })
      .join("") || empty("无训练任务");

  fillDistillTeachers();
}

function fillDistillTeachers() {
  const g = state.game;
  if (!g) return;
  const src = $("#di-source").value;
  let list = [];
  if (src === "own") {
    list = (g.systems?.training?.models || [])
      .filter((m) => m.released || m.hidden_score)
      .map((m) => [m.id, `${m.name} (H${m.hidden_score})`]);
  } else if (src === "open") {
    list = (g.systems?.training?.open_models || []).map((m) => [
      m.id,
      `${m.name} (H${m.hidden_score})`,
    ]);
  } else {
    list = (g.systems?.training?.competitor_models || []).map((m) => [
      m.id,
      `${m.name} · ${m.company} (H${m.hidden_score})`,
    ]);
  }
  fillSelect($("#di-teacher"), list.length ? list : [["", "无"]], $("#di-teacher").value);
}

async function createDataset() {
  const name = $("#ds-name").value.trim() || "数据集";
  const useOpen = $("#ds-open").checked;
  const weights = {};
  $all("#ds-weights [data-w]").forEach((i) => {
    weights[i.dataset.w] = Number(i.value) || 0;
  });
  try {
    applyAction(await api.createDataset(name, useOpen, weights));
  } catch (e) {
    toast(e.message, "err");
  }
}

async function startTraining() {
  const empSel = $("#tr-emps");
  const employee_ids = [...empSel.selectedOptions].map((o) => o.value);
  const from_scratch = $("#tr-scratch").checked;
  const payload = {
    name: $("#tr-name").value.trim() || "Model",
    model_type: $("#tr-type").value,
    params_b: Number($("#tr-params").value),
    dataset_id: $("#tr-ds").value,
    from_scratch,
    base_model_id: from_scratch ? null : $("#tr-base").value || null,
    expected_days: Number($("#tr-days").value) || 30,
    employee_ids,
  };
  try {
    applyAction(await api.startTraining(payload));
  } catch (e) {
    toast(e.message, "err");
  }
}

async function startDistill() {
  const payload = {
    name: $("#di-name").value.trim() || "Distill",
    teacher_model_id: $("#di-teacher").value,
    teacher_source: $("#di-source").value,
    params_b: Number($("#di-params").value),
    dataset_id: $("#di-ds").value,
    expected_days: 14,
    employee_ids: [],
    model_type: "text",
  };
  try {
    applyAction(await api.distill(payload));
  } catch (e) {
    toast(e.message, "err");
  }
}

function renderModels() {
  const models = state.game.systems?.training?.models || [];
  if (!models.length) {
    $("#model-list").innerHTML = empty("还没有训练完成的模型");
    return;
  }
  $("#model-list").innerHTML = models
    .map((m) => {
      const evals = m.eval_scores || {};
      const evalHtml = Object.entries(evals)
        .filter(([k]) => k !== "average")
        .map(([k, v]) => `<span>${k}: <b>${Number(v).toFixed(1)}</b></span>`)
        .join("");
      const status = [];
      if (m.released) status.push(m.open_source ? "开源" : "闭源");
      if (m.preview) status.push("Preview");
      if (m.api_enabled) status.push("API");
      if (!m.released) status.push("未发布");
      return `<div class="model-card">
        <header>
          <div>
            <div class="nm">${esc(m.name)}</div>
            <div class="muted">${m.params_b}B · ${m.model_type}${m.base_label ? " · 基于 " + esc(m.base_label) : ""}${m.distilled ? " · 蒸馏" : ""}</div>
          </div>
          <div class="tags">${status.map((s) => `<span class="tag">${s}</span>`).join("")}</div>
        </header>
        <div class="scores">
          <div class="score-box"><div class="k">隐藏分</div><div class="v hi">${m.hidden_score}</div></div>
          <div class="score-box"><div class="k">EVAL 均分</div><div class="v">${Number(evals.average || 0).toFixed(1)}</div></div>
        </div>
        <div class="eval-list">${evalHtml}</div>
        ${
          m.released && m.api_enabled
            ? `<div class="muted mt" style="font-size:0.82rem">API $${m.price_input}/M in · $${m.price_output}/M out
              ${m.daily_revenue != null ? " · 日入 " + money(m.daily_revenue) : ""}</div>`
            : ""
        }
        <div class="actions">
          ${
            !m.released
              ? `<button class="btn sm primary" data-rel="${m.id}" data-os="0">闭源发布</button>
                 <button class="btn sm" data-rel="${m.id}" data-os="1">开源发布</button>
                 <button class="btn sm" data-rel="${m.id}" data-os="0" data-prev="1">Preview</button>`
              : `<button class="btn sm" data-price="${m.id}">调价</button>`
          }
        </div>
      </div>`;
    })
    .join("");

  $all("[data-rel]").forEach((b) => {
    b.onclick = async () => {
      try {
        applyAction(
          await api.releaseModel({
            model_id: b.dataset.rel,
            open_source: b.dataset.os === "1",
            preview: b.dataset.prev === "1",
            api_enabled: true,
          })
        );
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
  $all("[data-price]").forEach((b) => {
    b.onclick = async () => {
      const m = models.find((x) => x.id === b.dataset.price);
      const pin = prompt("Input $/M tokens", m?.price_input ?? 2);
      const pout = prompt("Output $/M tokens", m?.price_output ?? 6);
      if (pin == null || pout == null) return;
      try {
        applyAction(await api.setPrice(b.dataset.price, Number(pin), Number(pout)));
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
}

function renderMarket() {
  const g = state.game;
  const segs = g.systems?.market?.segments || {};
  const users = g.systems?.market?.segment_users || {};
  const ai = g.systems?.competitors || {};
  const threat = Number(ai.threat_index || 0);

  if ($("#threat-pill")) {
    const threatColor = threat > 70 ? "var(--bad)" : threat > 40 ? "var(--warn)" : "var(--good)";
    $("#threat-pill").innerHTML = `
      <span class="pill" style="border-color:${threatColor};color:${threatColor}">竞争压力 ${threat.toFixed(0)}</span>
      <span class="pill">对手 ${ (ai.rivals || ai.competitors || []).length }</span>
      <span class="pill">竞品模型 ${ (ai.models || []).length }</span>`;
  }

  $("#market-segments").innerHTML = Object.values(segs)
    .map((s) => {
      return `<div class="stack-item">
        <div class="t">${esc(s.name)} <span class="badge">${Number(users[s.id] || 0).toFixed(0)} 活跃</span></div>
        <div class="s">${esc(s.description || "")}</div>
        <div class="tags mt">
          <span class="tag">付费意愿 ${s.pay_willingness}</span>
          <span class="tag">价格敏感 ${s.price_sensitivity}</span>
          <span class="tag">新鲜感 ${s.novelty_bias}</span>
        </div>
      </div>`;
    })
    .join("");

  const log = ai.action_log || [];
  if ($("#rival-log")) {
    $("#rival-log").innerHTML = log.length
      ? log
          .slice()
          .reverse()
          .map(
            (l) =>
              `<div class="log-line"><span class="d">D${l.day}</span><span class="m">${esc(l.msg)}</span></div>`
          )
          .join("")
      : empty("推进天数后，对手会研究、发模型、挖角…");
  }

  const comps = ai.rivals || ai.competitors || g.systems?.market?.competitors || [];
  $("#market-comps").innerHTML = comps
    .map((c) => {
      const fs = c.flagship;
      const tier = c.tier || "challenger";
      const topRes = (c.top_research || [])
        .slice(0, 3)
        .map((r) => `<span class="tag">${esc(r.id)} ${r.level}</span>`)
        .join("");
      return `<div class="rival-card" style="--rc:${c.color || "#38bdf8"}">
        <header>
          <div>
            <div class="nm">${esc(c.name)}</div>
            <div class="muted">${esc(c.strategy_name || c.strategy || "")} · <span class="tier-${tier}">${tier}</span></div>
          </div>
          <div class="tags">
            <span class="tag">实力 ${((c.strength || 0) * 100).toFixed(0)}</span>
          </div>
        </header>
        <div class="personality">${esc(c.personality || c.strategy_desc || "")}</div>
        ${
          fs
            ? `<div class="flagship"><b>旗舰</b> ${esc(fs.name)} · H${fs.hidden_score}
                · EVAL ${Number(fs.eval_avg || 0).toFixed(1)}
                · ${fs.open_source ? "开源" : "闭源"}
                ${fs.api_enabled !== false && fs.price_output != null ? " · $" + fs.price_output + "/M" : ""}
              </div>`
            : ""
        }
        <div class="tags">
          <span class="tag">声誉 ${Number(c.public_rep || 0).toFixed(0)}</span>
          <span class="tag">开源比 ${((c.open_ratio || 0) * 100).toFixed(0)}%</span>
          <span class="tag">员工 ${c.employee_count ?? "—"}</span>
          <span class="tag">模型 ${c.models_count ?? 0}</span>
        </div>
        <div class="tags mt">${topRes}</div>
        <div class="actions">
          <button class="btn sm" data-poach="${c.id}">挖角 (1.5×)</button>
          <button class="btn sm" data-poach="${c.id}" data-mult="2.2">高价挖角 (2.2×)</button>
        </div>
      </div>`;
    })
    .join("") || empty("无对手数据");

  $all("#market-comps [data-poach]").forEach((b) => {
    b.onclick = async () => {
      try {
        const mult = Number(b.dataset.mult || 1.5);
        applyAction(await api.poach(b.dataset.poach, mult));
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });

  const models = ai.models || g.systems?.training?.competitor_models || [];
  if ($("#rival-models")) {
    $("#rival-models").innerHTML = models.length
      ? models
          .slice()
          .sort((a, b) => (b.hidden_score || 0) - (a.hidden_score || 0))
          .map(
            (m) => `<div class="stack-item">
            <div class="t">${esc(m.name)} <span class="badge">${esc(m.company || "")}</span></div>
            <div class="s">H${m.hidden_score} · EVAL ${Number(m.eval_avg || 0).toFixed(1)}
              · ${m.params_b}B · ${m.open_source ? "开源" : "闭源"}
              ${m.api_enabled ? " · API $" + m.price_output + "/M" : ""}
              · ${m.model_type || "text"}</div>
          </div>`
          )
          .join("")
      : empty("暂无竞品模型");
  }
}

function renderEvents() {
  const g = state.game;
  const q = g.systems?.events?.queue || [];
  const hist = g.systems?.events?.history || [];
  if (!q.length) {
    $("#event-queue").innerHTML = empty("当前没有待处理事件。推进天数可能触发新事件。");
  } else {
    $("#event-queue").innerHTML = q
      .map(
        (ev) => `<div class="event-card" data-eid="${ev.instance_id}">
        <h3>${esc(ev.title)}</h3>
        <p>${esc(ev.description)}</p>
        <div class="choices">
          ${(ev.choices || [])
            .map(
              (c) =>
                `<button class="btn" data-choice="${c.id}" data-eid="${ev.instance_id}">${esc(c.label)}</button>`
            )
            .join("")}
        </div>
      </div>`
      )
      .join("");
    $all("#event-queue [data-choice]").forEach((b) => {
      b.onclick = async () => {
        try {
          applyAction(await api.eventChoice(b.dataset.eid, b.dataset.choice));
        } catch (e) {
          toast(e.message, "err");
        }
      };
    });
  }
  $("#event-history").innerHTML =
    hist
      .slice()
      .reverse()
      .map(
        (h) =>
          `<div class="stack-item"><div class="t">D${h.resolved_day || h.day} · ${esc(h.title)}</div>
        <div class="s">→ ${esc(h.chosen_label || "")} ${h.result_logs?.length ? "· " + h.result_logs.join(", ") : ""}</div></div>`
      )
      .join("") || empty("暂无历史");
}

function renderLog() {
  const log = state.game.log || [];
  $("#full-log").innerHTML = log
    .map((l) => `<div class="log-line"><span class="d">D${l.day}</span><span class="m">[${l.cat || "game"}] ${esc(l.msg)}</span></div>`)
    .join("");
}

function empty(t) {
  return `<div class="muted" style="padding:0.5rem 0">${t}</div>`;
}
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

boot();
