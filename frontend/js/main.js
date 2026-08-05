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
  selectedModelId: null,
  ladderMode: "closed",
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

function costEstimateHtml({ upfront = 0, daily = 0, days = 0, license = 0, total = null, note = "" }) {
  const projected = total == null ? Number(upfront) + Number(license) + Number(daily) * Number(days) : Number(total);
  return `<div class="cost-estimate-title"><span>预计费用</span><b>${money(projected)}</b></div>
    <div class="cost-estimate-parts">
      ${license ? `<span>授权 ${money(license)}</span>` : ""}
      ${upfront ? `<span>启动 ${money(upfront)}</span>` : ""}
      ${daily ? `<span>日耗约 ${money(daily)}</span>` : ""}
      ${days ? `<span>按 ${Number(days).toFixed(days % 1 ? 1 : 0)} 天估算</span>` : ""}
    </div>${note ? `<small>${esc(note)}</small>` : ""}`;
}

function parameterScaleFactor(paramsB) {
  const params = Math.max(0.1, Number(paramsB) || 0.1);
  return 0.65 + 2.15 * (1 - Math.exp(-Math.pow(params / 45, 0.42)));
}

function parameterComputeUnits(paramsB, presets = null) {
  const params = Math.max(0.1, Number(paramsB) || 0.1);
  const points = (presets || state.game?.systems?.training?.param_presets || state.catalog?.param_presets || [])
    .map((item) => [Number(item.params_b), Number(item.compute_units)])
    .filter(([p, units]) => p > 0 && units > 0)
    .sort((a, b) => a[0] - b[0]);
  if (!points.length) return 10 * Math.pow(params, 1.06);
  if (params <= points[0][0]) return points[0][1] * Math.pow(params / points[0][0], 1.06);
  if (params >= points[points.length - 1][0]) {
    const last = points[points.length - 1];
    return last[1] * Math.pow(params / last[0], 1.06);
  }
  for (let index = 0; index < points.length - 1; index += 1) {
    const [leftP, leftUnits] = points[index];
    const [rightP, rightUnits] = points[index + 1];
    if (params >= leftP && params <= rightP) {
      const ratio = Math.log(params / leftP) / Math.log(rightP / leftP);
      return Math.exp(Math.log(leftUnits) + (Math.log(rightUnits) - Math.log(leftUnits)) * ratio);
    }
  }
  return 10 * Math.pow(params, 1.06);
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
  $("#btn-new-distill").onclick = openStandaloneDistillModal;
  $("#tr-scratch").onchange = (e) => {
    $("#tr-base-wrap").classList.toggle("hidden", e.target.checked);
  };
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
  renderDatasets();
  renderCompute();
  renderTraining();
  renderModels();
  renderLeaderboard();
  renderMarket();
  renderRivals();
  renderFinance();
  renderFunding();
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
  const debt = Number(g.systems?.finance?.total_balance || 0);
  $("#stat-debt").textContent = money(debt);
  $("#stat-debt").style.color = debt > 0 ? "var(--warn)" : "";
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
    const pct = Number(j.progress_pct != null ? j.progress_pct : Math.min(100, (j.progress / (j.needed || 1)) * 100));
    const eta = j.eta_days != null ? ` · ~${j.eta_days}d` : "";
    active.push(`<div class="stack-item"><div class="t">研究 · ${j.name || j.research_id}</div>
      <div class="s">Lv.${j.level ?? "?"} · ${j.employee_ids?.length || 0} 人${eta}</div>
      <div class="progress"><i style="width:${pct}%"></i></div></div>`);
  });
  (g.systems?.training?.active || []).forEach((j) => {
    const pct = Number(j.progress_pct != null ? j.progress_pct : Math.min(100, (j.progress / (j.needed || 1)) * 100));
    const eta = j.eta_days != null ? ` · ~${j.eta_days}d` : "";
    active.push(`<div class="stack-item"><div class="t">训练 · ${j.name}</div>
      <div class="s">${j.phase || ""} · ${j.params_b}B · ${(j.employee_ids||[]).length}人${eta}</div>
      <div class="progress"><i style="width:${pct}%"></i></div></div>`);
  });
  (g.systems?.training?.dataset_jobs || []).forEach((j) => {
    const pct = Number(j.progress_pct || 0);
    const eta = j.eta_days != null ? ` · ~${j.eta_days}d` : " · 已暂停";
    active.push(`<div class="stack-item"><div class="t">数据集 · ${esc(j.name)}</div>
      <div class="s">目标质量 ${j.quality} · ${(j.employee_ids || []).length}人${eta}</div>
      <div class="progress"><i style="width:${pct}%"></i></div></div>`);
  });
  $("#dash-active").innerHTML = active.length ? active.join("") : `<div class="muted">暂无进行中的项目 — 去研究/训练页投入人手</div>`;

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
  const chief = g.systems?.hr?.chief_scientist || null;
  const autoHire = g.systems?.hr?.auto_hire || {};
  const chiefPanel = $("#chief-scientist-panel");
  chiefPanel.classList.toggle("active", Boolean(chief));
  chiefPanel.innerHTML = chief
    ? `<div class="chief-main"><div class="chief-emblem">CS</div><div><span class="eyebrow">CHIEF SCIENTIST</span><h3>${esc(chief.name)}</h3><p>${esc(chief.role_name || "首席科学家")} · 不会被竞争对手挖角，并指导整个研发团队。</p></div></div>
       <div class="chief-metrics"><div><span>科学能力</span><b>${Number(chief.ability || 0).toFixed(1)}</b></div><div><span>全员有效能力</span><b>×${Number(chief.team_skill_multiplier || 1).toFixed(3)}</b></div><div><span>人才保护</span><b>挖角免疫</b></div></div>
       <button class="btn sm ghost" data-chief-unset>解除职务</button>`
    : `<div class="chief-main"><div class="chief-emblem vacant">CS</div><div><span class="eyebrow">CHIEF SCIENTIST</span><h3>尚未任命首席科学家</h3><p>从在职员工中任命一人。其最高四项技能的平均值将转化为全员能力乘数，最高可达 ×1.250。</p></div></div><span class="muted chief-hint">使用员工卡片上的“任命首席”按钮</span>`;
  const unsetChief = chiefPanel.querySelector("[data-chief-unset]");
  if (unsetChief) unsetChief.onclick = () => hrAct("unchief", chief.employee_id);
  const autoHirePanel = $("#auto-hire-panel");
  const hireLimit = Number(autoHire.max_hires_per_cycle || 3);
  autoHirePanel.classList.toggle("active", Boolean(autoHire.enabled));
  autoHirePanel.innerHTML = `<div class="auto-hire-main"><span>AUTO HIRE</span><div><span class="eyebrow">RESEARCH TALENT AGENT</span><h3>自动雇佣研究人才</h3><p>${esc(autoHire.status_message || "根据已开启 AUTO 的研究课题，优先补齐无人负责的方向，再按边际研究收益与雇佣成本选择候选人。")}</p></div></div>
    <div class="auto-hire-metrics"><div><span>当前目标</span><b>${esc(autoHire.target_research_name || "等待 AUTO 研究")}</b></div><div><span>候选人</span><b>${esc(autoHire.candidate_name || "待评估")}</b><small>${autoHire.candidate_fit != null ? `匹配 ${Number(autoHire.candidate_fit).toFixed(0)} · 收益成本 ${Number(autoHire.candidate_roi || 0).toFixed(1)}` : `每 7 天最多录用 ${hireLimit} 人`}</small></div><div><span>累计录用</span><b>${Number(autoHire.hires_completed || 0)} 人</b><small>${autoHire.hires_this_cycle ? `上一轮 ${Number(autoHire.hires_this_cycle)} 人` : autoHire.cash_reserve != null ? `现金垫 ${money(autoHire.cash_reserve)}` : "保留三个月工资安全垫"}</small></div></div>
    <div class="auto-hire-actions"><label>每轮上限<input type="number" min="1" max="20" value="${hireLimit}" data-auto-hire-limit /></label><button class="btn sm ${autoHire.enabled ? "" : "primary"}" data-auto-hire-save>${autoHire.enabled ? "保存设置" : "开启自动雇佣"}</button>${autoHire.enabled ? `<button class="btn sm ghost" data-auto-hire-stop>关闭</button>` : ""}</div>`;
  autoHirePanel.querySelector("[data-auto-hire-save]").onclick = async () => {
    try {
      const limit = Math.max(1, Math.min(20, Number(autoHirePanel.querySelector("[data-auto-hire-limit]").value) || 3));
      applyAction(await api.setAutoHire(true, limit));
    } catch (error) {
      toast(error.message, "err");
    }
  };
  const stopAutoHire = autoHirePanel.querySelector("[data-auto-hire-stop]");
  if (stopAutoHire) stopAutoHire.onclick = async () => {
    try {
      applyAction(await api.setAutoHire(false, hireLimit));
    } catch (error) {
      toast(error.message, "err");
    }
  };
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
  const poachEstimates = g.systems?.hr?.poach_estimates || {};
  $("#poach-list").innerHTML = comps
    .map(
      (c) => {
        const estimate = poachEstimates[c.id]?.["1.5"];
        const cost = estimate
          ? `预计 ${money(estimate.min_total)}–${money(estimate.max_total)} · 失败费 ${money(estimate.min_search)}–${money(estimate.max_search)}`
          : "目标确定后结算";
        return `<button class="btn sm" data-poach="${c.id}" title="${esc(c.personality || "")}">
          挖角 ${esc(c.name)}
          <span class="muted">（${esc(c.strategy_name || c.strategy || "")} · ${cost}）</span>
        </button>`;
      }
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
  const baseSkills = p.skills || {};
  const shownSkills = hired ? (p.effective_skills || baseSkills) : baseSkills;
  const multiplier = Number(p.effective_skill_multiplier || 1);
  const skills = Object.entries(shownSkills)
    .filter(([, v]) => v >= 20)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([k, v]) => {
      const name = state.catalog.skills?.[k]?.name || k;
      const base = Number(baseSkills[k] || 0);
      return `<span>${name} <b>${Number(v).toFixed(0)}</b>${hired && multiplier > 1.0005 ? `<small>基础 ${base.toFixed(0)}</small>` : ""}</span>`;
    })
    .join("");
  const tags = [];
  if (p.seniority_name) tags.push(`<span class="tag">${p.seniority_name}</span>`);
  if (p.assigned_to) tags.push(`<span class="tag warn">任务中</span>`);
  if (hired) {
    if (p.is_chief_scientist) tags.push(`<span class="tag chief-tag">首席科学家 · 挖角免疫</span>`);
    if (multiplier > 1.0005) tags.push(`<span class="tag good">团队加成 ×${multiplier.toFixed(3)}</span>`);
    tags.push(`<span class="tag">士气 ${Number(p.morale || 0).toFixed(0)}</span>`);
    tags.push(`<span class="tag ${p.satisfaction < 40 ? "bad" : "good"}">满意度 ${Number(p.satisfaction || 0).toFixed(0)}</span>`);
    (p.hidden_tags_visible || []).forEach((t) => {
      const meta = state.catalog.hidden_tags?.[t];
      tags.push(`<span class="tag hidden-tag" title="${esc(meta?.desc || "")}">${meta?.name || t}</span>`);
    });
  } else {
    tags.push(`<span class="tag">签约奖 ${money(p.signing_bonus)}</span>`);
    tags.push(`<span class="tag warn">首期支出 ${money(p.hire_cost || Number(p.signing_bonus || 0) + Number(p.salary || 0))}</span>`);
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
    ? `${p.is_chief_scientist ? `<button class="btn sm ghost" data-act="unchief" data-id="${p.id}">解除首席</button>` : `<button class="btn sm" data-act="chief" data-id="${p.id}">任命首席</button>`}
       <button class="btn sm" data-act="train" data-id="${p.id}">培养</button>
       <button class="btn sm danger" data-act="fire" data-id="${p.id}">解雇 · 补偿 ${money(p.severance_cost || Number(p.salary || 0) * 0.5)}</button>`
    : `<button class="btn sm primary" data-act="hire" data-id="${p.id}">雇佣 · 预计 ${money(p.hire_cost || 0)}</button>`;

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
      const employee = (state.game.systems?.hr?.employees || []).find((item) => item.id === id);
      if (!confirm(`确认解雇？预计补偿 ${money(employee?.severance_cost || Number(employee?.salary || 0) * 0.5)}`)) return;
      applyAction(await api.fire(id));
    } else if (act === "train") {
      await trainModal(id);
    } else if (act === "chief") {
      applyAction(await api.setChiefScientist(id));
    } else if (act === "unchief") {
      applyAction(await api.setChiefScientist(null));
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
  const activeAll = g.systems?.research?.active || [];
  const activeCategory = activeAll.filter((item) => item.category === cat);
  const maxC = g.systems?.research?.max_concurrent || 8;
  const categoryStaff = g.systems?.research?.category_staff?.[cat] || { used: 0, cap: 20, remaining: 20 };
  const categoryNames = { model: "模型", data: "数据", compute: "推理算力" };
  const automation = g.systems?.research?.automation || {};
  const automationSummary = automation.enabled_count
    ? automation.reserved_employee
      ? `自动课题 ${automation.enabled_count} · 训练预留 <b>${esc(automation.reserved_employee.name)}</b>（匹配 ${Number(automation.reserved_employee.training_fit || 0).toFixed(0)}）`
      : `自动课题 ${automation.enabled_count} · 暂无可预留人员`
    : "自动研究未开启";

  if ($("#research-focus-bar")) {
    $("#research-focus-bar").innerHTML = `
      <span class="pill research-cap-pill">${categoryNames[cat] || cat}研究人员 <b>${categoryStaff.used}/${categoryStaff.cap}</b></span>
      <span class="pill">本类课题 ${activeCategory.length} 个 · 全部课题 ${activeAll.length}/${maxC}</span>
      <span class="pill">空闲人手 ${(g.systems?.hr?.employees || []).filter((e) => !e.assigned_to).length}</span>
      <span class="pill auto-summary">${automationSummary}</span>
      ${activeCategory
        .map(
          (a) =>
            `<span class="pill" title="${esc(a.name)}">${esc(a.name || a.research_id)} ${Number(a.progress_pct || 0).toFixed(0)}%${
              a.eta_days != null ? " · ~" + a.eta_days + "d" : ""
            }</span>`
        )
        .join("")}`;
  }

  $("#research-list").innerHTML = items
    .map((r) => {
      const pct = Number(r.progress_pct || 0);
      const maxed = r.level >= r.max_level;
      const focused = !!r.focused;
      const nStaff = (r.employee_ids || r.staff || []).length;
      const staffNames = (r.staff || []).map((s) => s.name).join("、") || "未分配";
      const eta =
        r.eta_days != null ? `ETA ${r.eta_days}d` : focused ? "计算中" : "投入人手后开始累积";
      const speed = focused ? `${Number(r.speed_per_day || 0).toFixed(1)}/天` : "—";
      return `<div class="r-card ${focused ? "focused" : ""} ${r.auto_enabled ? "automated" : ""}">
        <header>
          <span class="nm">${esc(r.name)}</span>
          <div class="research-card-controls">
            <span class="lv">Lv.${r.level}/${r.max_level}</span>
            ${maxed ? "" : `<button class="auto-toggle ${r.auto_enabled ? "on" : ""}" data-auto-research="${r.id}" data-enabled="${r.auto_enabled ? "1" : "0"}" title="开启后自动调度合适人员；可能产生所示立项费"><i></i><span>AUTO</span></button>`}
          </div>
        </header>
        <div class="desc">${esc(r.description || "")}</div>
        <div class="progress"><i style="width:${maxed ? 100 : pct}%"></i></div>
        <div class="progress-meta">
          <span>${maxed ? "MAX" : pct.toFixed(0) + "% → Lv." + (r.level + 1)}</span>
          <span>${speed} · ${eta}</span>
        </div>
        <div class="staff-line">${r.auto_enabled ? "⚙ " : focused ? "🔬 " : "👤 "}${esc(staffNames)}${nStaff ? `（本项目 ${nStaff} 人${r.auto_enabled ? " · 自动" : ""}）` : r.auto_enabled ? "（等待合适人员）" : ""}</div>
        <footer>
          <span class="cost">${maxed ? "已满级" : `${r.setup_cost_estimate ? `立项 ${money(r.setup_cost_estimate)} · ` : ""}日耗 ~${money(r.daily_cost || 0)} · 累计 ${money(r.total_invested || 0)}`}</span>
          <div style="display:flex;gap:0.3rem;flex-wrap:wrap">
            ${
              maxed
                ? ""
                : focused
                ? `<button class="btn sm" data-assign="${r.id}">调整人手</button>
                   <button class="btn sm ghost" data-pause="${r.id}">撤回</button>`
                : `<button class="btn sm primary" data-start="${r.id}">投入人手</button>`
            }
          </div>
        </footer>
      </div>`;
    })
    .join("");

  $all("#research-list [data-start]").forEach((b) => {
    b.onclick = () => focusResearch(b.dataset.start, cat, []);
  });
  $all("#research-list [data-assign]").forEach((b) => {
    const item = items.find((x) => x.id === b.dataset.assign);
    b.onclick = () => focusResearch(b.dataset.assign, cat, item?.employee_ids || []);
  });
  $all("#research-list [data-pause]").forEach((b) => {
    b.onclick = async () => {
      try {
        applyAction(await api.pauseResearch(b.dataset.pause));
      } catch (e) {
        toast(e.message, "err");
      }
    };
  });
  $all("#research-list [data-auto-research]").forEach((button) => {
    button.onclick = async () => {
      const enabled = button.dataset.enabled !== "1";
      try {
        applyAction(await api.setResearchAuto(button.dataset.autoResearch, cat, enabled));
      } catch (error) {
        toast(error.message, "err");
      }
    };
  });
}

