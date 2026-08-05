/** Thin API client. Game id is sent via X-Game-Id header. */

const BASE = "/api";

let gameId = localStorage.getItem("aisim_game_id") || null;

export function getGameId() {
  return gameId;
}

export function setGameId(id) {
  gameId = id;
  if (id) localStorage.setItem("aisim_game_id", id);
  else localStorage.removeItem("aisim_game_id");
}

async function req(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && gameId) headers["X-Game-Id"] = gameId;
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  });
  let data;
  try {
    data = await res.json();
  } catch {
    data = { ok: false, message: res.statusText };
  }
  if (!res.ok) {
    const msg = data.detail || data.message || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  health: () => req("/health", { auth: false }),
  catalog: () => req("/catalog", { auth: false }),
  newGame: (body) => req("/game/new", { method: "POST", body, auth: false }),
  state: () => req("/game/state"),
  advance: (days = 1) => req("/game/advance", { method: "POST", body: { days } }),
  save: (slot, label) => req("/game/save", { method: "POST", body: { slot, label } }),
  load: (slot) => req("/game/load", { method: "POST", body: { slot }, auth: false }),
  saves: () => req("/game/saves", { auth: false }),
  deleteSave: (slot) => req(`/game/saves/${encodeURIComponent(slot)}`, { method: "DELETE", auth: false }),

  refreshHr: () => req("/hr/refresh", { method: "POST", body: {} }),
  hire: (candidate_id) => req("/hr/hire", { method: "POST", body: { candidate_id } }),
  fire: (employee_id) => req("/hr/fire", { method: "POST", body: { employee_id } }),
  trainSkill: (employee_id, skill, intensity = 1) =>
    req("/hr/train", { method: "POST", body: { employee_id, skill, intensity } }),
  setChiefScientist: (employee_id = null) =>
    req("/hr/chief-scientist", { method: "POST", body: { employee_id } }),
  setAutoHire: (enabled, max_hires_per_cycle = 3) =>
    req("/hr/auto-hire", { method: "POST", body: { enabled, max_hires_per_cycle } }),
  poach: (target_company_id, offer_multiplier = 1.5) =>
    req("/hr/poach", { method: "POST", body: { target_company_id, offer_multiplier } }),

  startResearch: (research_id, category, employee_ids = []) =>
    req("/research/start", { method: "POST", body: { research_id, category, employee_ids } }),
  assignResearch: (research_id, category, employee_ids = []) =>
    req("/research/assign", { method: "POST", body: { research_id, category, employee_ids } }),
  pauseResearch: (research_id) =>
    req("/research/pause", { method: "POST", body: { research_id } }),
  setResearchAuto: (research_id, category, enabled) =>
    req("/research/auto", { method: "POST", body: { research_id, category, enabled } }),

  purchaseCompute: (chip_id, quantity = 1, mode = "buy") =>
    req("/compute/purchase", { method: "POST", body: { chip_id, quantity, mode } }),

  createDataset: (name, use_open_source_base, data_research_weights, employee_ids = [], expected_days = 20) =>
    req("/training/dataset", {
      method: "POST",
      body: { name, use_open_source_base, data_research_weights, employee_ids, expected_days },
    }),
  assignDataset: (job_id, employee_ids = []) =>
    req("/training/dataset/assign", { method: "POST", body: { job_id, employee_ids } }),
  startTraining: (payload) => req("/training/start", { method: "POST", body: payload }),
  assignTraining: (job_id, employee_ids = []) =>
    req("/training/assign", { method: "POST", body: { job_id, employee_ids } }),
  distill: (payload) => req("/training/distill", { method: "POST", body: payload }),
  improveModel: (payload) => req("/training/improve", { method: "POST", body: payload }),
  setAutoDistill: (model_id, enabled, mode = "open") =>
    req("/training/auto-distill", { method: "POST", body: { model_id, enabled, mode } }),
  setAutoRl: (enabled) =>
    req("/training/auto-rl", { method: "POST", body: { enabled } }),
  releaseModel: (payload) => req("/training/release", { method: "POST", body: payload }),
  setPrice: (model_id, price_input, price_output) =>
    req("/training/price", { method: "POST", body: { model_id, price_input, price_output } }),
  setAutoPrice: (model_id, enabled) =>
    req("/training/auto-price", { method: "POST", body: { model_id, enabled } }),
  signContract: (offer_id, model_id, duration_years) =>
    req("/market/contracts/sign", { method: "POST", body: { offer_id, model_id, duration_years } }),
  borrow: (product_id, amount) =>
    req("/finance/borrow", { method: "POST", body: { product_id, amount } }),
  repayLoan: (loan_id) =>
    req("/finance/repay", { method: "POST", body: { loan_id } }),
  useFundingTool: (tool_id) =>
    req("/finance/tools/use", { method: "POST", body: { tool_id } }),

  eventChoice: (event_instance_id, choice_id) =>
    req("/events/choose", { method: "POST", body: { event_instance_id, choice_id } }),
};