async function focusResearch(id, cat, preselected = []) {
  const item = (state.game.systems?.research?.catalog?.[cat] || []).find((x) => x.id === id);
  const categoryStaff = state.game.systems?.research?.category_staff?.[cat] || { used: 0, cap: 20, remaining: 20 };
  const categoryNames = { model: "模型", data: "数据", compute: "推理算力" };
  const ids = await pickEmployeesModal(
    `投入人手 · ${item?.name || id}`,
    {
      preselected,
      allowBusyOn: `research:${id}`,
      hint: `${categoryNames[cat] || cat}研究共享 ${categoryStaff.cap} 人上限，目前已用 ${categoryStaff.used} 人、剩余 ${categoryStaff.remaining} 人。撤下人手后进度保留。`,
      max: item?.assignable_cap || item?.team_cap || 20,
      costPreview: (count) => {
        const onePersonDaily = Number(item?.daily_cost || 0);
        const dailyBase = onePersonDaily / 0.75;
        const daily = dailyBase * (0.6 + 0.15 * Math.max(1, count));
        const setup = Number(item?.setup_cost_estimate || 0);
        return `<div class="cost-estimate-title"><span>预计支出</span><b>${setup ? `启动 ${money(setup)} + ` : ""}${money(daily)}/天</b></div><small>日耗会随分配人数变化，直到当前研究等级完成或撤回人员。</small>`;
      },
    }
  );
  if (ids === null) return;
  try {
    // start_research == assign focus in new model
    applyAction(await api.startResearch(id, cat, ids));
  } catch (e) {
    toast(e.message, "err");
  }
}

function pickEmployeesModal(title, opts = {}) {
  const {
    preselected = [],
    allowBusyOn = null,
    hint = "",
    max = 20,
    costPreview = null,
  } = opts;
  const emps = state.game.systems?.hr?.employees || [];
  const pre = new Set(preselected);
  const body = document.createElement("div");
  if (!emps.length) {
    body.innerHTML = `<p class="muted">暂无员工，请先去人才市场招聘。</p>`;
  } else {
    body.innerHTML = `
      ${hint ? `<p class="muted" style="margin-top:0">${esc(hint)}</p>` : ""}
      <p class="muted" style="font-size:0.8rem">最多 ${max} 人 · 已选 <span id="pick-count">0</span></p>
      <div class="stack" style="max-height:50vh;overflow:auto">
      ${emps
        .map((e) => {
          const onThis =
            allowBusyOn && e.assigned_to === allowBusyOn;
          const busy = e.assigned_to && !onThis;
          const checked = pre.has(e.id) || onThis;
          return `<label class="check" style="margin:0;opacity:${busy ? 0.45 : 1}">
          <input type="checkbox" value="${e.id}" ${checked ? "checked" : ""} ${busy ? "disabled" : ""} />
          <span><b>${esc(e.name)}</b> · ${esc(e.role_name || "")} · ${esc(e.seniority_name || "")}
          ${busy ? `<span class="tag warn">忙碌</span>` : onThis ? `<span class="tag good">本组</span>` : ""}
          </span>
        </label>`;
        })
        .join("")}
      </div>`;
    if (costPreview) body.insertAdjacentHTML("beforeend", `<div class="cost-estimate" id="pick-cost-estimate"></div>`);
  }
  const footer = document.createElement("div");
  footer.style.cssText = "display:flex;gap:0.5rem;width:100%;justify-content:flex-end";
  footer.innerHTML = `<button class="btn ghost" id="m-cancel">取消</button>
    <button class="btn" id="m-clear">清空</button>
    <button class="btn primary" id="m-ok">确认分配</button>`;
  const p = showModal({ title, body, footer });

  const syncCount = () => {
    const n = body.querySelectorAll("input:checked:not(:disabled)").length;
    const el = body.querySelector("#pick-count");
    if (el) el.textContent = String(n);
    const costEl = body.querySelector("#pick-cost-estimate");
    if (costEl && costPreview) costEl.innerHTML = costPreview(n);
  };
  body.querySelectorAll("input[type=checkbox]").forEach((inp) => {
    inp.onchange = () => {
      const checked = [...body.querySelectorAll("input:checked:not(:disabled)")];
      if (checked.length > max) {
        inp.checked = false;
        toast(`最多 ${max} 人`, "err");
      }
      syncCount();
    };
  });
  syncCount();

  return new Promise((resolve) => {
    footer.querySelector("#m-cancel").onclick = () => {
      closeModal();
      resolve(null);
    };
    footer.querySelector("#m-clear").onclick = () => {
      body.querySelectorAll("input:checked:not(:disabled)").forEach((i) => (i.checked = false));
      syncCount();
    };
    footer.querySelector("#m-ok").onclick = () => {
      const ids = [...body.querySelectorAll("input:checked:not(:disabled)")].map((i) => i.value);
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
  const trainingJobs = g.systems?.training?.active || [];
  const trainingDemand = trainingJobs
    .filter((job) => !job.paused)
    .reduce((sum, job) => sum + Number(job.compute_required_tf || 0), 0);
  const computeRatio = Number(pool.flops_tf || 0) / Math.max(1, trainingDemand);
  const trainingComputeMult = trainingDemand
    ? Math.max(0.18, Math.min(3.5, Math.pow(computeRatio, 0.72)))
    : 0;
  $("#pool-summary").innerHTML = `
    <span class="pill">${pool.units || 0} 卡</span>
    <span class="pill">${Number(pool.flops_tf || 0).toFixed(0)} TF</span>
    <span class="pill">${Number(pool.memory_gb || 0).toFixed(0)} GB</span>
    <span class="pill">效率 ×${Number(pool.efficiency || 1).toFixed(2)}</span>
    <span class="pill">占用 ${(Number(pool.busy || 0) * 100).toFixed(0)}%</span>
    ${trainingDemand ? `<span class="pill compute-impact">训练需求 ${trainingDemand.toFixed(0)} TF · 当前速度 ×${trainingComputeMult.toFixed(2)}</span>` : `<span class="pill">暂无训练算力需求</span>`}`;

  const chips = g.systems?.compute?.available || [];
  $("#chip-list").innerHTML = chips
    .map((c) => {
      const cloudOnly = c.cloud_only;
      const buyCost = Number(c.effective_unit_cost ?? c.unit_cost ?? 0);
      const cloudCost = Number(c.effective_monthly_cloud_cost ?? c.monthly_cloud_cost ?? 0);
      return `<div class="chip-card">
        <h4>${esc(c.name)}</h4>
        <div class="specs">${c.flops_tf} TF · ${c.memory_gb}GB · 拥有 ${c.owned || 0} · 云 ${c.cloud_qty || 0}
          ${c.note ? "<br/>" + esc(c.note) : ""}
        </div>
        <div class="row">
          ${
            cloudOnly
              ? ""
              : `<button class="btn sm primary" data-buy="${c.id}" data-mode="buy">采购 ${money(buyCost)}/张</button>`
          }
          <button class="btn sm" data-buy="${c.id}" data-mode="cloud">租用 ${money(cloudCost)}/张/月</button>
          <input type="number" min="1" max="64" value="1" data-qty="${c.id}" style="width:64px" />
        </div>
        <div class="cost-estimate compact" data-compute-estimate="${c.id}"></div>
      </div>`;
    })
    .join("");

  const updateComputeEstimate = (chip) => {
    const quantity = Number($(`[data-qty="${chip.id}"]`)?.value || 1);
    const buy = Number(chip.effective_unit_cost ?? chip.unit_cost ?? 0) * quantity;
    const monthly = Number(chip.effective_monthly_cloud_cost ?? chip.monthly_cloud_cost ?? 0) * quantity;
    const output = $(`[data-compute-estimate="${chip.id}"]`);
    if (output) output.innerHTML = chip.cloud_only
      ? `<div class="cost-estimate-title"><span>预计首月支出</span><b>${money(monthly)}</b></div><small>此后每月持续扣除 ${money(monthly)}</small>`
      : `<div class="cost-estimate-title"><span>采购 / 云租首月</span><b>${money(buy)} / ${money(monthly)}</b></div><small>云租此后每月持续扣除 ${money(monthly)}</small>`;
  };
  chips.forEach((chip) => {
    const input = $(`[data-qty="${chip.id}"]`);
    if (input) input.oninput = () => updateComputeEstimate(chip);
    updateComputeEstimate(chip);
  });

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

function renderDatasets() {
  const g = state.game;
  const dataRes = (g.systems?.research?.catalog?.data || []).map((r) => r.id);
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
    .map((k) => `<label>${names[k] || k}<input type="number" min="0" max="10" step="0.1" value="1" data-w="${k}" /></label>`)
    .join("");

  const datasets = g.systems?.training?.datasets || [];
  const jobs = g.systems?.training?.dataset_jobs || [];
  $("#ds-summary").innerHTML = `<span class="pill">构建中 ${jobs.length}</span><span class="pill">可用 ${datasets.length}</span>`;
  $("#ds-list").innerHTML = datasets
    .map((d) => `<div class="stack-item"><div class="t">${esc(d.name)}</div><div class="s">质量 ${d.quality}${d.open_source_base ? " · 开源 base" : " · 自采语料"} · D${d.created_day || 0}</div></div>`)
    .join("") || empty("尚无可用数据集");

  const free = (g.systems?.hr?.employees || []).filter((e) => !e.assigned_to);
  $("#ds-emps").innerHTML = free
    .map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.role_name || "")}</option>`)
    .join("");

  const updateDatasetEstimate = () => {
    const useOpen = $("#ds-open").checked;
    const days = Math.max(5, Number($("#ds-days").value) || 20);
    const staffCount = $("#ds-emps").selectedOptions.length;
    const dataCatalog = g.systems?.research?.catalog?.data || [];
    const levelsById = Object.fromEntries(dataCatalog.map((item) => [item.id, Number(item.level || 0)]));
    const estimateBase = 15000 + (useOpen ? 0 : 25000)
      + keys.reduce((sum, key) => sum + Number(levelsById[key] || 0) * 3000, 0);
    const upfront = Math.max(4000, estimateBase * 0.2);
    const dailyBase = Math.max(500, (estimateBase - upfront) / days);
    const daily = dailyBase * (0.8 + 0.1 * Math.max(1, staffCount));
    $("#ds-cost-estimate").innerHTML = costEstimateHtml({
      upfront,
      daily,
      days,
      note: useOpen ? "使用开源素材；实际总成本随团队人数和完成速度变化。" : "包含自采语料预算；实际总成本随团队人数和完成速度变化。",
    });
  };
  [$("#ds-open"), $("#ds-days"), $("#ds-emps"), ...$all("#ds-weights input")].forEach((input) => {
    input.onchange = updateDatasetEstimate;
    input.oninput = updateDatasetEstimate;
  });
  updateDatasetEstimate();

  $("#ds-jobs").innerHTML = jobs
    .map((j) => {
      const pct = Number(j.progress_pct || 0);
      const staff = (j.staff || []).map((s) => s.name).join("、") || "未分配人员";
      const weights = Object.entries(j.weights || {}).sort((a, b) => b[1] - a[1]).slice(0, 3)
        .map(([k, v]) => `${names[k] || k} ${(Number(v) * 100).toFixed(0)}%`).join(" · ");
      return `<div class="train-job">
        <header><div><div class="nm">${esc(j.name)}</div><div class="muted">目标质量 ${j.quality} · ${esc(weights)}</div></div>
          <div class="tags"><span class="tag">${pct.toFixed(0)}%</span><span class="tag">${j.eta_days != null ? "ETA " + j.eta_days + "d" : "已暂停"}</span></div></header>
        <div class="progress"><i style="width:${pct}%"></i></div>
        <div class="staff-line">👤 ${esc(staff)}</div>
        <div class="muted" style="font-size:0.78rem;margin-top:0.3rem">速度 ${Number(j.speed_per_day || 0).toFixed(1)}/天 · 日耗 ${money(j.daily_cost || j.daily_cost_base || 0)} · 累计 ${money(j.total_invested || 0)}</div>
        <div style="display:flex;gap:0.35rem;margin-top:0.55rem"><button class="btn sm" data-ds-assign="${j.id}">调整人手</button><button class="btn sm ghost" data-ds-pause="${j.id}">${j.employee_ids?.length ? "撤人暂停" : "恢复/派人"}</button></div>
      </div>`;
    }).join("") || empty("暂无构建任务");

  $all("#ds-jobs [data-ds-assign]").forEach((b) => { b.onclick = () => assignDatasetJob(b.dataset.dsAssign); });
  $all("#ds-jobs [data-ds-pause]").forEach((b) => {
    b.onclick = async () => {
      const job = jobs.find((j) => j.id === b.dataset.dsPause);
      if (!job) return;
      if (job.employee_ids?.length) {
        try { applyAction(await api.assignDataset(job.id, [])); } catch (e) { toast(e.message, "err"); }
      } else assignDatasetJob(job.id);
    };
  });
}

async function assignDatasetJob(jobId) {
  const job = (state.game.systems?.training?.dataset_jobs || []).find((j) => j.id === jobId);
  if (!job) return;
  const ids = await pickEmployeesModal(`数据集人手 · ${job.name}`, {
    preselected: job.employee_ids || [], allowBusyOn: `dataset:${jobId}`,
    hint: "数据工程与产品技能会提高构建速度；撤下全部人员会暂停并保留进度。", max: job.team_cap || 12,
  });
  if (ids === null) return;
  try { applyAction(await api.assignDataset(jobId, ids)); } catch (e) { toast(e.message, "err"); }
}

function renderTraining() {
  const g = state.game;
  const dss = g.systems?.training?.datasets || [];
  // training form selects
  const types = g.systems?.training?.model_types || state.catalog.model_types || {};
  fillSelect(
    $("#tr-type"),
    Object.values(types).map((t) => [t.id, t.name]),
    $("#tr-type").value
  );
  const presets = g.systems?.training?.param_presets || state.catalog.param_presets || [];
  const paramsSelect = $("#tr-params");
  const previousParams = paramsSelect.value;
  paramsSelect.innerHTML = presets.map((preset) => {
    return `<option value="${preset.params_b}">${esc(preset.label)} · 性能 ×${Number(preset.performance_factor || parameterScaleFactor(preset.params_b)).toFixed(2)} · 训练规模 ${Number(preset.compute_units || 0).toFixed(0)} CU</option>`;
  }).join("");
  const previousOption = [...paramsSelect.options].find((option) => option.value === previousParams && !option.disabled);
  paramsSelect.value = previousOption?.value || [...paramsSelect.options].find((option) => !option.disabled)?.value || "";
  fillSelect(
    $("#tr-ds"),
    dss.map((d) => [d.id, `${d.name} (q=${d.quality})`]),
    $("#tr-ds").value
  );

  // Keep model pickers focused on the strongest commercially relevant choices.
  const baseGroups = teacherOptions(g.systems?.training || {});
  const bases = [
    ...baseGroups.own.map((m) => [m.id, `[自有 Top 1] ${m.name} · H${Number(m.hidden_score || 0).toFixed(1)}`]),
    ...baseGroups.open.map((m, index) => [m.id, `[开源 #${index + 1}] ${m.name} · H${Number(m.hidden_score || 0).toFixed(1)}`]),
    ...baseGroups.closed_competitor.map((m, index) => [m.id, `[闭源 #${index + 1}] ${m.name} · H${Number(m.hidden_score || 0).toFixed(1)}`]),
  ];
  fillSelect($("#tr-base"), bases.length ? bases : [["", "无可用基座"]], $("#tr-base").value);

  const free = (g.systems?.hr?.employees || []).filter((e) => !e.assigned_to);
  const sel = $("#tr-emps");
  sel.innerHTML = free.map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.role_name || "")}</option>`).join("");

  const updateTrainingEstimate = () => {
    const type = types[$("#tr-type").value] || {};
    const params = Number($("#tr-params").value) || 0;
    const requestedDays = Math.max(3, Number($("#tr-days").value) || 30);
    const days = Math.max(3, Math.trunc(requestedDays * Number(type.time_multiplier || 1)));
    const fromScratch = $("#tr-scratch").checked;
    const staffCount = $("#tr-emps").selectedOptions.length;
    const poolFlops = Number(g.systems?.compute?.pool?.flops_tf || 100);
    const computeFactor = fromScratch ? 1 : 0.38;
    const parameterUnits = parameterComputeUnits(params, presets);
    const requiredTf = Math.max(8, parameterUnits * 3 * Number(type.compute_multiplier || 1) * computeFactor);
    const otherDemand = (g.systems?.training?.active || [])
      .filter((job) => !job.paused)
      .reduce((sum, job) => sum + Number(job.compute_required_tf || 0), 0);
    const computeRatio = poolFlops / Math.max(1, requiredTf + otherDemand);
    const computeMult = Math.max(0.18, Math.min(3.5, Math.pow(computeRatio, 0.72)));
    const upfront = 8000 + parameterUnits * 250 * Number(type.difficulty || 1);
    let license = 0;
    if (!fromScratch) {
      const baseId = $("#tr-base").value;
      const selectedBase = [...baseGroups.own, ...baseGroups.open, ...baseGroups.closed_competitor]
        .find((item) => item.id === baseId);
      if (selectedBase?.teacher_source === "closed_competitor") {
        license = Number(selectedBase.hidden_score || 0) * 800;
      } else if (selectedBase?.teacher_source === "open") {
        license = Number(selectedBase.params_b || params) * 50;
      }
    }
    const dailyBase = upfront * 0.04 + poolFlops * 0.35 + parameterUnits * 4;
    const daily = dailyBase * (0.7 + 0.08 * Math.max(1, staffCount));
    $("#tr-cost-estimate").innerHTML = costEstimateHtml({
      upfront,
      license,
      daily,
      days,
      note: `参数规模无需研究解锁；参数性能 ×${parameterScaleFactor(params).toFixed(2)}，训练规模 ${parameterUnits.toFixed(0)} CU，算力需求约 ${requiredTf.toFixed(0)} TF，当前预计速度 ×${computeMult.toFixed(2)}。更大的模型会显著提高启动费、日耗和训练时间。`,
    });
    $("#btn-start-train").disabled = false;
  };
  [$("#tr-type"), $("#tr-params"), $("#tr-days"), $("#tr-base"), $("#tr-emps")].forEach((input) => {
    input.onchange = updateTrainingEstimate;
    input.oninput = updateTrainingEstimate;
  });
  $("#tr-scratch").onchange = (event) => {
    $("#tr-base-wrap").classList.toggle("hidden", event.target.checked);
    updateTrainingEstimate();
  };
  updateTrainingEstimate();

  const active = g.systems?.training?.active || [];
  if ($("#training-active-count")) $("#training-active-count").textContent = String(active.length);
  $("#tr-active").innerHTML =
    active
      .map((j) => {
        const pct = Number(j.progress_pct != null ? j.progress_pct : Math.min(100, (j.progress / (j.needed || 1)) * 100));
        const phases = j.phases || [];
        const phaseHtml = phases.length
          ? `<div class="phase-track">${phases
              .map((p) => {
                const at = Number(p.at || 0) * 100;
                const cls = pct >= 100 || pct >= at + 15 ? "done" : pct >= at ? "on" : "";
                return `<span class="${cls}">${esc(p.name)}</span>`;
              })
              .join("")}</div>`
          : "";
        const staff = (j.staff || []).map((s) => s.name).join("、") || "无人值守（极慢）";
        const eta = j.eta_days != null ? `ETA ${j.eta_days}d` : j.paused ? "已暂停" : "—";
        const improvement = j.improvement;
        const compute = j.compute_profile || {};
        const computePct = Math.min(100, Number(compute.ratio || 0) / 1.5 * 100);
        const computeClass = Number(compute.ratio || 0) < 0.45 ? "bad" : Number(compute.ratio || 0) < 0.9 ? "warn" : "good";
        return `<div class="train-job">
          <header>
            <div>
              <div class="nm">${esc(j.name)}</div>
              <div class="muted">${j.params_b}B · ${esc(j.model_type)} · ${esc(j.phase || "")}</div>
              ${improvement ? `<div class="job-origin">${esc(improvement.method_label)} · 源自 ${esc(improvement.source_model_name)}</div>` : ""}
            </div>
            <div class="tags">
              <span class="tag">${pct.toFixed(0)}%</span>
              <span class="tag">${eta}</span>
            </div>
          </header>
          <div class="progress"><i style="width:${pct}%"></i></div>
          ${phaseHtml}
          <div class="staff-line">👤 ${esc(staff)}</div>
          <div class="compute-impact-row ${computeClass}">
            <div><span>算力 ${Number(compute.allocated_tf || 0).toFixed(0)} / 需求 ${Number(compute.required_tf || j.compute_required_tf || 0).toFixed(0)} TF</span><b>${esc(compute.status || "计算中")} · 速度 ×${Number(compute.speed_mult || 1).toFixed(2)}</b></div>
            <div class="compute-meter"><i style="width:${computePct}%"></i></div>
          </div>
          <div class="muted" style="font-size:0.78rem;margin-top:0.3rem">速度 ${Number(j.speed_per_day||0).toFixed(1)}/天 · 日耗 ${money(j.daily_cost||0)}</div>
          <div style="display:flex;gap:0.35rem;margin-top:0.55rem;flex-wrap:wrap">
            <button class="btn sm" data-tr-assign="${j.id}">调整人手</button>
            <button class="btn sm ghost" data-tr-pause="${j.id}">${j.paused || !(j.employee_ids||[]).length ? "恢复/派人" : "撤人暂停"}</button>
          </div>
        </div>`;
      })
      .join("") || empty("无训练任务 — 立项后按天累积进度");

  $all("#tr-active [data-tr-assign]").forEach((b) => {
    b.onclick = () => assignTrainingJob(b.dataset.trAssign);
  });
  $all("#tr-active [data-tr-pause]").forEach((b) => {
    b.onclick = async () => {
      const job = (state.game.systems?.training?.active || []).find((j) => j.id === b.dataset.trPause);
      if (!job) return;
      if (job.employee_ids?.length) {
        try { applyAction(await api.assignTraining(job.id, [])); } catch (e) { toast(e.message, "err"); }
      } else {
        assignTrainingJob(job.id);
      }
    };
  });
}

async function assignTrainingJob(jobId) {
  const job = (state.game.systems?.training?.active || []).find((j) => j.id === jobId);
  if (!job) return;
  const ids = await pickEmployeesModal(`训练人手 · ${job.name}`, {
    preselected: job.employee_ids || [],
    allowBusyOn: `train:${jobId}`,
    hint: "训练进度按天累积。撤下全部人手会暂停（进度保留）。",
    max: job.team_cap || 20,
  });
  if (ids === null) return;
  try {
    applyAction(await api.assignTraining(jobId, ids));
  } catch (e) {
    toast(e.message, "err");
  }
}

async function createDataset() {
  const name = $("#ds-name").value.trim() || "数据集";
  const useOpen = $("#ds-open").checked;
  const weights = {};
  $all("#ds-weights [data-w]").forEach((i) => {
    weights[i.dataset.w] = Number(i.value) || 0;
  });
  const employee_ids = [...$("#ds-emps").selectedOptions].map((o) => o.value);
  const expected_days = Number($("#ds-days").value) || 20;
  try {
    applyAction(await api.createDataset(name, useOpen, weights, employee_ids, expected_days));
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

function renderLeaderboard() {
  const market = state.game.systems?.market || {};
  const ladders = market.model_leaderboards || {};
  const ladder = ladders[state.ladderMode] || (market.model_leaderboard || []).filter(
    (model) => state.ladderMode === "open" ? model.open_source : !model.open_source
  ).slice(0, 20);
  $all("#model-ladder-mode button").forEach((button) => {
    button.classList.toggle("on", button.dataset.v === state.ladderMode);
    button.onclick = () => {
      state.ladderMode = button.dataset.v;
      renderLeaderboard();
    };
  });
  $("#model-leaderboard").innerHTML = ladder.length
    ? ladder.slice(0, 20).map((m) => `<div class="ladder-row ${m.is_player ? "mine" : ""}">
        <span class="rank">#${m.category_rank || m.rank}</span><span class="ladder-model"><b>${esc(m.name)}</b><small>${esc(m.owner)} · ${m.params_b}B · ${esc(m.model_type)}${m.api_enabled && m.price_output != null ? ` · API $${m.price_input ?? "—"}/$${m.price_output} 每 M tokens` : ""}</small></span>
        <span>EVAL <b>${Number(m.eval_avg).toFixed(1)}</b></span><span>隐藏 <b>${Number(m.hidden_score).toFixed(0)}</b></span><span class="ladder-score">${Number(m.ladder_score).toFixed(1)}</span>
      </div>`).join("")
    : empty("发布模型后将进入公开天梯榜");
}

function renderModels() {
  const training = state.game.systems?.training || {};
  const models = training.models || [];
  const summary = $("#model-portfolio-summary");
  const released = models.filter((m) => m.released).length;
  const apiModels = models.filter((m) => m.released && m.api_enabled).length;
  const dailyRevenue = models.reduce((sum, m) => sum + Number(m.daily_revenue || 0), 0);
  summary.innerHTML = `
    <div><span>模型</span><b>${models.length}</b></div>
    <div><span>已发布</span><b>${released}</b></div>
    <div><span>API 运营</span><b>${apiModels}</b></div>
    <div><span>模型日入</span><b>${money(dailyRevenue)}</b></div>`;
  renderAutoRlPanel(training, models);

  if (!models.length) {
    $("#model-nav").innerHTML = empty("暂无模型版本");
    $("#model-detail").innerHTML = `<div class="card model-empty"><span>◇</span><h3>还没有训练完成的模型</h3><p>请先到训练工坊创建公司的第一个基座模型。</p></div>`;
    return;
  }

  if (!models.some((m) => m.id === state.selectedModelId)) {
    state.selectedModelId = models[models.length - 1].id;
  }
  const selected = models.find((m) => m.id === state.selectedModelId) || models[0];
  const methodLabels = { fine_tune: "继续微调", distill: "蒸馏优化", rl: "RL 后训练" };
  $("#model-nav").innerHTML = models
    .slice()
    .sort((a, b) => Number(b.created_day || 0) - Number(a.created_day || 0))
    .map((m) => {
      const op = m.improvement_label || (m.generation > 1 ? methodLabels[m.improvement_method] : "基座模型");
      return `<button class="model-nav-item ${m.id === selected.id ? "on" : ""}" data-model-select="${m.id}">
        <span class="model-nav-top"><b>${esc(m.name)}</b><em>${m.released ? (m.open_source ? "开源" : "线上") : "草稿"}</em></span>
        <span class="model-nav-meta"><i>G${Number(m.generation || 1)}</i>${esc(op || "基座模型")} · H${Number(m.hidden_score || 0).toFixed(1)}</span>
      </button>`;
    }).join("");
  $all("#model-nav [data-model-select]").forEach((button) => {
    button.onclick = () => {
      state.selectedModelId = button.dataset.modelSelect;
      renderModels();
    };
  });

  const evals = selected.eval_scores || {};
  const benchmarks = Object.entries(evals).filter(([key]) => key !== "average");
  const status = [];
  status.push(selected.released ? (selected.open_source ? "开源发布" : "闭源发布") : "未发布");
  if (selected.preview) status.push("Preview");
  if (selected.api_enabled) status.push("API 运营中");
  if (selected.auto_price_enabled) status.push("自动定价");
  const activeJob = (training.active || []).find(
    (job) => (job.improvement || {}).source_model_id === selected.id
  );
  const autoDistill = (training.auto_distill || []).find(
    (item) => item.id === selected.auto_distill_id || item.root_model_id === selected.id || item.current_model_id === selected.id
  );
  const children = models.filter((m) => m.parent_model_id === selected.id);
  const lineage = selected.lineage || [];
  const parent = selected.parent_model_name || selected.base_label;

  $("#model-detail").innerHTML = `<div class="card model-detail-card">
    <div class="model-detail-head">
      <div>
        <span class="eyebrow">GENERATION ${Number(selected.generation || 1)}</span>
        <h2>${esc(selected.name)}</h2>
        <p>${selected.params_b}B · 参数性能 ×${Number(selected.parameter_scale_factor || parameterScaleFactor(selected.params_b)).toFixed(2)} · ${esc(selected.model_type)}${parent ? ` · 基于 ${esc(parent)}` : " · 原生基座"}</p>
      </div>
      <div class="tags">${status.map((s) => `<span class="tag">${s}</span>`).join("")}</div>
    </div>

    <div class="model-kpis">
      <div><span>隐藏能力</span><b>${Number(selected.hidden_score || 0).toFixed(1)}</b></div>
      <div><span>EVAL 均分</span><b>${Number(evals.average || 0).toFixed(1)}</b></div>
      <div><span>API 日收入</span><b>${money(selected.daily_revenue || 0)}</b></div>
      <div><span>日活用户</span><b>${Number(selected.daily_users || 0).toFixed(0)}</b></div>
    </div>

    <div class="model-detail-grid">
      <div>
        <div class="detail-title"><span>评测表现</span><small>${benchmarks.length} 项基准</small></div>
        <div class="benchmark-grid">${benchmarks.length ? benchmarks.map(([key, value]) => `
          <div class="benchmark-row"><span>${esc(key.replaceAll("_", " ").toUpperCase())}</span><div><i style="width:${Math.min(100, Number(value || 0))}%"></i></div><b>${Number(value).toFixed(1)}</b></div>`).join("") : empty("暂无细分评测")}</div>
      </div>
      <div>
        <div class="detail-title"><span>版本谱系</span><small>${lineage.length + 1} 代记录</small></div>
        <div class="lineage-strip">
          ${lineage.map((node, index) => `<span><i>G${index + 1}</i><b>${esc(node.name || node.id)}</b><small>${esc(methodLabels[node.method] || "基座")}</small></span><em>→</em>`).join("")}
          <span class="current"><i>G${Number(selected.generation || 1)}</i><b>${esc(selected.name)}</b><small>当前版本</small></span>
        </div>
        <div class="detail-title version-title"><span>直接衍生版本</span><small>${children.length} 个</small></div>
        <div class="child-versions">${children.length ? children.map((m) => `<button data-child-model="${m.id}"><b>${esc(m.name)}</b><span>${esc(m.improvement_label || "后训练")} · H${Number(m.hidden_score).toFixed(1)}</span></button>`).join("") : `<p class="muted">尚无衍生版本</p>`}</div>
      </div>
    </div>

    <div class="detail-title action-title"><span>继续迭代这个版本</span><small>完成后生成独立的新版本</small></div>
    ${activeJob ? `<div class="active-improvement"><span class="pulse-dot"></span><div><b>${esc(activeJob.improvement?.method_label)}进行中：${esc(activeJob.name)}</b><small>${Number(activeJob.progress_pct || 0).toFixed(0)}% · ${esc(activeJob.phase || "处理中")} · ${activeJob.eta_days != null ? `预计 ${activeJob.eta_days} 天` : "等待资源"}</small></div></div>` : `
    <div class="model-action-grid">
      <button class="model-action-card fine-tune" data-improve="fine_tune"><span>FT</span><div><b>继续微调</b><p>使用专项数据集提升领域性能，收益稳定且可控。</p><small>中等成本 · 依赖数据质量</small></div></button>
      <button class="model-action-card distill" data-improve="distill"><span>DS</span><div><b>蒸馏优化</b><p>从更强教师模型迁移能力，以较低算力取得提升。</p><small>低成本 · 需要教师模型</small></div></button>
      <button class="model-action-card rl" data-improve="rl"><span>RL</span><div><b>RL 后训练</b><p>通过奖励建模强化推理、智能体表现与对齐能力。</p><small>高潜力 · 成本较高</small></div></button>
    </div>`}

    <div class="auto-distill-panel ${autoDistill?.enabled ? "active" : ""}">
      <div class="auto-distill-head">
        <div><span class="auto-distill-mark">AUTO DS</span><div><b>连续自动蒸馏</b><p>${autoDistill ? esc(autoDistill.status_message || "等待调度") : "自动选择教师与训练员工，逐代蒸馏到目标能力的 90%。"}</p></div></div>
        <div class="actions">${autoDistill?.enabled ? `<button class="btn sm danger" data-auto-distill-stop>关闭自动蒸馏</button><button class="btn sm ghost" data-auto-distill-config>调整策略</button>` : `<button class="btn sm primary" data-auto-distill-config>${autoDistill ? "重新开启自动蒸馏" : "开启自动蒸馏"}</button>`}</div>
      </div>
      ${autoDistill ? `<div class="auto-distill-progress"><div><span>最新版 ${esc(autoDistill.current_model_name || "—")} · H${Number(autoDistill.current_score || 0).toFixed(1)}</span><b>目标 H${Number(autoDistill.threshold_score || 0).toFixed(1)} · ${Number(autoDistill.progress_pct || 0).toFixed(0)}%</b></div><div class="progress"><i style="width:${Math.min(100, Number(autoDistill.progress_pct || 0))}%"></i></div><div class="auto-distill-meta"><span>${esc(autoDistill.mode_name || autoDistill.mode)}</span><span>教师 ${esc(autoDistill.teacher_model_name || "待选择")}</span><span>已完成 ${Number(autoDistill.cycles_completed || 0)} 轮</span>${autoDistill.employee_name ? `<span>负责人 ${esc(autoDistill.employee_name)}</span>` : ""}</div></div>` : ""}
    </div>

    <div class="model-commerce">
      <div><b>商业状态</b><span>${selected.released && selected.api_enabled ? `API $${selected.price_input}/M 输入 · $${selected.price_output}/M 输出` : selected.released ? "已发布，API 未启用" : "尚未发布，可先继续优化或直接上线"}</span>${selected.auto_price_enabled ? `<small class="pricing-auto-note">${esc(selected.auto_price_reason || "每 7 天根据市场收益自动微调")}${selected.auto_price_estimated_daily_revenue != null ? ` · 预计日收入 ${money(selected.auto_price_estimated_daily_revenue)}` : ""}</small>` : ""}</div>
      <div class="actions">${!selected.released ? `<button class="btn sm primary" data-rel="${selected.id}" data-os="0">闭源发布</button><button class="btn sm" data-rel="${selected.id}" data-os="1">开源发布</button><button class="btn sm ghost" data-rel="${selected.id}" data-os="0" data-prev="1">Preview</button>` : selected.api_enabled ? `<button class="btn sm" data-price="${selected.id}">手动调整价格</button><button class="btn sm ${selected.auto_price_enabled ? "ghost" : "primary"}" data-auto-price="${selected.id}" data-enabled="${selected.auto_price_enabled ? "0" : "1"}">${selected.auto_price_enabled ? "关闭自动定价" : "开启自动定价"}</button>` : ""}</div>
    </div>
  </div>`;

  $all("#model-detail [data-improve]").forEach((button) => {
    button.onclick = () => openImprovementModal(selected, button.dataset.improve);
  });
  $all("#model-detail [data-child-model]").forEach((button) => {
    button.onclick = () => {
      state.selectedModelId = button.dataset.childModel;
      renderModels();
    };
  });
  $("#model-detail [data-auto-distill-config]").onclick = () => openAutoDistillModal(selected, autoDistill);
  const stopAutoDistill = $("#model-detail [data-auto-distill-stop]");
  if (stopAutoDistill) {
    stopAutoDistill.onclick = async () => {
      try {
        applyAction(await api.setAutoDistill(selected.id, false, autoDistill?.mode || "open"));
      } catch (error) {
        toast(error.message, "err");
      }
    };
  }
  $all("#model-detail [data-rel]").forEach((b) => {
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
  $all("#model-detail [data-price]").forEach((b) => {
    b.onclick = async () => {
      const m = models.find((x) => x.id === b.dataset.price);
      if (m?.auto_price_enabled && !confirm("手动调价会关闭该模型的自动定价，是否继续？")) return;
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
  $all("#model-detail [data-auto-price]").forEach((button) => {
    button.onclick = async () => {
      try {
        button.disabled = true;
        applyAction(await api.setAutoPrice(button.dataset.autoPrice, button.dataset.enabled === "1"));
      } catch (error) {
        button.disabled = false;
        toast(error.message, "err");
      }
    };
  });
}

function renderAutoRlPanel(training, models) {
  const panel = $("#model-auto-rl");
  if (!panel) return;
  const automation = training.auto_rl || {};
  const strongest = models.slice().sort((a, b) =>
    Number(b.hidden_score || 0) - Number(a.hidden_score || 0)
    || Number(b.eval_scores?.average || 0) - Number(a.eval_scores?.average || 0)
    || Number(b.created_day || 0) - Number(a.created_day || 0)
  )[0] || null;
  const activeJob = (training.active || []).find((job) => job.auto_rl);
  const params = Number(strongest?.params_b || 0);
  const parameterUnits = strongest ? parameterComputeUnits(params, training.param_presets) : 0;
  const upfront = strongest ? 7000 + parameterUnits * 120 : 0;
  const poolFlops = Number(state.game.systems?.compute?.pool?.flops_tf || 100);
  const factor = 0.24;
  const dailyBase = strongest
    ? upfront * 0.025 + poolFlops * 0.1 * factor + parameterUnits * 0.9 * factor
    : 0;
  const daily = dailyBase * 0.78;
  const estimatedTotal = upfront + daily * 14;
  const type = (training.model_types || {})[strongest?.model_type || "text"] || {};
  const requiredTf = strongest
    ? Math.max(8, parameterUnits * 3 * Number(type.compute_multiplier || 1) * factor)
    : 0;
  const statusLabel = automation.enabled
    ? automation.status === "running" ? "运行中" : "自动等待"
    : automation.status === "stopping" ? "停止中" : "未开启";
  panel.className = `card model-auto-rl ${automation.enabled ? "active" : ""}`;
  panel.innerHTML = `<div class="model-auto-rl-main">
    <div class="auto-rl-brand"><span>AUTO RL</span><div><span class="eyebrow">AUTONOMOUS POST-TRAINING</span><h3>自动 RL 后训练</h3><p>${esc(automation.status_message || "持续对公司当前最强模型进行 RL 后训练，每轮自动重新选模并匹配最佳空闲员工。")}</p></div></div>
    <div class="auto-rl-switch"><span class="status-dot"></span><b>${statusLabel}</b><button class="btn ${automation.enabled ? "ghost" : "primary"}" data-auto-rl-toggle>${automation.enabled ? "关闭自动 RL" : "开启自动 RL"}</button></div>
  </div>
  <div class="auto-rl-grid">
    <div><span>当前最强模型</span><b>${esc(strongest?.name || "等待首个模型")}</b><small>${strongest ? `${params}B · H${Number(strongest.hidden_score || 0).toFixed(1)}` : "模型完成后自动接管"}</small></div>
    <div><span>自动负责人</span><b>${esc(automation.employee_name || "等待匹配")}</b><small>${automation.employee_fit != null ? `RL 匹配度 ${Number(automation.employee_fit).toFixed(0)}` : "按 RL / 对齐 / ML 理论动态选择"}</small></div>
    <div><span>训练进度</span><b>${activeJob ? `${Number(activeJob.progress_pct || 0).toFixed(0)}%` : `${Number(automation.cycles_completed || 0)} 轮`}</b><small>${activeJob ? `${esc(activeJob.phase || "处理中")} · ${activeJob.eta_days != null ? `约 ${activeJob.eta_days} 天` : "等待资源"}` : "每轮完成后重新比较最强版本"}</small></div>
    <div class="auto-rl-cost"><span>预计单轮费用</span><b>${strongest ? money(estimatedTotal) : "—"}</b><small>${strongest ? `启动 ${money(upfront)} + 日耗约 ${money(daily)} × 14 天 · ${requiredTf.toFixed(0)} TF` : "生成模型后自动计算"}</small></div>
  </div>`;
  panel.querySelector("[data-auto-rl-toggle]").onclick = async () => {
    try {
      panel.querySelector("[data-auto-rl-toggle]").disabled = true;
      applyAction(await api.setAutoRl(!automation.enabled));
    } catch (error) {
      panel.querySelector("[data-auto-rl-toggle]").disabled = false;
      toast(error.message, "err");
    }
  };
}

function teacherOptions(training, excludedModelId = null) {
  const own = (training.models || [])
    .filter((item) => item.id !== excludedModelId)
    .sort((a, b) => Number(b.hidden_score || 0) - Number(a.hidden_score || 0))
    .slice(0, 1)
    .map((item) => ({ ...item, teacher_source: "own" }));
  const openById = new Map();
  [...(training.open_models || []), ...(training.competitor_models || []).filter((item) => item.source === "open")]
    .forEach((item) => openById.set(item.id, { ...item, teacher_source: "open" }));
  const closed = (training.competitor_models || [])
    .filter((item) => item.source === "closed_competitor" || (!item.open_source && item.source !== "open"))
    .sort((a, b) => Number(b.hidden_score || 0) - Number(a.hidden_score || 0))
    .slice(0, 10)
    .map((item) => ({ ...item, teacher_source: "closed_competitor" }));
  const open = [...openById.values()]
    .sort((a, b) => Number(b.hidden_score || 0) - Number(a.hidden_score || 0))
    .slice(0, 10);
  return { own, open, closed_competitor: closed };
}

function modelFamilyName(model) {
  if (model.family_name) return model.family_name;
  let name = model.lineage?.[0]?.name || model.name || "Model";
  const suffix = /(?:-(?:AutoRL|AutoDS|FT|SFT|DS|Distill|RL)(?:-?v\d+)?(?:-c\d+)?|-v\d+)$/i;
  let previous = null;
  while (name !== previous) {
    previous = name;
    name = name.replace(suffix, "");
  }
  return name || "Model";
}

function openAutoDistillModal(model, config = null) {
  const training = state.game.systems?.training || {};
  const source = (training.models || []).find((item) => item.id === config?.current_model_id) || model;
  const groups = teacherOptions(training, source.id);
  const employees = (state.game.systems?.hr?.employees || []).filter((employee) => !employee.assigned_to);
  const fit = (employee) => {
    const skills = employee.skills || {};
    return Number(skills.ml_theory || 0) * 0.58 + Number(skills.systems || 0) * 0.3 + Number(skills.data_eng || 0) * 0.12;
  };
  const suggestedEmployee = employees.slice().sort((a, b) => fit(b) - fit(a))[0];
  const initialMode = config?.mode || "open";
  const body = document.createElement("div");
  body.innerHTML = `<div class="improve-modal-head"><span>∞</span><div><b>连续自动蒸馏 · ${esc(source.name)}</b><p>每轮完成后自动使用最新版继续蒸馏，达到自动选择教师隐藏能力的 90% 后停止。</p></div></div>
    <div class="auto-mode-grid">
      <label class="auto-mode"><input type="radio" name="auto-distill-mode" value="open" ${initialMode === "open" ? "checked" : ""}/><span><b>开源优先</b><small>选择最强同类开源教师，授权成本最低</small></span></label>
      <label class="auto-mode"><input type="radio" name="auto-distill-mode" value="closed" ${initialMode === "closed" ? "checked" : ""}/><span><b>闭源优先</b><small>选择最强闭源竞品教师，需要持续支付授权费</small></span></label>
      <label class="auto-mode"><input type="radio" name="auto-distill-mode" value="frontier" ${initialMode === "frontier" ? "checked" : ""}/><span><b>最领先</b><small>不计来源，始终追踪能力最高的同类型教师</small></span></label>
    </div>
    <div id="auto-distill-preview"></div>
    <div class="cost-estimate" id="auto-distill-cost"></div>
    <p class="modal-note">费用为单轮预估。自动蒸馏可能执行多轮，每轮都会重新支付启动费、教师授权费和训练日耗；资金、算力或人员不足时会自动等待。</p>`;
  const footer = document.createElement("div");
  footer.className = "modal-actions";
  footer.innerHTML = `${config?.enabled ? `<button class="btn danger" data-disable>关闭自动蒸馏</button>` : ""}<button class="btn ghost" data-cancel>取消</button><button class="btn primary" data-submit>${config?.enabled ? "保存策略" : "开启自动蒸馏"}</button>`;
  showModal({ title: "自动蒸馏设置", body, footer });

  const selectTeacher = (mode) => {
    let candidates = mode === "open"
      ? groups.open
      : mode === "closed"
      ? groups.closed_competitor
      : [...groups.own, ...groups.open, ...groups.closed_competitor];
    candidates = candidates.filter((item) => (item.model_type || "text") === (source.model_type || "text"));
    return candidates.sort((a, b) => Number(b.hidden_score || 0) - Number(a.hidden_score || 0))[0] || null;
  };
  const refresh = () => {
    const mode = body.querySelector('input[name="auto-distill-mode"]:checked').value;
    const teacher = selectTeacher(mode);
    const target = Number(teacher?.hidden_score || 0) * 0.9;
    const progress = target > 0 ? Math.min(100, Number(source.hidden_score || 0) / target * 100) : 0;
    body.querySelector("#auto-distill-preview").innerHTML = teacher
      ? `<div class="auto-distill-preview"><div><span>预计教师</span><b>${esc(teacher.name)}</b><small>${teacher.teacher_source === "closed_competitor" ? "竞品闭源" : teacher.teacher_source === "open" ? "开源" : "自有"} · H${Number(teacher.hidden_score).toFixed(1)}</small></div><div><span>停止目标</span><b>H${target.toFixed(1)}</b><small>当前 H${Number(source.hidden_score || 0).toFixed(1)} · 已达 ${progress.toFixed(0)}%</small></div><div><span>自动负责人</span><b>${esc(suggestedEmployee?.name || "等待人员")}</b><small>${suggestedEmployee ? `蒸馏匹配 ${fit(suggestedEmployee).toFixed(0)}` : "没有合适的空闲员工"}</small></div></div>`
      : `<div class="auto-distill-preview empty"><span>当前策略下没有同类型教师模型，开启后将保持等待。</span></div>`;
    const params = Number(source.params_b || 7);
    const parameterUnits = parameterComputeUnits(params, training.param_presets);
    const upfront = 3500 + parameterUnits * 55;
    const licenseFee = teacher?.teacher_source === "closed_competitor"
      ? Number(teacher.hidden_score || 0) * 550
      : teacher?.teacher_source === "open"
      ? Number(teacher.params_b || 0) * 35
      : 0;
    const factor = 0.12;
    const poolFlops = Number(state.game.systems?.compute?.pool?.flops_tf || 100);
    const dailyBase = upfront * 0.025 + poolFlops * 0.1 * factor + parameterUnits * 0.9 * factor;
    const daily = dailyBase * 0.78;
    const type = (training.model_types || {})[source.model_type || "text"] || {};
    const requiredTf = Math.max(8, parameterUnits * 3 * Number(type.compute_multiplier || 1) * factor);
    const otherDemand = (training.active || []).filter((job) => !job.paused)
      .reduce((sum, job) => sum + Number(job.compute_required_tf || 0), 0);
    const computeMult = Math.max(0.18, Math.min(3.5, Math.pow(poolFlops / Math.max(1, requiredTf + otherDemand), 0.72)));
    body.querySelector("#auto-distill-cost").innerHTML = costEstimateHtml({
      upfront,
      license: licenseFee,
      daily,
      days: 10,
      note: `单轮算力需求约 ${requiredTf.toFixed(0)} TF，当前预计速度 ×${computeMult.toFixed(2)}。`,
    });
  };
  body.querySelectorAll('input[name="auto-distill-mode"]').forEach((input) => {
    input.onchange = refresh;
  });
  refresh();
  footer.querySelector("[data-cancel]").onclick = () => closeModal(null);
  const disable = footer.querySelector("[data-disable]");
  if (disable) disable.onclick = async () => {
    try {
      disable.disabled = true;
      const result = await api.setAutoDistill(model.id, false, config?.mode || "open");
      closeModal(true);
      applyAction(result);
    } catch (error) {
      disable.disabled = false;
      toast(error.message, "err");
    }
  };
  footer.querySelector("[data-submit]").onclick = async () => {
    const mode = body.querySelector('input[name="auto-distill-mode"]:checked').value;
    try {
      footer.querySelector("[data-submit]").disabled = true;
      const result = await api.setAutoDistill(model.id, true, mode);
      closeModal(true);
      applyAction(result);
    } catch (error) {
      footer.querySelector("[data-submit]").disabled = false;
      toast(error.message, "err");
    }
  };
}

function openStandaloneDistillModal() {
  const training = state.game.systems?.training || {};
  const groups = teacherOptions(training);
  const datasets = training.datasets || [];
  const presets = training.param_presets || state.catalog.param_presets || [];
  const employees = (state.game.systems?.hr?.employees || []).filter((employee) => !employee.assigned_to);
  const body = document.createElement("div");
  body.innerHTML = `<div class="improve-modal-head"><span>DS</span><div><b>从教师模型新建蒸馏模型</b><p>无需先有自有基座。可购买闭源竞品输出授权，训练一个更小、更低成本的自有模型。</p></div></div>
    <label>模型名称<input id="distill-name" placeholder="新蒸馏模型" /></label>
    <label>教师来源<select id="distill-source"><option value="closed_competitor">竞品闭源模型</option><option value="open">开源模型</option><option value="own">自有模型</option></select></label>
    <label>教师模型<select id="distill-teacher"></select></label>
    <div id="distill-license" class="modal-note"></div>
    <label>目标参数量<select id="distill-params">${presets.map((preset) => `<option value="${preset.params_b}">${esc(preset.label)} · ${Number(preset.compute_units || 0).toFixed(0)} CU</option>`).join("")}</select></label>
    <label>训练数据集<select id="distill-dataset">${datasets.map((dataset) => `<option value="${dataset.id}">${esc(dataset.name)} · Q${Number(dataset.quality).toFixed(2)}</option>`).join("")}</select></label>
    <label>训练周期（天）<input id="distill-days" type="number" min="3" max="180" value="14" /></label>
    <label>分配员工（可多选）<select id="distill-employees" multiple size="6">${employees.map((employee) => `<option value="${employee.id}">${esc(employee.name)} · ${esc(employee.role_name || employee.role || "")}</option>`).join("")}</select></label>`;
  body.insertAdjacentHTML("beforeend", `<div class="cost-estimate" id="distill-cost-estimate"></div>`);
  const footer = document.createElement("div");
  footer.className = "modal-actions";
  footer.innerHTML = `<button class="btn ghost" data-cancel>取消</button><button class="btn primary" data-submit>开始蒸馏</button>`;
  showModal({ title: "新建蒸馏模型", body, footer });

  const sourceSelect = body.querySelector("#distill-source");
  const teacherSelect = body.querySelector("#distill-teacher");
  const license = body.querySelector("#distill-license");
  const refreshTeachers = () => {
    const source = sourceSelect.value;
    const items = groups[source] || [];
    teacherSelect.innerHTML = items.length
      ? items.map((item) => `<option value="${item.id}">${esc(item.name)}${item.company ? ` · ${esc(item.company)}` : ""} · H${Number(item.hidden_score || 0).toFixed(1)}</option>`).join("")
      : `<option value="">该来源暂无可用教师模型</option>`;
    const refreshLicense = () => {
      const teacher = items.find((item) => item.id === teacherSelect.value);
      const fee = source === "closed_competitor"
        ? Number(teacher?.hidden_score || 0) * 1000
        : source === "open"
        ? Number(teacher?.params_b || 0) * 80
        : Number(teacher?.params_b || 0) * 40;
      license.textContent = teacher
        ? `${source === "closed_competitor" ? "闭源输出授权与采样" : "教师调用"}预计费用 ${money(fee)}，另计训练启动费与每日算力成本。`
        : "请选择可用的教师模型。";
      updateDistillBudget();
    };
    teacherSelect.onchange = refreshLicense;
    refreshLicense();
  };
  sourceSelect.onchange = refreshTeachers;
  const updateDistillBudget = () => {
    const source = sourceSelect.value;
    const teacher = (groups[source] || []).find((item) => item.id === teacherSelect.value);
    const params = Number(body.querySelector("#distill-params").value || 0);
    const parameterUnits = parameterComputeUnits(params, training.param_presets);
    const type = (training.model_types || {})[teacher?.model_type || "text"] || {};
    const requestedDays = Math.max(3, Number(body.querySelector("#distill-days").value) || 14);
    const days = Math.max(3, Math.trunc(requestedDays * Number(type.time_multiplier || 1)));
    const staffCount = body.querySelector("#distill-employees").selectedOptions.length;
    const poolFlops = Number(state.game.systems?.compute?.pool?.flops_tf || 100);
    const requiredTf = Math.max(8, parameterUnits * 3 * Number(type.compute_multiplier || 1) * 0.26);
    const otherDemand = (training.active || []).filter((job) => !job.paused)
      .reduce((sum, job) => sum + Number(job.compute_required_tf || 0), 0);
    const computeMult = Math.max(0.18, Math.min(3.5, Math.pow(poolFlops / Math.max(1, requiredTf + otherDemand), 0.72)));
    const licenseFee = source === "closed_competitor"
      ? Number(teacher?.hidden_score || 0) * 1000
      : source === "open"
      ? Number(teacher?.params_b || 0) * 80
      : Number(teacher?.params_b || 0) * 40;
    const upfront = 8000 + parameterUnits * 250 * Number(type.difficulty || 1);
    const dailyBase = upfront * 0.04 + poolFlops * 0.35 + parameterUnits * 4;
    const daily = dailyBase * (0.7 + 0.08 * Math.max(1, staffCount));
    body.querySelector("#distill-cost-estimate").innerHTML = costEstimateHtml({
      upfront,
      license: licenseFee,
      daily,
      days,
      note: `该参数规模为 ${parameterUnits.toFixed(0)} CU，蒸馏算力需求约 ${requiredTf.toFixed(0)} TF，当前预计速度 ×${computeMult.toFixed(2)}。还需满足对应模型容量研究等级。`,
    });
  };
  [body.querySelector("#distill-params"), body.querySelector("#distill-days"), body.querySelector("#distill-employees")].forEach((input) => {
    input.onchange = updateDistillBudget;
    input.oninput = updateDistillBudget;
  });
  refreshTeachers();

  footer.querySelector("[data-cancel]").onclick = () => closeModal(null);
  footer.querySelector("[data-submit]").onclick = async () => {
    const source = sourceSelect.value;
    const teacher = (groups[source] || []).find((item) => item.id === teacherSelect.value);
    if (!teacher) {
      toast("当前来源没有可用的教师模型", "err");
      return;
    }
    const employee_ids = [...body.querySelector("#distill-employees").selectedOptions].map((option) => option.value);
    const payload = {
      name: body.querySelector("#distill-name").value.trim() || `${teacher.name}-Distill`,
      teacher_model_id: teacher.id,
      teacher_source: source,
      params_b: Number(body.querySelector("#distill-params").value),
      dataset_id: body.querySelector("#distill-dataset").value,
      expected_days: Number(body.querySelector("#distill-days").value) || 14,
      employee_ids,
      model_type: teacher.model_type || "text",
    };
    try {
      footer.querySelector("[data-submit]").disabled = true;
      const result = await api.distill(payload);
      closeModal(true);
      applyAction(result);
    } catch (error) {
      footer.querySelector("[data-submit]").disabled = false;
      toast(error.message, "err");
    }
  };
}

function openImprovementModal(model, method) {
  const methods = {
    fine_tune: { title: "继续微调", code: "FT", days: 14, hint: "专项数据质量与 ML / 数据工程技能决定收益。" },
    distill: { title: "蒸馏优化", code: "DS", days: 10, hint: "教师越强，知识迁移空间越大；竞品闭源教师会产生授权费。" },
    rl: { title: "RL 后训练", code: "RL", days: 18, hint: "RL 与对齐技能、相关研究等级会显著影响最终收益。" },
  };
  const meta = methods[method];
  const training = state.game.systems?.training || {};
  const datasets = training.datasets || [];
  const employees = (state.game.systems?.hr?.employees || []).filter((employee) => !employee.assigned_to);
  const groupedTeachers = teacherOptions(training, model.id);
  const teachers = [
    ...groupedTeachers.own.map((item) => [`own:${item.id}`, `[自有] ${item.name} · H${Number(item.hidden_score).toFixed(1)}`]),
    ...groupedTeachers.open.map((item) => [`open:${item.id}`, `[开源] ${item.name} · H${Number(item.hidden_score).toFixed(1)}`]),
    ...groupedTeachers.closed_competitor.map((item) => [`closed_competitor:${item.id}`, `[竞品闭源] ${item.name} · ${item.company || "未知公司"} · H${Number(item.hidden_score).toFixed(1)}`]),
  ];
  const familyName = modelFamilyName(model);
  const versionNumber = Math.max(
    1,
    ...(training.models || [])
      .filter((item) => modelFamilyName(item) === familyName)
      .map((item) => Number(item.version_number || item.generation || 1))
  ) + 1;
  const body = document.createElement("div");
  body.innerHTML = `<div class="improve-modal-head"><span>${meta.code}</span><div><b>${esc(meta.title)} · ${esc(model.name)}</b><p>${esc(meta.hint)}</p></div></div>
    <label>新版本名称<input id="improve-name" value="${esc(familyName)}-v${String(versionNumber).padStart(2, "0")}" /></label>
    <label>训练周期（天）<input id="improve-days" type="number" min="5" max="90" value="${meta.days}" /></label>
    <label class="${method === "fine_tune" ? "" : "optional-field"}">数据集${method === "fine_tune" ? "" : "（可选）"}<select id="improve-dataset">${datasets.length ? datasets.map((dataset) => `<option value="${dataset.id}" ${dataset.id === model.dataset_id ? "selected" : ""}>${esc(dataset.name)} · Q${Number(dataset.quality).toFixed(2)}</option>`).join("") : `<option value="">暂无可用数据集</option>`}</select></label>
    ${method === "distill" ? `<label>教师模型<select id="improve-teacher">${teachers.length ? teachers.map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join("") : `<option value="">暂无可用教师</option>`}</select></label>` : ""}
    <label>分配员工（可多选）<select id="improve-employees" multiple size="6">${employees.map((employee) => `<option value="${employee.id}">${esc(employee.name)} · ${esc(employee.role_name || employee.role || "")}</option>`).join("")}</select></label>
    <p class="modal-note">未分配员工时任务仍可启动，但进展会非常缓慢；可稍后在训练队列调整团队。</p>
    <div class="cost-estimate" id="improve-cost-estimate"></div>`;
  const footer = document.createElement("div");
  footer.className = "modal-actions";
  footer.innerHTML = `<button class="btn ghost" data-cancel>取消</button><button class="btn primary" data-submit>启动${esc(meta.title)}</button>`;
  showModal({ title: `模型后训练 · ${meta.title}`, body, footer });
  const updateImprovementBudget = () => {
    const params = Number(model.params_b || 7);
    const days = Math.max(5, Number(body.querySelector("#improve-days").value) || meta.days);
    const staffCount = body.querySelector("#improve-employees").selectedOptions.length;
    const poolFlops = Number(state.game.systems?.compute?.pool?.flops_tf || 100);
    const factor = { fine_tune: 0.18, distill: 0.12, rl: 0.24 }[method];
    const parameterUnits = parameterComputeUnits(params, training.param_presets);
    const upfront = {
      fine_tune: 4500 + parameterUnits * 90,
      distill: 3500 + parameterUnits * 55,
      rl: 7000 + parameterUnits * 120,
    }[method];
    const teacherValue = body.querySelector("#improve-teacher")?.value || "";
    const separator = teacherValue.indexOf(":");
    const source = separator >= 0 ? teacherValue.slice(0, separator) : "own";
    const teacherId = separator >= 0 ? teacherValue.slice(separator + 1) : null;
    const teacher = (groupedTeachers[source] || []).find((item) => item.id === teacherId);
    const licenseFee = method === "distill"
      ? source === "closed_competitor"
        ? Number(teacher?.hidden_score || 0) * 550
        : source === "open"
        ? Number(teacher?.params_b || 0) * 35
        : 0
      : 0;
    const dailyBase = upfront * 0.025 + poolFlops * 0.1 * factor + parameterUnits * 0.9 * factor;
    const daily = dailyBase * (0.7 + 0.08 * Math.max(1, staffCount));
    const type = (training.model_types || {})[model.model_type || "text"] || {};
    const requiredTf = Math.max(8, parameterUnits * 3 * Number(type.compute_multiplier || 1) * factor);
    const otherDemand = (training.active || []).filter((job) => !job.paused)
      .reduce((sum, job) => sum + Number(job.compute_required_tf || 0), 0);
    const computeMult = Math.max(0.18, Math.min(3.5, Math.pow(poolFlops / Math.max(1, requiredTf + otherDemand), 0.72)));
    body.querySelector("#improve-cost-estimate").innerHTML = costEstimateHtml({
      upfront,
      license: licenseFee,
      daily,
      days,
      note: `算力需求约 ${requiredTf.toFixed(0)} TF，计入现有任务后预计速度 ×${computeMult.toFixed(2)}。实际完成时间变化时，持续费用也会变化。`,
    });
  };
  [body.querySelector("#improve-days"), body.querySelector("#improve-employees"), body.querySelector("#improve-teacher")].filter(Boolean).forEach((input) => {
    input.onchange = updateImprovementBudget;
    input.oninput = updateImprovementBudget;
  });
  updateImprovementBudget();
  footer.querySelector("[data-cancel]").onclick = () => closeModal(null);
  footer.querySelector("[data-submit]").onclick = async () => {
    const teacherValue = body.querySelector("#improve-teacher")?.value || "";
    const separator = teacherValue.indexOf(":");
    const employee_ids = [...body.querySelector("#improve-employees").selectedOptions].map((option) => option.value);
    const payload = {
      model_id: model.id,
      method,
      name: body.querySelector("#improve-name").value.trim(),
      dataset_id: body.querySelector("#improve-dataset").value || null,
      expected_days: Number(body.querySelector("#improve-days").value) || meta.days,
      employee_ids,
      teacher_source: separator >= 0 ? teacherValue.slice(0, separator) : "own",
      teacher_model_id: separator >= 0 ? teacherValue.slice(separator + 1) : null,
    };
    try {
      footer.querySelector("[data-submit]").disabled = true;
      const result = await api.improveModel(payload);
      closeModal(true);
      applyAction(result);
    } catch (error) {
      footer.querySelector("[data-submit]").disabled = false;
      toast(error.message, "err");
    }
  };
}

function renderMarket() {
  const g = state.game;
  const segs = g.systems?.market?.segments || {};
  const users = g.systems?.market?.segment_users || {};
  const ai = g.systems?.competitors || {};
  const threat = Number(ai.threat_index || 0);
  const market = g.systems?.market || {};
  const marketShare = Number(market.player_api_market_share || 0) * 100;
  const openRivals = $("#btn-open-rivals");
  if (openRivals) openRivals.onclick = () => setTab("rivals");
  const openFinance = $("#btn-open-finance");
  if (openFinance) openFinance.onclick = () => setTab("finance");

  $("#revenue-summary").innerHTML = `
    <div class="income-card"><span>API 日收入</span><b>${money(market.api_daily_revenue || 0)}</b><small>全市场 ${money(market.total_api_market_daily_revenue || 0)}/日</small></div>
    <div class="income-card"><span>合同日收入</span><b>${money(market.contract_daily_revenue || 0)}</b></div>
    <div class="income-card"><span>API 市占率</span><b>${marketShare.toFixed(1)}%</b><small>由能力、动态 EVAL、价格与声誉共同决定</small></div>
    <div class="income-card"><span>API 市场阶段</span><b>×${Number(market.api_market_multiplier || 1).toFixed(2)}</b><small>市场随时间与前沿能力扩张</small></div>
    <div class="income-card"><span>毛收入月化</span><b>${money((market.daily_revenue || 0) * 30)}</b><small>净利润请前往财务状况查看</small></div>`;
  renderContracts(market);

  const dynamicEvals = market.dynamic_evals || [];
  $("#market-evals").innerHTML = dynamicEvals.length
    ? dynamicEvals.slice().reverse().map((item) => `<div class="dynamic-eval-card">
        <header><span class="tag warn">第 ${Number(item.generation || 1)} 代</span><b>${esc(item.name)}</b></header>
        <p>${esc(item.description || "")}</p>
        <div class="tags"><span class="tag">难度 ×${Number(item.difficulty || 1).toFixed(2)}</span><span class="tag">市场权重 ${Number(item.weight || 1).toFixed(2)}</span><span class="tag">D${item.created_day} 发布</span></div>
      </div>`).join("")
    : `<div class="muted">首个新评测预计在 D${market.next_eval_day ?? "—"} 左右发布；之后会持续出现更难的新基准。</div>`;

  if ($("#threat-pill")) {
    const threatColor = threat > 70 ? "var(--bad)" : threat > 40 ? "var(--warn)" : "var(--good)";
    $("#threat-pill").innerHTML = `
      <span class="pill" style="border-color:${threatColor};color:${threatColor}">竞争压力 ${threat.toFixed(0)}</span>
      <span class="pill">对手 ${ (ai.rivals || ai.competitors || []).length }</span>
      <span class="pill">竞品模型 ${ (ai.models || []).length }</span>
      <span class="pill">已破产 ${ (ai.bankruptcies || []).length }</span>
      <span class="pill">下次潜在入场 D${ai.next_entrant_day ?? "—"}</span>`;
  }

  $("#market-segments").innerHTML = Object.values(segs)
    .map((s) => {
      return `<div class="stack-item">
        <div class="t">${esc(s.name)} <span class="badge">我方 ${Number(users[s.id] || 0).toFixed(0)} · 对手 ${Number(market.competitor_segment_users?.[s.id] || 0).toFixed(0)}</span></div>
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
  const poachEstimates = g.systems?.hr?.poach_estimates || {};
  const marketComps = $("#market-comps");
  if (marketComps) marketComps.innerHTML = comps
    .map((c) => {
      const fs = c.flagship;
      const tier = c.tier || "challenger";
      const topRes = (c.top_research || [])
        .slice(0, 3)
        .map((r) => `<span class="tag">${esc(r.id)} ${r.level}</span>`)
        .join("");
      const normal = poachEstimates[c.id]?.["1.5"];
      const premium = poachEstimates[c.id]?.["2.2"];
      const poachLabel = (estimate) => estimate
        ? `${money(estimate.min_total)}–${money(estimate.max_total)}；失败费 ${money(estimate.min_search)}–${money(estimate.max_search)}`
        : "目标确定后结算";
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
        <div class="rival-business"><b>${esc(c.business_model_name || "混合商业化")}</b><span>日收入 ${money(c.daily_revenue || 0)} · ${Number(c.daily_profit || 0) >= 0 ? "盈利" : "亏损"} ${money(Math.abs(Number(c.daily_profit || 0)))}</span></div>
        <div class="personality">${esc(c.personality || c.strategy_desc || "")}</div>
        ${
          fs
            ? `<div class="flagship"><b>旗舰</b> ${esc(fs.name)} · H${fs.hidden_score}
                · EVAL ${Number(fs.eval_avg || 0).toFixed(1)}
                · ${fs.open_source ? "开源" : "闭源"}
                ${fs.api_enabled !== false && fs.price_output != null ? ` · API 输入 $${fs.price_input ?? "—"}/M · 输出 $${fs.price_output}/M` : ""}
                ${fs.distilled_from_player ? ` · <span class="tag warn">蒸馏自 ${esc(fs.teacher_model_name || "玩家模型")}</span>` : ""}
              </div>`
            : ""
        }
        <div class="tags">
          <span class="tag">声誉 ${Number(c.public_rep || 0).toFixed(0)}</span>
          <span class="tag">开源比 ${((c.open_ratio || 0) * 100).toFixed(0)}%</span>
          <span class="tag">员工 ${c.employee_count ?? "—"}</span>
          <span class="tag">模型 ${c.models_count ?? 0}</span>
          <span class="tag ${c.financial_status === "healthy" ? "good" : "warn"}">${c.financial_status === "healthy" ? "财务健康" : c.financial_status === "distressed" ? `现金紧张 · ${c.runway_days ?? "?"}天` : "资不抵债"}</span>
        </div>
        <div class="tags mt">${topRes}</div>
        <div class="poach-budget">挖角预计费用取决于随机锁定的人才；失败仍收取 30% 搜寻费。</div>
        <div class="actions">
          <button class="btn sm" data-poach="${c.id}" title="预计 ${poachLabel(normal)}">挖角 1.5× · ${normal ? `${money(normal.min_total)}–${money(normal.max_total)}` : "待估"}</button>
          <button class="btn sm" data-poach="${c.id}" data-mult="2.2" title="预计 ${poachLabel(premium)}">高价 2.2× · ${premium ? `${money(premium.min_total)}–${money(premium.max_total)}` : "待估"}</button>
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
              ${m.api_enabled ? ` · API 输入 $${m.price_input ?? "—"}/M / 输出 $${m.price_output}/M · 日入 ${money(m.daily_revenue || 0)}` : ""}
              · ${m.model_type || "text"}${m.distilled_from_player ? ` · <span class="tag warn">蒸馏自 ${esc(m.teacher_model_name || "玩家模型")}</span>` : ""}</div>
          </div>`
          )
          .join("")
      : empty("暂无竞品模型");
  }
}

function renderRivals() {
  const g = state.game;
  const ai = g.systems?.competitors || {};
  const rivals = (ai.rivals || ai.competitors || []).slice().sort((a, b) => {
    const tiers = { titan: 3, challenger: 2, startup: 1 };
    return (tiers[b.tier] || 0) - (tiers[a.tier] || 0) || Number(b.capital || 0) - Number(a.capital || 0);
  });
  const profitable = rivals.filter((rival) => Number(rival.daily_profit || 0) >= 0).length;
  const distressed = rivals.filter((rival) => rival.financial_status !== "healthy").length;
  const bankruptcies = ai.bankruptcies || [];
  $("#rivals-summary").innerHTML = `
    <div><span>在营公司</span><b>${rivals.length}</b></div>
    <div><span>当前盈利</span><b>${profitable}</b></div>
    <div><span>财务承压</span><b>${distressed}</b></div>
    <div><span>累计破产</span><b>${bankruptcies.length}</b></div>`;

  const log = ai.action_log || [];
  $("#rivals-log").innerHTML = log.length
    ? log.slice().reverse().map((item) => `<div class="log-line"><span class="d">D${item.day}</span><span class="m">${esc(item.msg)}</span></div>`).join("")
    : empty("暂无竞争动态");
  $("#rivals-bankruptcies").innerHTML = bankruptcies.length
    ? bankruptcies.slice().reverse().map((item) => `<div class="stack-item"><div class="t">${esc(item.name)} <span class="tag bad">D${item.day} 破产</span></div><div class="s">${esc(item.business_model_name || "未知商业模式")} · 最终资金 ${money(item.final_capital || 0)}</div></div>`).join("")
    : empty("目前尚无竞争对手破产");

  const poachEstimates = g.systems?.hr?.poach_estimates || {};
  $("#rivals-directory").innerHTML = rivals.length
    ? rivals.map((rival) => {
        const profit = Number(rival.daily_profit || 0);
        const topResearch = (rival.top_research || []).slice(0, 5).map((item) => `${item.id} Lv.${item.level}`).join(" · ");
        const models = rival.top_models || [];
        const revenue = rival.revenue_breakdown || {};
        const normal = poachEstimates[rival.id]?.["1.5"];
        return `<article class="rival-intel-card" style="--rc:${rival.color || "#38bdf8"}">
          <div class="rival-intel-head">
            <div>
              <span class="eyebrow">${esc(rival.tier || "challenger")} · ${esc(rival.country || "")}</span>
              <h3>${esc(rival.name)}</h3>
              <p>${esc(rival.business_model_name || "混合商业化")} · ${esc(rival.strategy_name || rival.strategy || "")}</p>
            </div>
            <div class="rival-finance">
              <div><span>现金</span><b>${money(rival.capital || 0)}</b></div>
              <div><span>日收入</span><b>${money(rival.daily_revenue || 0)}</b></div>
              <div><span>日成本</span><b>${money(rival.daily_cost || 0)}</b></div>
              <div><span>日利润</span><b style="color:${profit >= 0 ? "var(--good)" : "var(--bad)"}">${profit >= 0 ? "+" : "−"}${money(Math.abs(profit))}</b></div>
            </div>
            <div class="actions"><button class="btn sm" data-rival-poach="${rival.id}">挖角 1.5×${normal ? ` · ${money(normal.min_total)}起` : ""}</button></div>
          </div>
          <div class="tags" style="padding:.7rem 1rem 0">
            <span class="tag">实力 ${(Number(rival.strength || 0) * 100).toFixed(0)}</span>
            <span class="tag">声誉 ${Number(rival.public_rep || 0).toFixed(0)}</span>
            <span class="tag">政府关系 ${Number(rival.gov_relation || 0).toFixed(0)}</span>
            <span class="tag">员工 ${rival.employee_count ?? 0}</span>
            <span class="tag">开源比 ${(Number(rival.open_ratio || 0) * 100).toFixed(0)}%</span>
            <span class="tag ${rival.financial_status === "healthy" ? "good" : "warn"}">${rival.financial_status === "healthy" ? "财务健康" : rival.financial_status === "distressed" ? `承压 · 跑道 ${rival.runway_days ?? "?"} 天` : "资不抵债"}</span>
            <span class="tag">API ${money(revenue.api || 0)}/日</span>
            <span class="tag">合同 ${money(revenue.contracts || 0)}/日</span>
            <span class="tag">生态 ${money(revenue.ecosystem || 0)}/日</span>
            <span class="tag">政府 ${money(revenue.government || 0)}/日</span>
          </div>
          <div style="padding:.55rem 1rem 0" class="muted">重点研究：${esc(topResearch || "暂无")}</div>
          <div class="rival-model-top">${models.length ? models.map((model, index) => `<div class="rival-model-mini">
            <span>#${index + 1} · ${model.open_source ? "开源" : "闭源"}</span>
            <b>${esc(model.name)}</b>
            <small>H${Number(model.hidden_score || 0).toFixed(1)} · EVAL ${Number(model.eval_avg || 0).toFixed(1)} · ${model.params_b}B<br>${model.api_enabled ? `输入 $${model.price_input ?? "—"}/M · 输出 $${model.price_output ?? "—"}/M<br>API 日入 ${money(model.daily_revenue || 0)}` : "API 未运营"}${model.distilled_from_player ? `<br><span class="warn">蒸馏自 ${esc(model.teacher_model_name || "玩家模型")}</span>` : ""}</small>
          </div>`).join("") : empty("该公司暂无在榜模型")}</div>
        </article>`;
      }).join("")
    : empty("目前没有在营竞争对手；之后仍可能有新公司入场。");

  $all("#rivals-directory [data-rival-poach]").forEach((button) => {
    button.onclick = async () => {
      try {
        applyAction(await api.poach(button.dataset.rivalPoach, 1.5));
      } catch (error) {
        toast(error.message, "err");
      }
    };
  });
}

function renderContracts(market) {
  const active = market.active_contracts || [];
  $("#active-contracts").innerHTML = active.length
    ? active.map((c) => `<div class="stack-item"><div class="t">${esc(c.buyer)} <span class="tag good">履约中</span></div><div class="s">${esc(c.model_name)} · ${c.duration_years}年 · ${money(c.monthly_revenue)}/月 · D${c.end_day} 到期 · 累计 ${money(c.total_earned)}</div></div>`).join("")
    : `<div class="muted">尚无生效合同</div>`;

  const typeName = { enterprise: "企业", government: "政府" };
  $("#contract-offers").innerHTML = (market.contract_offers || []).map((o) => {
    const req = o.requirements || {};
    const reqs = [
      req.model_types?.length ? `类型 ${req.model_types.join("/")}` : "",
      req.min_eval ? `EVAL≥${req.min_eval}` : "",
      req.min_safety ? `安全≥${req.min_safety}` : "",
      req.min_hidden ? `隐藏≥${req.min_hidden}` : "",
      req.min_gov_relation ? `政府关系≥${req.min_gov_relation}` : "",
      ...Object.entries(req.min_benchmarks || {}).map(([key, value]) => `${key.toUpperCase()}≥${value}`),
    ].filter(Boolean);
    const eligible = (o.model_assessments || []).filter((a) => a.eligible);
    const assessments = (o.model_assessments || []).map((a) => `<option value="${a.model_id}" ${a.eligible ? "" : "disabled"}>${esc(a.model_name)}${a.eligible ? " ✓" : " — " + esc(a.issues.join("、"))}</option>`).join("");
    return `<div class="contract-card ${o.active ? "active" : ""} ${o.dynamic ? "dynamic" : ""}">
      <header><div><span class="tag">${typeName[o.buyer_type] || o.buyer_type}</span>${o.dynamic ? '<span class="tag warn">限时高难</span>' : ""}<h4>${esc(o.buyer)}</h4></div>${o.active ? '<span class="tag good">已签约</span>' : o.expires_day ? `<span class="tag">D${o.expires_day} 截止</span>` : ""}</header>
      <p>${esc(o.description || "")}</p><div class="tags">${reqs.map((r) => `<span class="tag warn">${esc(r)}</span>`).join("")}</div>
      <label>投标模型<select data-contract-model="${o.id}">${assessments || '<option value="">暂无训练完成模型</option>'}</select></label>
      <label>合同期限<select data-contract-years="${o.id}">${(o.duration_options || []).map((d) => `<option value="${d.years}">${d.years}年 · ${money(d.monthly_revenue)}/月</option>`).join("")}</select></label>
      <button class="btn sm primary" data-sign-contract="${o.id}" ${o.active || o.expired || !eligible.length ? "disabled" : ""}>${o.active ? "合同履约中" : o.expired ? "采购已截止" : eligible.length ? "签署合同" : "暂无合格模型"}</button>
    </div>`;
  }).join("") || empty("暂无采购机会");

  $all("#contract-offers [data-sign-contract]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.signContract;
      const modelId = $(`[data-contract-model="${id}"]`).value;
      const years = Number($(`[data-contract-years="${id}"]`).value);
      try { applyAction(await api.signContract(id, modelId, years)); } catch (e) { toast(e.message, "err"); }
    };
  });
}

function renderFinance() {
  const finance = state.game.systems?.finance || {};
  const statement = finance.financial_statement || {};
  const income = statement.income || {};
  const expenses = statement.expenses || {};
  const netIncome = Number(statement.monthly_net_income || 0);
  const netCashFlow = Number(statement.monthly_net_cash_flow || 0);

  $("#finance-summary").innerHTML = `
    <div class="income-card"><span>月化总收入</span><b>${money(income.total || 0)}</b><small>API 与采购合同收入</small></div>
    <div class="income-card outflow-card"><span>月化总支出</span><b>${money(expenses.total || 0)}</b><small>含工资、研究与负债利息</small></div>
    <div class="income-card net-card ${netIncome >= 0 ? "positive" : "negative"}"><span>月度净利润</span><b>${money(netIncome)}</b><small>总收入 − 全部经营支出</small></div>
    <div class="income-card net-card ${netCashFlow >= 0 ? "positive" : "negative"}"><span>月度净现金流</span><b>${money(netCashFlow)}</b><small>净利润 − 偿还贷款本金</small></div>`;

  const breakdown = (items, total, kind) => items.map(([label, value]) => {
    const amount = Number(value || 0);
    const width = total > 0 ? Math.max(amount > 0 ? 2 : 0, amount / total * 100) : 0;
    return `<div class="finance-breakdown-row"><div><span>${label}</span><b>${money(amount)}</b></div><div class="finance-meter ${kind}"><i style="width:${Math.min(100, width)}%"></i></div></div>`;
  }).join("");

  $("#finance-income-breakdown").innerHTML = breakdown([
    ["API 收入", income.api],
    ["长期采购合同", income.contracts],
  ], Number(income.total || 0), "income") || empty("当前没有经营收入");

  $("#finance-expense-breakdown").innerHTML = breakdown([
    ["员工薪酬", expenses.payroll],
    ["云算力租赁", expenses.cloud_compute],
    ["研究投入", expenses.research],
    ["模型训练", expenses.model_training],
    ["数据集构建", expenses.dataset_building],
    ["负债利息", expenses.debt_interest],
    ["收入分成融资成本", expenses.revenue_financing_cost],
  ], Number(expenses.total || 0), "expense") || empty("当前没有经营支出");

  const runway = statement.runway_months == null
    ? "已实现正现金流"
    : `按当前消耗可维持 ${Number(statement.runway_months).toFixed(1)} 个月`;
  $("#finance-cashflow-status").innerHTML = `
    <div class="cashflow-copy"><span class="eyebrow">CASH FLOW BRIDGE</span><h3>利润到现金流</h3><p>${runway}；当前现金 ${money(statement.capital || 0)}。</p></div>
    <div class="cashflow-equation">
      <div><span>月度净利润</span><b class="${netIncome >= 0 ? "good-text" : "bad-text"}">${money(netIncome)}</b></div>
      <em>−</em><div><span>偿还融资本金</span><b>${money(statement.monthly_financing_principal || statement.monthly_debt_principal || 0)}</b></div>
      <em>=</em><div><span>月度净现金流</span><b class="${netCashFlow >= 0 ? "good-text" : "bad-text"}">${money(netCashFlow)}</b></div>
    </div>`;

}

function renderFunding() {
  const finance = state.game.systems?.finance || {};
  const statement = finance.financial_statement || {};
  const expenses = statement.expenses || {};
  const score = Number(finance.credit_score || 0);
  const orb = $("#credit-orb");
  if (orb) {
    orb.querySelector("b").textContent = score.toFixed(0);
    orb.style.setProperty("--credit", `${Math.min(100, score) * 3.6}deg`);
    orb.classList.toggle("good", score >= 70);
    orb.classList.toggle("warn", score >= 45 && score < 70);
    orb.classList.toggle("bad", score < 45);
  }

  const revenueBalance = (finance.active_revenue_financing || []).reduce((sum, item) => sum + Number(item.remaining || 0), 0);
  $("#funding-summary").innerHTML = `
    <div class="income-card"><span>创始团队持股</span><b>${(Number(finance.founder_ownership ?? 1) * 100).toFixed(1)}%</b><small>累计股权融资 ${money(finance.equity_raised || 0)}</small></div>
    <div class="income-card debt-card"><span>贷款余额</span><b>${money(finance.total_balance || 0)}</b><small>固定还款债务</small></div>
    <div class="income-card outflow-card"><span>收入分成待还</span><b>${money(revenueBalance)}</b><small>预计本月 ${money(statement.monthly_revenue_financing_payment || 0)}</small></div>
    <div class="income-card"><span>累计科研补助</span><b>${money(finance.grant_funding || 0)}</b><small>无需偿还或稀释</small></div>`;

  const toolType = { equity: "股权融资", revenue_share: "收入分成", grant: "无偿补助" };
  $("#funding-tools").innerHTML = (finance.funding_tools || []).map((tool) => {
    const detail = tool.type === "equity"
      ? `出让 ${(Number(tool.equity_percent || 0) * 100).toFixed(1)}% 股权`
      : tool.type === "revenue_share"
      ? `收入分成 ${(Number(tool.revenue_share || 0) * 100).toFixed(0)}% · 偿还 ${Number(tool.repayment_multiple || 1).toFixed(2)}×`
      : "无需偿还 · 不稀释股权";
    return `<div class="funding-tool-card ${tool.eligible ? "eligible" : "locked"}" style="--funding-color:${tool.color || "#38bdf8"}">
      <header><span>${toolType[tool.type] || esc(tool.type)}</span><b>${money(tool.amount || 0)}</b></header>
      <h3>${esc(tool.name)}</h3><small>${esc(tool.provider || "")}</small><p>${esc(tool.description || "")}</p>
      <div class="funding-tool-detail">${detail}</div>
      ${tool.eligible
        ? `<button class="btn primary" data-use-funding-tool="${tool.id}">启用该融资工具</button>`
        : `<div class="loan-issues">${(tool.issues || []).map((issue) => `<span>${esc(issue)}</span>`).join("")}</div><button class="btn" disabled>暂未满足条件</button>`}
    </div>`;
  }).join("") || empty("暂无非贷款融资工具");

  $all("#funding-tools [data-use-funding-tool]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("确认使用该融资工具？相关股权或收入分成成本不可撤销。")) return;
      try { applyAction(await api.useFundingTool(button.dataset.useFundingTool)); } catch (error) { toast(error.message, "err"); }
    };
  });

  const revenueFinancing = finance.active_revenue_financing || [];
  $("#active-revenue-financing").innerHTML = revenueFinancing.length
    ? revenueFinancing.map((item) => {
        const target = Number(item.repayment_target || 1);
        const progress = Math.max(0, Math.min(100, (1 - Number(item.remaining || 0) / target) * 100));
        return `<div class="loan-row"><div class="loan-mark">%</div><div class="loan-main"><div class="loan-title"><b>${esc(item.name)}</b><span>${esc(item.provider || "")}</span></div><div class="progress"><i style="width:${progress}%"></i></div><div class="loan-meta"><span>待还 ${money(item.remaining)}</span><span>累计已还 ${money(item.total_repaid)}</span><span>每日收入分成 ${(Number(item.revenue_share || 0) * 100).toFixed(0)}%</span></div></div></div>`;
      }).join("")
    : `<div class="empty-state"><span>%</span><div><b>暂无收入分成融资</b><small>这类融资会随实际收入动态偿还</small></div></div>`;

  $("#finance-debt-summary").innerHTML = `
    <div class="income-card debt-card"><span>未偿本金</span><b>${money(finance.total_balance || 0)}</b><small>当前全部贷款余额</small></div>
    <div class="income-card outflow-card"><span>预计月供</span><b>${money(finance.monthly_debt_service || 0)}</b><small>本金 ${money(statement.monthly_debt_principal || 0)} · 利息 ${money(expenses.debt_interest || 0)}</small></div>
    <div class="income-card"><span>累计已付利息</span><b>${money(finance.total_interest_paid || 0)}</b><small>历史融资成本</small></div>`;

  const active = finance.active_loans || [];
  $("#active-loans").innerHTML = active.length
    ? active.map((loan) => {
        const progress = Math.min(100, Number(loan.payments_made || 0) / Math.max(1, Number(loan.term_months || 1)) * 100);
        const payoff = Number(loan.balance || 0) * (1 + Number(loan.early_repay_fee_rate || 0));
        return `<div class="loan-row">
          <div class="loan-mark">${esc((loan.lender || "贷").slice(0, 1))}</div>
          <div class="loan-main"><div class="loan-title"><b>${esc(loan.name)}</b><span>${esc(loan.lender || "")}</span></div>
            <div class="progress"><i style="width:${progress}%"></i></div>
            <div class="loan-meta"><span>余额 ${money(loan.balance)}</span><span>月供 ${money(loan.monthly_payment)}</span><span>${loan.payments_made || 0}/${loan.term_months} 期</span><span>APR ${(Number(loan.apr || 0) * 100).toFixed(1)}%</span></div>
          </div>
          <button class="btn sm" data-payoff="${loan.id}" data-payoff-amount="${payoff}">提前结清 ${money(payoff)}</button>
        </div>`;
      }).join("")
    : `<div class="empty-state"><span>◇</span><div><b>暂无贷款</b><small>保持低负债可以获得更高的后续授信额度</small></div></div>`;

  $all("#active-loans [data-payoff]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm(`确认支付 ${money(b.dataset.payoffAmount)} 提前结清？`)) return;
      try { applyAction(await api.repayLoan(b.dataset.payoff)); } catch (e) { toast(e.message, "err"); }
    };
  });

  const products = finance.products || [];
  $("#loan-products").innerHTML = products.map((p) => {
    const minimum = Number(p.min_amount || 0);
    const available = Number(p.available_amount || 0);
    const canBorrow = p.eligible && available >= minimum;
    const amount = canBorrow ? minimum : 0;
    return `<div class="loan-product ${canBorrow ? "eligible" : "locked"}" style="--loan-color:${p.color || "#38bdf8"}">
      <div class="loan-product-top"><span class="loan-type">${p.term_years} YEAR</span><span class="loan-apr">${(Number(p.apr || 0) * 100).toFixed(1)}% <small>APR</small></span></div>
      <h3>${esc(p.name)}</h3><div class="lender">${esc(p.lender || "")}</div><p>${esc(p.description || "")}</p>
      <div class="loan-specs"><div><span>可贷额度</span><b>${canBorrow ? `${money(minimum)}–${money(available)}` : "未开放"}</b></div><div><span>期限</span><b>${p.term_years} 年</b></div><div><span>手续费</span><b>${(Number(p.origination_fee_rate || 0) * 100).toFixed(1)}%</b></div></div>
      ${canBorrow ? `<label>申请金额<input type="number" data-loan-amount="${p.id}" min="${minimum}" max="${available}" step="${p.amount_step}" value="${amount}" /></label>
        <div class="loan-estimate" data-loan-estimate="${p.id}"></div><button class="btn primary" data-borrow="${p.id}">确认融资</button>`
        : `<div class="loan-issues">${(p.issues || []).map((issue) => `<span>${esc(issue)}</span>`).join("") || "当前不可申请"}</div><button class="btn" disabled>尚未满足授信条件</button>`}
    </div>`;
  }).join("") || empty("暂无贷款产品");

  const updateEstimate = (product) => {
    const input = $(`[data-loan-amount="${product.id}"]`);
    const output = $(`[data-loan-estimate="${product.id}"]`);
    if (!input || !output) return;
    const amount = Number(input.value || 0);
    const months = Number(product.term_years || 1) * 12;
    const rate = Number(product.apr || 0) / 12;
    const factor = Math.pow(1 + rate, months);
    const payment = rate > 0 ? amount * rate * factor / (factor - 1) : amount / months;
    const fee = amount * Number(product.origination_fee_rate || 0);
    const proceeds = amount - fee;
    const totalRepayment = payment * months;
    output.innerHTML = `<span>预计到账 <b>${money(proceeds)}</b></span><span>手续费 <b>${money(fee)}</b></span><span>预计月供 <b>${money(payment)}</b></span><span>预计总还款 <b>${money(totalRepayment)}</b></span>`;
  };
  products.filter((p) => p.eligible).forEach((p) => {
    const input = $(`[data-loan-amount="${p.id}"]`);
    if (input) { input.oninput = () => updateEstimate(p); updateEstimate(p); }
  });
  $all("#loan-products [data-borrow]").forEach((b) => {
    b.onclick = async () => {
      const amount = Number($(`[data-loan-amount="${b.dataset.borrow}"]`).value);
      try { applyAction(await api.borrow(b.dataset.borrow, amount)); } catch (e) { toast(e.message, "err"); }
    };
  });

  const payments = finance.payment_log || [];
  $("#loan-payment-log").innerHTML = payments.length
    ? payments.slice().reverse().map((entry) => `<div class="log-line"><span class="d">D${entry.day}</span><span class="m">${esc(entry.name)} · ${money(entry.payment)}（本金 ${money(entry.principal)} / 利息 ${money(entry.interest)}）${entry.late ? " · 逾期" : ""}</span></div>`).join("")
    : empty("首笔还款将在贷款后的下一个月度结算日产生");
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
            .map((c) => {
              const capital = Number(c.effects?.capital || 0);
              const cashImpact = capital < 0
                ? `<span class="choice-cost">预计支出 ${money(Math.abs(capital))}</span>`
                : capital > 0
                ? `<span class="choice-income">预计获得 ${money(capital)}</span>`
                : "";
              return `<button class="btn" data-choice="${c.id}" data-eid="${ev.instance_id}"><span>${esc(c.label)}</span>${cashImpact}</button>`;
            })
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
