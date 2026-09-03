const state = {
  scopes: [],
  schedules: [],
  runs: [],
  screening: [],
  queue: [],
  verified: [],
  reviewHistory: [],
  reviewRunId: "",
  selectedObservation: null,
  registries: null,
  analysis: null,
  quality: null,
  queryYield: null,
  qualityRunId: null,
  qualityObservationId: null,
  matrixMode: "matrix_a",
  pendingRun: null,
  health: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function listValues(value) {
  return value.split(/[,，|]/).map((item) => item.trim()).filter(Boolean);
}

const objectTypeLabels = {
  writing_system: "文字系统",
  style_family: "书体",
  font: "字体",
};

function fillObjectLabels(form, snapshot, preferredLabel = null) {
  const objectType = form.elements.object_type.value;
  const options = (snapshot?.objects || []).filter((row) => row.object_type === objectType);
  form.elements.object_label.innerHTML = options.map((row) =>
    `<option value="${escapeHtml(row.canonical_label)}">${escapeHtml(row.canonical_label)}</option>`
  ).join("");
  if (preferredLabel && options.some((row) => row.canonical_label === preferredLabel)) {
    form.elements.object_label.value = preferredLabel;
  }
}

function applyRegistryToForm(form, snapshot, selected = {}) {
  const objectTypes = [...new Set((snapshot?.objects || []).map((row) => row.object_type))];
  form.elements.object_type.innerHTML = objectTypes.map((value) =>
    `<option value="${escapeHtml(value)}">${escapeHtml(objectTypeLabels[value] || value)}</option>`
  ).join("");
  if (selected.objectType && objectTypes.includes(selected.objectType)) {
    form.elements.object_type.value = selected.objectType;
  }
  fillObjectLabels(form, snapshot, selected.objectLabel);
  if (form.elements.aesthetic_terms) {
    const selectedTerms = new Set(selected.aestheticTerms || []);
    const terms = (snapshot.code_options || []).filter((row) => row.code_type === "aesthetic_term");
    form.elements.aesthetic_terms.innerHTML = terms.map((row) =>
      `<option value="${escapeHtml(row.code)}" ${selectedTerms.has(row.code) ? "selected" : ""}>${escapeHtml(row.display_zh || row.code)} · ${escapeHtml(row.code)}</option>`
    ).join("");
  }
}

function toast(message, error = false) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.className = error ? "show error" : "show";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.className = ""; }, 3200);
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function switchView(view) {
  document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === `view-${view}`));
  document.querySelectorAll(".nav-button").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  if (view === "dashboard") refreshDashboard();
  if (view === "scopes") refreshScopes();
  if (view === "review") refreshReview();
  if (view === "quality") refreshQuality();
  if (view === "runs") refreshRuns();
  if (view === "system") refreshSystem();
}

async function refreshHealth() {
  try {
    const health = await api("/api/health");
    state.health = health;
    document.querySelector("#health-dot").className = "status-dot ok";
    document.querySelector("#health-text").textContent = `本机数据库正常 · YouTube 密钥${health.youtube_api_key_configured ? "已配置" : "未配置"} · Mastodon 令牌 ${health.mastodon_access_token_count || 0} 个实例 · Reddit ${health.reddit_credentials_configured ? "已配置" : "待授权"} · TikTok ${health.tiktok_credentials_configured ? "已配置" : "待授权"} · X ${health.x_collection_ready ? "就绪" : "关闭"}`;
    document.querySelector("#metric-observations").textContent = health.observations;
    document.querySelector("#metric-active").textContent = health.active_runs;
  } catch (error) {
    document.querySelector("#health-dot").className = "status-dot bad";
    document.querySelector("#health-text").textContent = "本机服务不可用";
  }
}

function renderScopes() {
  document.querySelector("#scope-count").textContent = `${state.scopes.length} 个范围`;
  const container = document.querySelector("#scope-list");
  if (!state.scopes.length) {
    container.innerHTML = '<div class="empty-state">尚无已登记范围</div>';
    return;
  }
  container.innerHTML = state.scopes.map((scope) => {
    const schedule = state.schedules.find((item) => item.scope_id === scope.scope_id);
    const mastodonInstances = scope.platform === "mastodon" ? (scope.platform_options?.instances || []) : [];
    const redditSubreddits = scope.platform === "reddit" ? (scope.platform_options?.subreddits || []) : [];
    const tiktokQuery = scope.platform === "tiktok" ? scope.platform_options?.query : null;
    const xOptions = scope.platform === "x" ? scope.platform_options : null;
    return `
    <article class="record-item">
      <div>
        <h3>${escapeHtml(scope.name)}</h3>
        <p>${escapeHtml(scope.object_type)} / ${escapeHtml(scope.object_label)}</p>
        ${(scope.queries || []).map((query, index) => `<p>Q${index + 1} · ${escapeHtml(query.query_family || "legacy_scope_keywords")} · ${escapeHtml(query.phase || "exploratory")} · ${escapeHtml(query.exact_query || query.query_text)}</p>`).join("")}
        ${mastodonInstances.length ? `<p>选定实例 · ${mastodonInstances.map(escapeHtml).join(" · ")}</p>` : ""}
        ${redditSubreddits.length ? `<p>选定 subreddit · ${redditSubreddits.map((item) => `r/${escapeHtml(item)}`).join(" · ")} · 不代表 Reddit 全网样本</p>` : ""}
        ${tiktokQuery ? `<p>Research API AST · ${escapeHtml(JSON.stringify(tiktokQuery))} · 不代表 TikTok 全网样本</p>` : ""}
        ${xOptions ? `<p>Recent search · ${escapeHtml(xOptions.query)} · ${xOptions.page_size} posts × ${xOptions.max_pages} 页 · run cap ${xOptions.local_run_budget_microusd} µUSD</p>` : ""}
        <p>${formatDate(scope.window_start)} — ${formatDate(scope.window_end)}</p>
        <div class="meta"><span class="tag platform-tag">${escapeHtml(scope.platform)}</span>${scope.keywords.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")} ${scope.languages.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}<span class="tag ${scope.active ? "" : "status"}">${scope.active ? "活动" : "已归档"}</span>${scope.platform === "reddit" ? `<span class="tag status">${state.health?.reddit_credentials_configured ? "本机授权已配置" : "待授权"}</span>` : ""}${scope.platform === "tiktok" ? `<span class="tag status">${state.health?.tiktok_credentials_configured ? "本机授权已配置" : "待授权"}</span>` : ""}${scope.platform === "x" ? `<span class="tag status">${state.health?.x_collection_ready ? "费用门禁就绪" : "费用门禁关闭"}</span>` : ""}${schedule ? `<span class="tag">${schedule.interval_minutes} 分钟 · ${schedule.enabled ? "调度中" : "已暂停"}</span>` : ""}</div>
      </div>
      <div class="action-group">
        <button class="secondary-button" data-edit-scope="${escapeHtml(scope.scope_id)}">编辑</button>
        ${scope.active ? `<button class="run-button" data-start-scope="${escapeHtml(scope.scope_id)}">▶ 采集</button>` : ""}
        ${scope.active && schedule?.enabled ? `<button class="secondary-button" data-run-schedule="${escapeHtml(schedule.schedule_id)}">立即调度</button>` : ""}
        ${scope.active ? `<button class="quiet-button" data-archive-scope="${escapeHtml(scope.scope_id)}">归档</button>` : ""}
      </div>
    </article>`;
  }).join("");
  container.querySelectorAll("[data-start-scope]").forEach((button) => {
    button.addEventListener("click", () => startRun(button.dataset.startScope, button));
  });
  container.querySelectorAll("[data-edit-scope]").forEach((button) => {
    button.addEventListener("click", () => editScope(button.dataset.editScope));
  });
  container.querySelectorAll("[data-archive-scope]").forEach((button) => {
    button.addEventListener("click", () => archiveScope(button.dataset.archiveScope));
  });
  container.querySelectorAll("[data-run-schedule]").forEach((button) => {
    button.addEventListener("click", () => runSchedule(button.dataset.runSchedule, button));
  });
}

async function refreshScopes() {
  [state.scopes, state.schedules] = await Promise.all([api("/api/scopes"), api("/api/schedules")]);
  renderScopes();
}

function toLocalInput(value) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function toWindowInput(value, platform) {
  return platform === "tiktok" ? String(value).slice(0, 10) : toLocalInput(value);
}

function editScope(scopeId) {
  const scope = state.scopes.find((item) => item.scope_id === scopeId);
  const schedule = state.schedules.find((item) => item.scope_id === scopeId);
  if (!scope) return;
  const form = document.querySelector("#scope-form");
  form.elements.scope_id.value = scope.scope_id;
  form.elements.platform.value = scope.platform;
  form.querySelectorAll('[name="platform"]').forEach((input) => { input.disabled = true; });
  form.elements.name.value = scope.name;
  applyRegistryToForm(form, state.registries, {
    objectType: scope.object_type,
    objectLabel: scope.object_label,
  });
  form.elements.keywords.value = scope.keywords.join(", ");
  form.elements.languages.value = scope.languages.join(", ");
  form.elements.max_items.value = scope.max_items;
  form.elements.query_family.value = scope.query_family || "legacy_scope_keywords";
  form.elements.phase.value = scope.phase || "exploratory";
  form.elements.exact_query.value = scope.exact_query || scope.keywords.join(" OR ");
  const platformOptions = scope.platform_options || {};
  form.elements.mastodon_instances.value = (platformOptions.instances || []).join(", ");
  form.elements.mastodon_access_method.value = platformOptions.access_method || "hashtag_timeline";
  form.elements.mastodon_page_size.value = platformOptions.page_size || 40;
  form.elements.mastodon_max_pages_per_instance.value = platformOptions.max_pages_per_instance || 1;
  form.elements.mastodon_request_delay_seconds.value = platformOptions.request_delay_seconds ?? 1;
  form.elements.reddit_subreddits.value = (platformOptions.subreddits || []).join(", ");
  form.elements.reddit_access_method.value = platformOptions.access_method || "subreddit_search";
  form.elements.reddit_sort.value = platformOptions.sort || "relevance";
  form.elements.reddit_time_filter.value = platformOptions.time_filter || "all";
  form.elements.reddit_page_size.value = platformOptions.page_size || 100;
  form.elements.reddit_max_pages_per_subreddit.value = platformOptions.max_pages_per_subreddit || 1;
  form.elements.reddit_request_delay_seconds.value = platformOptions.request_delay_seconds ?? 1;
  form.elements.tiktok_query.value = JSON.stringify(platformOptions.query || {}, null, 2);
  form.elements.tiktok_video_page_size.value = platformOptions.video_page_size || 100;
  form.elements.tiktok_max_video_pages.value = platformOptions.max_video_pages || 1;
  form.elements.tiktok_comment_page_size.value = platformOptions.comment_page_size || 100;
  form.elements.tiktok_max_comment_pages_per_video.value = platformOptions.max_comment_pages_per_video || 1;
  form.elements.tiktok_reply_page_size.value = platformOptions.reply_page_size || 100;
  form.elements.tiktok_max_reply_pages_per_comment.value = platformOptions.max_reply_pages_per_comment || 1;
  form.elements.tiktok_request_delay_seconds.value = platformOptions.request_delay_seconds ?? 1;
  form.elements.x_page_size.value = platformOptions.page_size || 10;
  form.elements.x_max_pages.value = platformOptions.max_pages || 1;
  form.elements.x_request_delay_seconds.value = platformOptions.request_delay_seconds ?? 1;
  form.elements.x_local_run_budget_microusd.value = platformOptions.local_run_budget_microusd || 50000;
  updatePlatformControls(form);
  form.elements.max_videos.value = scope.layer_quotas?.max_videos || Math.min(scope.max_items, 50);
  form.elements.max_comment_threads_per_video.value = scope.layer_quotas?.max_comment_threads_per_video ?? 100;
  form.elements.max_replies_per_thread.value = scope.layer_quotas?.max_replies_per_thread ?? 100;
  const yieldPolicy = scope.query_yield_policy || {};
  form.elements.query_yield_evaluation_k.value = yieldPolicy.evaluation_k ?? 20;
  form.elements.query_yield_min_included_at_k.value = yieldPolicy.min_included_at_k ?? 5;
  form.elements.query_yield_min_precision_at_k.value = yieldPolicy.min_precision_at_k ?? 0.25;
  form.elements.query_yield_min_precision_lower_bound.value = yieldPolicy.min_precision_lower_bound ?? 0.10;
  form.elements.query_yield_confidence_level.value = yieldPolicy.confidence_level ?? 0.95;
  form.elements.additional_exact_query.value = "";
  document.querySelector("#add-scope-query").disabled = false;
  form.elements.window_start.value = toWindowInput(scope.window_start, scope.platform);
  form.elements.window_end.value = toWindowInput(scope.window_end, scope.platform);
  form.elements.interval_minutes.value = schedule?.interval_minutes || 60;
  form.elements.schedule_enabled.checked = schedule?.enabled || false;
  document.querySelector("#scope-submit").textContent = "更新范围";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function archiveScope(scopeId) {
  const scope = state.scopes.find((item) => item.scope_id === scopeId);
  if (!scope || !confirm(`归档“${scope.name}”并停止其调度？`)) return;
  const payload = {
    platform: scope.platform, name: scope.name, object_type: scope.object_type, object_label: scope.object_label,
    keywords: scope.keywords, languages: scope.languages, window_start: scope.window_start,
    window_end: scope.window_end, max_items: scope.max_items, active: false,
    query_family: scope.query_family, phase: scope.phase, exact_query: scope.exact_query,
    max_videos: scope.layer_quotas?.max_videos,
    max_comment_threads_per_video: scope.layer_quotas?.max_comment_threads_per_video,
    max_replies_per_thread: scope.layer_quotas?.max_replies_per_thread,
    mastodon_instances: scope.platform_options?.instances,
    mastodon_access_method: scope.platform_options?.access_method || "hashtag_timeline",
    mastodon_page_size: scope.platform_options?.page_size || 40,
    mastodon_max_pages_per_instance: scope.platform_options?.max_pages_per_instance || 1,
    mastodon_request_delay_seconds: scope.platform_options?.request_delay_seconds ?? 1,
    reddit_subreddits: scope.platform_options?.subreddits,
    reddit_access_method: scope.platform_options?.access_method || "subreddit_search",
    reddit_sort: scope.platform_options?.sort || "relevance",
    reddit_time_filter: scope.platform_options?.time_filter || "all",
    reddit_page_size: scope.platform_options?.page_size || 100,
    reddit_max_pages_per_subreddit: scope.platform_options?.max_pages_per_subreddit || 1,
    reddit_request_delay_seconds: scope.platform_options?.request_delay_seconds ?? 1,
    tiktok_query: scope.platform_options?.query,
    tiktok_video_page_size: scope.platform_options?.video_page_size || 100,
    tiktok_max_video_pages: scope.platform_options?.max_video_pages || 1,
    tiktok_comment_page_size: scope.platform_options?.comment_page_size || 100,
    tiktok_max_comment_pages_per_video: scope.platform_options?.max_comment_pages_per_video || 1,
    tiktok_reply_page_size: scope.platform_options?.reply_page_size || 100,
    tiktok_max_reply_pages_per_comment: scope.platform_options?.max_reply_pages_per_comment || 1,
    tiktok_request_delay_seconds: scope.platform_options?.request_delay_seconds ?? 1,
    x_page_size: scope.platform_options?.page_size || 10,
    x_max_pages: scope.platform_options?.max_pages || 1,
    x_request_delay_seconds: scope.platform_options?.request_delay_seconds ?? 1,
    x_local_run_budget_microusd: scope.platform_options?.local_run_budget_microusd || 50000,
  };
  try {
    await api(`/api/scopes/${encodeURIComponent(scopeId)}`, { method: "PUT", body: JSON.stringify(payload) });
    toast("范围已归档，关联调度已停止");
    await refreshScopes();
  } catch (error) { toast(error.message, true); }
}

async function runSchedule(scheduleId, button) {
  button.disabled = true;
  try {
    const run = await api(`/api/schedules/${encodeURIComponent(scheduleId)}/run`, { method: "POST" });
    if (!run.collection_run_id) {
      const messages = {
        disabled: "调度当前未启用",
        window_closed: "研究范围时间窗口已结束，调度已停止",
      };
      toast(messages[run.status] || `调度未启动：${run.status || "未知状态"}`, true);
      await refreshScopes();
      return;
    }
    toast(`调度已触发：${run.collection_run_id}`);
    switchView("runs");
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function executeStartRun(scopeId, button, budgets = {}) {
  button.disabled = true;
  try {
    const run = await api("/api/runs", { method: "POST", body: JSON.stringify({ scope_id: scopeId, ...budgets }) });
    toast(`采集已启动：${run.collection_run_id}`);
    switchView("runs");
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

function startRun(scopeId, button) {
  const scope = state.scopes.find((item) => item.scope_id === scopeId);
  if (!scope || scope.platform !== "youtube") {
    executeStartRun(scopeId, button);
    return;
  }
  const queryCount = Math.max(1, scope.queries?.length || 1);
  const searchBudget = Math.min(100, queryCount * 2);
  const quotas = scope.layer_quotas || {};
  const maxVideos = Number(quotas.max_videos || 1) * queryCount;
  const maxThreads = Math.min(Number(quotas.max_comment_threads_per_video || 0), Number(scope.max_items || 0));
  const replyPages = Number(quotas.max_replies_per_thread || 0) > 0 ? maxThreads : 0;
  const sharedBudget = Math.max(1, searchBudget * 2 + maxVideos * (maxThreads > 0 ? 1 + replyPages : 0));
  const form = document.querySelector("#run-budget-form");
  form.elements.youtube_run_search_call_budget.value = searchBudget;
  form.elements.youtube_run_shared_unit_budget.value = sharedBudget;
  state.pendingRun = { scopeId, button };
  document.querySelector("#run-budget-dialog").showModal();
}

async function selectReview(record) {
  state.selectedObservation = record.observation_id;
  document.querySelectorAll("#review-list .record-item").forEach((item) => item.classList.toggle("selected", item.dataset.id === record.observation_id));
  const form = document.querySelector("#review-form");
  form.elements.observation_id.value = record.observation_id;
  try {
    const registry = await api(`/api/observations/${encodeURIComponent(record.observation_id)}/registry`);
    applyRegistryToForm(form, registry.snapshot, {
      objectType: record.object_type,
      objectLabel: record.object_label,
      aestheticTerms: record.aesthetic_terms,
    });
    document.querySelector("#review-registry-status").textContent =
      `已锁定 object map ${registry.object_map_version} / codebook ${registry.codebook_version}`;
  } catch (error) {
    document.querySelector("#review-registry-status").textContent = error.message;
  }
  form.elements.evidence_span.value = record.evidence_span || "";
  form.elements.stance.value = record.stance || "descriptive";
  form.elements.author_role.value = record.author_role || "unknown";
  form.elements.screening_reason.value = "";
  form.elements.exclusion_reason.value = "";
  document.querySelector("#review-source").innerHTML = `${escapeHtml(record.text)}<br><a href="${escapeHtml(record.url)}" target="_blank" rel="noreferrer">打开公开原始页面 ↗</a>`;
  refreshReviewHistory(record.observation_id);
}

function renderReviewHistory() {
  document.querySelector("#history-count").textContent = state.reviewHistory.length;
  const container = document.querySelector("#review-history");
  if (!state.reviewHistory.length) {
    container.innerHTML = '<div class="empty-state compact-empty">尚无审核变更</div>';
    return;
  }
  container.innerHTML = state.reviewHistory.map((event) => `
    <article class="record-item history-item"><div><h3>${escapeHtml(event.previous_status)} → ${escapeHtml(event.new_status)}</h3><p>${formatDate(event.created_at)} · ${escapeHtml(event.reviewer_ref)}</p></div></article>`).join("");
}

async function refreshReviewHistory(observationId = state.selectedObservation) {
  if (!observationId) {
    state.reviewHistory = [];
  } else {
    state.reviewHistory = await api(`/api/review-history?observation_id=${encodeURIComponent(observationId)}`);
  }
  renderReviewHistory();
}

function renderReview() {
  document.querySelector("#queue-count").textContent = `${state.screening.length} 待筛选 · ${state.queue.length} 待编码`;
  document.querySelector("#metric-pending").textContent = state.queue.length;
  const container = document.querySelector("#review-list");
  const records = [
    ...state.screening.map((record) => ({ ...record, workflowStage: "screening" })),
    ...state.queue.map((record) => ({ ...record, workflowStage: "coding" })),
  ];
  if (!records.length) {
    container.innerHTML = '<div class="empty-state">审核队列为空</div>';
    return;
  }
  container.innerHTML = records.map((record) => `
    <article class="record-item ${record.observation_id === state.selectedObservation ? "selected" : ""}" data-id="${escapeHtml(record.observation_id)}">
      <div><h3>${escapeHtml(record.object_label || "未标注对象")}</h3><p>${escapeHtml(record.text.slice(0, 150))}</p><div class="meta"><span class="tag">${escapeHtml(record.language_bcp47 || "unknown")}</span><span class="tag status">${record.workflowStage === "screening" ? "待筛选" : "待编码"}</span></div></div>
    </article>`).join("");
  container.querySelectorAll(".record-item").forEach((item) => {
    item.addEventListener("click", () => selectReview(records.find((record) => record.observation_id === item.dataset.id)));
  });
  if (!state.selectedObservation || !records.some((record) => record.observation_id === state.selectedObservation)) selectReview(records[0]);
}

async function refreshReview() {
  const suffix = state.reviewRunId ? `?collection_run_id=${encodeURIComponent(state.reviewRunId)}` : "";
  [state.screening, state.queue, state.runs] = await Promise.all([
    api(`/api/screening-queue${suffix}`), api(`/api/review-queue${suffix}`), api("/api/runs"),
  ]);
  const select = document.querySelector("#review-run-select");
  select.innerHTML = '<option value="">全部运行</option>' + state.runs.map((run) => `<option value="${escapeHtml(run.collection_run_id)}">${escapeHtml(run.collection_run_id)} · ${escapeHtml(run.runtime_status || run.status)}</option>`).join("");
  select.value = state.reviewRunId;
  renderReview();
  if (!state.screening.length && !state.queue.length) await refreshReviewHistory(null);
}

async function submitScreening(decision) {
  const form = document.querySelector("#review-form");
  const observationId = form.elements.observation_id.value;
  const reason = form.elements.screening_reason.value.trim();
  if (!observationId) return toast("请选择候选记录", true);
  if (!reason) {
    form.elements.screening_reason.focus();
    return toast("相关性筛选必须填写理由", true);
  }
  try {
    await api(`/api/observations/${encodeURIComponent(observationId)}/screen`, {
      method: "POST",
      body: JSON.stringify({ decision, reason }),
    });
    toast({ include: "已纳入编码队列", exclude: "已从编码队列排除", uncertain: "已保留为不确定" }[decision]);
    state.selectedObservation = null;
    await refreshReview();
  } catch (error) { toast(error.message, true); }
}

function reviewPayload(status) {
  const form = document.querySelector("#review-form");
  return {
    status,
    object_type: form.elements.object_type.value,
    object_label: form.elements.object_label.value.trim(),
    aesthetic_terms: [...form.elements.aesthetic_terms.selectedOptions].map((option) => option.value),
    evidence_span: form.elements.evidence_span.value.trim() || null,
    stance: form.elements.stance.value || null,
    confidence: Number(form.elements.confidence.value),
    exclusion_reason: form.elements.exclusion_reason.value.trim() || null,
    author_role: form.elements.author_role.value === "unknown" ? null : form.elements.author_role.value,
  };
}

async function submitReview(status) {
  const form = document.querySelector("#review-form");
  const observationId = form.elements.observation_id.value;
  if (!observationId) return toast("请选择候选记录", true);
  const verificationFields = ["object_label", "aesthetic_terms", "evidence_span"];
  verificationFields.forEach((name) => { form.elements[name].required = status === "human_verified"; });
  if (status === "human_verified" && !form.reportValidity()) return;
  if (status === "excluded" && !form.elements.exclusion_reason.value.trim()) {
    form.elements.exclusion_reason.focus();
    return toast("排除记录必须填写原因", true);
  }
  try {
    await api(`/api/observations/${encodeURIComponent(observationId)}/review`, { method: "POST", body: JSON.stringify(reviewPayload(status)) });
    toast(status === "human_verified" ? "人工确认已写入审计记录" : "排除决定已写入审计记录");
    state.selectedObservation = null;
    await refreshReview();
    await refreshDashboard();
  } catch (error) {
    toast(error.message, true);
  }
}

async function openEvidence(observationId) {
  try {
    const evidence = await api(`/api/evidence/${encodeURIComponent(observationId)}`);
    const observation = evidence.observation;
    const mastodonSightings = evidence.mastodon_sightings || [];
    document.querySelector("#evidence-status").textContent = observation.annotation_status;
    document.querySelector("#evidence-content").className = "";
    document.querySelector("#evidence-content").innerHTML = `
      <section class="evidence-block"><h3>OBSERVATION</h3><p><strong>${escapeHtml(observation.object_label)}</strong> · ${escapeHtml((observation.aesthetic_terms || []).join(" / "))}</p><p>“${escapeHtml(observation.evidence_span)}”</p><p><a href="${escapeHtml(observation.url)}" target="_blank" rel="noreferrer">原始公开页面 ↗</a></p></section>
      <section class="evidence-block"><h3>QUERY</h3><p>${escapeHtml(evidence.query?.query_id)}</p><p>${escapeHtml(evidence.query?.query_text)}</p><p>${escapeHtml(evidence.query?.window_start)} — ${escapeHtml(evidence.query?.window_end)}</p></section>
      <section class="evidence-block"><h3>SOURCE</h3><p>${escapeHtml(evidence.source?.source_id)}</p><p>许可状态：${escapeHtml(evidence.source?.license_status)}</p></section>
      <section class="evidence-block"><h3>RUN MANIFEST</h3><p>${escapeHtml(evidence.run_manifest.collection_run_id)}</p><p>接收 ${evidence.run_manifest.counts.received} · 规范化 ${evidence.run_manifest.counts.normalized} · 失败 ${evidence.run_manifest.counts.failures}</p></section>
      ${mastodonSightings.length ? `<section class="evidence-block"><h3>INSTANCE SIGHTINGS · LOCAL ONLY</h3><p>${mastodonSightings.map((row) => `${escapeHtml(row.observed_instance)} · ${escapeHtml(row.visibility)} · ${escapeHtml(row.local_status_id)}`).join("<br>")}</p><pre>${escapeHtml(JSON.stringify(mastodonSightings, null, 2))}</pre></section>` : ""}
      <section class="evidence-block"><h3>RAW EVENT · LOCAL ONLY</h3><pre>${escapeHtml(JSON.stringify(evidence.raw_event, null, 2))}</pre></section>`;
    switchView("dashboard");
  } catch (error) {
    toast(error.message, true);
  }
}

function renderMatrix(analysis) {
  const mode = state.matrixMode;
  const rows = analysis[mode];
  const titles = { matrix_a: "对象 → 审美术语", matrix_b: "审美术语 → 对象", lift: "关联强度 Lift" };
  document.querySelector("#matrix-title").textContent = titles[mode];
  document.querySelectorAll("[data-matrix]").forEach((button) => button.classList.toggle("active", button.dataset.matrix === mode));
  const headers = mode === "matrix_a"
    ? ["研究对象", "术语", "P(术语 | 对象)", "计数", "口径"]
    : mode === "matrix_b"
      ? ["术语", "研究对象", "P(对象 | 术语)", "计数", "口径"]
      : ["研究对象", "术语", "Lift", "总体术语概率", "口径"];
  document.querySelector("#matrix-head").innerHTML = headers.map((value) => `<th>${value}</th>`).join("");
  const body = document.querySelector("#matrix-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty-state">尚无人工确认记录</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => {
    const evidence = state.verified.find((record) => record.object_label === row.object_label && record.aesthetic_terms.includes(row.term));
    const values = mode === "matrix_a"
      ? [row.object_label, row.term, Number(row.p_term_given_object).toFixed(3), row.pair_weight, row.exploratory === "true" ? "探索性" : "稳定"]
      : mode === "matrix_b"
        ? [row.term, row.object_label, Number(row.p_object_given_term).toFixed(3), row.pair_weight, row.exploratory === "true" ? "探索性" : "稳定"]
        : [row.object_label, row.term, Number(row.lift).toFixed(3), Number(row.p_term).toFixed(3), row.exploratory === "true" ? "探索性" : "稳定"];
    return `<tr ${evidence ? `data-observation="${escapeHtml(evidence.observation_id)}"` : ""}>
      ${values.map((value, index) => `<td class="${index >= 2 && index <= 3 ? "metric-number" : index === 4 ? "flag" : ""}">${escapeHtml(value)}</td>`).join("")}</tr>`;
  }).join("");
  body.querySelectorAll("[data-observation]").forEach((row) => row.addEventListener("click", () => openEvidence(row.dataset.observation)));
}

function renderSupportingAnalysis(analysis) {
  const trendBody = document.querySelector("#trend-body");
  trendBody.innerHTML = analysis.time_series.length
    ? analysis.time_series.map((row) => `<tr><td>${escapeHtml(row.time_bucket)}</td><td>${escapeHtml(row.object_label)}</td><td>${escapeHtml(row.term)}</td><td class="metric-number">${escapeHtml(row.record_count)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty-state">尚无趋势记录</td></tr>';
  const platform = document.querySelector("#platform-summary");
  platform.innerHTML = analysis.platform_summary.length
    ? analysis.platform_summary.map((row) => `<div><span>${escapeHtml(row.platform)}</span><strong>${row.record_count}</strong></div>`).join("")
    : '<div class="empty-state compact-empty">尚无平台记录</div>';
}

async function refreshDashboard() {
  try {
    const [analysis, queue, verified] = await Promise.all([
      api("/api/analysis"), api("/api/review-queue"), api("/api/observations?status=human_verified"),
    ]);
    state.queue = queue;
    state.verified = verified;
    state.analysis = analysis;
    document.querySelector("#metric-verified").textContent = analysis.included_records;
    document.querySelector("#metric-pending").textContent = queue.length;
    renderMatrix(analysis);
    renderSupportingAnalysis(analysis);
    refreshHealth();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderQualityWorkspace() {
  const workspace = state.quality;
  const observations = (workspace?.observations || []).filter((row) => row.screening?.decision === "include");
  document.querySelector("#quality-observation-count").textContent = observations.length;
  const list = document.querySelector("#quality-observation-list");
  list.innerHTML = observations.length ? observations.map((row) => `
    <article class="record-item ${row.observation_id === state.qualityObservationId ? "selected" : ""}" data-quality-observation="${escapeHtml(row.observation_id)}"><div><h3>${escapeHtml(row.object_label || "待形成 gold")}</h3><p>${escapeHtml(row.text.slice(0, 150))}</p><div class="meta"><span class="tag">${escapeHtml(row.annotation_status)}</span><span class="tag">${escapeHtml(row.language_bcp47 || "unknown")}</span></div></div></article>`).join("") : '<div class="empty-state">该运行没有 screening include 记录</div>';
  list.querySelectorAll("[data-quality-observation]").forEach((item) => item.addEventListener("click", () => selectQualityObservation(item.dataset.qualityObservation)));

  const annotations = workspace?.independent_annotations || [];
  const adjudications = workspace?.adjudications || [];
  document.querySelector("#quality-evidence-count").textContent = `${annotations.length} 编码 · ${adjudications.length} 裁决`;
  document.querySelector("#quality-evidence-list").innerHTML = annotations.length || adjudications.length ? [
    ...annotations.map((row) => `<article class="record-item"><div><h3>${escapeHtml(row.coder_id)} · 独立编码</h3><p>${escapeHtml(row.object_label)} / ${escapeHtml(row.aesthetic_terms.join(" · "))} / ${escapeHtml(row.stance)}</p><p>${formatDate(row.created_at)}</p></div></article>`),
    ...adjudications.map((row) => `<article class="record-item"><div><h3>${escapeHtml(row.adjudicator_id)} · 第三人裁决</h3><p>${escapeHtml(row.object_label)} / ${escapeHtml(row.aesthetic_terms.join(" · "))} / ${escapeHtml(row.stance)}</p><p>${escapeHtml(row.reason)} · ${formatDate(row.created_at)}</p></div></article>`),
  ].join("") : '<div class="empty-state">尚无独立编码或裁决</div>';

  const report = workspace?.quality_reports?.at(-1);
  const governance = workspace?.governance;
  document.querySelector("#quality-report").innerHTML = report ? `
    <div><span>最新结论</span><strong>${escapeHtml(report.status)}</strong></div><div><span>双编覆盖</span><strong>${report.double_coded_count} / ${report.required_double_coded}</strong></div>
    <div><span>对象 α</span><strong>${report.agreement.object_label.alpha ?? "不可计算"}</strong></div><div><span>立场 α</span><strong>${report.agreement.stance.alpha ?? "不可计算"}</strong></div>
    <div class="wide-definition"><span>阻断项</span><strong>${escapeHtml(report.blockers.join(" / ") || "无")}</strong></div>
    <div class="wide-definition"><span>发布治理</span><strong>${governance?.release_allowed ? "已明确授权" : "未授权"} · ${escapeHtml(governance?.reason || "—")}</strong></div>` : `<div class="wide-definition empty-state compact-empty"><span>尚无质量报告</span></div>`;

  renderQueryYield();

  if (observations.length && !observations.some((row) => row.observation_id === state.qualityObservationId)) selectQualityObservation(observations[0].observation_id);
}

function formatRate(value) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

function queryYieldStatus(status) {
  return { passed: "通过", failed: "未达标", inconclusive: "证据不足" }[status] || status;
}

function queryYieldReason(reason) {
  return {
    run_not_completed: "运行尚未完成",
    no_queries: "没有冻结 query",
    retrieved_below_evaluation_k: "候选数低于评价 k",
    rank_metadata_incomplete: "检索排名证据不完整",
    top_k_screening_incomplete: "top-k 尚未完成明确筛选",
    included_at_k_below_minimum: "top-k 纳入数低于最低线",
    precision_at_k_below_minimum: "precision@k 低于最低线",
    precision_lower_bound_below_minimum: "Wilson 下界低于最低线",
  }[reason] || reason;
}

function renderQueryYield() {
  const workspace = state.queryYield;
  const report = workspace?.current_report;
  const policy = workspace?.policy_snapshot?.policy;
  const stateLabel = document.querySelector("#query-yield-state");
  const summary = document.querySelector("#query-yield-summary");
  const body = document.querySelector("#query-yield-body");
  const promoteButton = document.querySelector("#promote-query-yield");
  const promotionForm = document.querySelector("#query-promotion-form");
  const promotionFields = document.querySelector("#query-promotion-fields");
  const promotionStatus = document.querySelector("#query-promotion-status");
  if (!report || !policy) {
    stateLabel.textContent = "未载入";
    summary.innerHTML = '<div class="wide-definition empty-state compact-empty"><span>尚无校准证据</span></div>';
    body.innerHTML = "";
    promoteButton.disabled = true;
    promotionFields.disabled = true;
    promotionStatus.textContent = "没有可晋级 query";
    return;
  }
  const mode = workspace.policy_snapshot.assessment_mode === "preregistered" ? "运行前冻结" : "事后诊断";
  const reportState = workspace.report_history.length
    ? workspace.latest_report_is_current ? "当前报告已冻结" : "冻结报告已过期"
    : "尚未冻结报告";
  const latestReport = workspace.report_history.at(-1);
  const alreadyPromoted = new Set(state.scopes.flatMap((scope) =>
    (scope.queries || []).filter((query) =>
      query.phase === "confirmatory"
      && query.promotion_evidence?.collection_run_id === state.qualityRunId
      && query.promotion_evidence?.query_yield_report_id === latestReport?.query_yield_report_id
    ).map((query) => query.promotion_evidence.source_query_id)
  ));
  const promotableQueryIds = report.calibration_passed_query_ids.filter((queryId) => !alreadyPromoted.has(queryId));
  const canPromote = promotableQueryIds.length > 0 && workspace.latest_report_is_current;
  stateLabel.textContent = `${mode} · ${reportState}`;
  promoteButton.disabled = !canPromote;
  promotionFields.disabled = !canPromote;
  promotionStatus.textContent = canPromote ? `${promotableQueryIds.length} 条 query 可晋级` : "没有可晋级 query";
  const formKey = `${state.qualityRunId}:${latestReport?.query_yield_report_id || "none"}`;
  if (promotionForm.dataset.report !== formKey) {
    const selectedRun = state.runs.find((run) => run.collection_run_id === state.qualityRunId);
    const sourceStart = selectedRun?.manifest?.window?.start;
    const sourceEnd = selectedRun?.manifest?.window?.end;
    if (sourceStart && sourceEnd) {
      const calibrationStart = new Date(sourceStart);
      const calibrationDuration = new Date(sourceEnd).getTime() - calibrationStart.getTime();
      const holdoutStart = new Date(calibrationStart.getTime() - calibrationDuration);
      promotionForm.elements.name.value = `YouTube 确认范围 ${holdoutStart.toISOString().slice(0, 10)}`;
      promotionForm.elements.window_start.value = toLocalInput(holdoutStart.toISOString());
      promotionForm.elements.window_end.value = toLocalInput(sourceStart);
    }
    promotionForm.dataset.report = formKey;
  }
  summary.innerHTML = `
    <div><span>当前结论</span><strong>${escapeHtml(queryYieldStatus(report.status))}</strong></div>
    <div><span>晋级资格</span><strong>${promotableQueryIds.length ? `${promotableQueryIds.length} 条可晋级` : "不可晋级"}</strong></div>
    <div><span>评价政策</span><strong>k=${policy.evaluation_k} · 纳入≥${policy.min_included_at_k} · precision≥${formatRate(policy.min_precision_at_k)}</strong></div>
    <div><span>不确定性最低线</span><strong>Wilson ${formatRate(policy.confidence_level)} 下界≥${formatRate(policy.min_precision_lower_bound)}</strong></div>`;
  body.innerHTML = report.query_results.length ? report.query_results.map((row, index) => {
    const interval = row.precision_at_k_interval;
    const reasons = [...row.inconclusive_reasons, ...row.failure_reasons].map(queryYieldReason);
    const selector = canPromote && promotableQueryIds.includes(row.query_id)
      ? `<label class="query-selector"><input type="checkbox" name="promotion_query_id" value="${escapeHtml(row.query_id)}" checked><span>Q${index + 1} · ${escapeHtml(row.exact_query)}</span></label>`
      : `<strong>Q${index + 1} · ${escapeHtml(row.exact_query)}</strong>`;
    return `<tr>
      <td class="query-cell">${selector}<span>${escapeHtml(row.query_family)}</span></td>
      <td>${escapeHtml(row.phase)}</td>
      <td class="metric-number">${row.retrieved_count} / ${row.resolved_count}</td>
      <td class="metric-number">${row.included_count}</td>
      <td class="metric-number">${formatRate(row.precision_at_k)}</td>
      <td class="metric-number">${interval ? `${formatRate(interval.lower)}–${formatRate(interval.upper)}` : "—"}</td>
      <td><span class="tag ${row.status === "passed" ? "" : "status"}">${escapeHtml(queryYieldStatus(row.status))}</span>${reasons.length ? `<small>${escapeHtml(reasons.join("；"))}</small>` : ""}</td>
    </tr>`;
  }).join("") : '<tr><td colspan="7" class="empty-state compact-empty">运行没有冻结 query</td></tr>';
}

async function selectQualityObservation(observationId) {
  state.qualityObservationId = observationId;
  const observation = state.quality?.observations.find((row) => row.observation_id === observationId);
  if (!observation) return;
  renderQualityWorkspace();
  const form = document.querySelector("#quality-form");
  form.elements.observation_id.value = observationId;
  form.elements.evidence_span.value = observation.evidence_span || "";
  form.elements.stance.value = observation.stance || "descriptive";
  form.elements.author_role.value = observation.author_role || "ordinary_user";
  document.querySelector("#quality-source").innerHTML = `${escapeHtml(observation.text)}<br><a href="${escapeHtml(observation.url)}" target="_blank" rel="noreferrer">打开公开原始页面 ↗</a>`;
  try {
    const registry = await api(`/api/observations/${encodeURIComponent(observationId)}/registry`);
    applyRegistryToForm(form, registry.snapshot, { objectType: observation.object_type, objectLabel: observation.object_label, aestheticTerms: observation.aesthetic_terms });
    document.querySelector("#quality-form-status").textContent = `registry ${registry.object_map_version} / ${registry.codebook_version}`;
  } catch (error) { document.querySelector("#quality-form-status").textContent = error.message; }
}

async function refreshQuality() {
  try {
    state.runs = await api("/api/runs");
    const select = document.querySelector("#quality-run-select");
    select.innerHTML = state.runs.map((run) => `<option value="${escapeHtml(run.collection_run_id)}">${escapeHtml(run.collection_run_id)} · ${escapeHtml(run.runtime_status)}</option>`).join("");
    if (!state.runs.length) {
      state.quality = null;
      state.queryYield = null;
      state.qualityRunId = null;
      renderQualityWorkspace();
      return;
    }
    if (!state.runs.some((run) => run.collection_run_id === state.qualityRunId)) state.qualityRunId = state.runs[0].collection_run_id;
    select.value = state.qualityRunId;
    [state.quality, state.queryYield] = await Promise.all([
      api(`/api/runs/${encodeURIComponent(state.qualityRunId)}/quality-workspace`),
      api(`/api/runs/${encodeURIComponent(state.qualityRunId)}/query-yield`),
    ]);
    renderQualityWorkspace();
  } catch (error) { toast(error.message, true); }
}

async function submitQualityDecision(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity() || !form.elements.observation_id.value) return;
  const common = {
    object_type: form.elements.object_type.value,
    object_label: form.elements.object_label.value,
    aesthetic_terms: [...form.elements.aesthetic_terms.selectedOptions].map((option) => option.value),
    evidence_span: form.elements.evidence_span.value.trim(),
    stance: form.elements.stance.value,
    author_role: form.elements.author_role.value,
  };
  const adjudication = form.elements.action_type.value === "adjudication";
  const payload = adjudication ? { ...common, adjudicator_id: form.elements.actor_id.value.trim(), confidence: Number(form.elements.confidence.value), reason: form.elements.reason.value.trim() } : { ...common, coder_id: form.elements.actor_id.value.trim(), language_confirmed: form.elements.language_confirmed.checked };
  try {
    const observationId = form.elements.observation_id.value;
    const path = adjudication ? "adjudicate" : "independent-annotations";
    await api(`/api/observations/${encodeURIComponent(observationId)}/${path}`, { method: "POST", body: JSON.stringify(payload) });
    toast(adjudication ? "第三人裁决已写入不可变证据" : "独立编码已写入不可变证据");
    await refreshQuality();
  } catch (error) { toast(error.message, true); }
}

async function decideRelease(releaseAllowed) {
  const reason = document.querySelector('#release-form [name="reason"]').value.trim();
  if (!reason) return toast("发布治理必须填写理由", true);
  try {
    await api(`/api/runs/${encodeURIComponent(state.qualityRunId)}/release`, { method: "POST", body: JSON.stringify({ release_allowed: releaseAllowed, reason }) });
    toast(releaseAllowed ? "研究发布已明确授权" : "研究发布授权已撤销");
    await refreshQuality();
  } catch (error) { toast(error.message, true); }
}

function renderRuns() {
  const container = document.querySelector("#run-list");
  if (!state.runs.length) {
    container.innerHTML = '<div class="empty-state">尚无采集运行</div>';
    return;
  }
  container.innerHTML = state.runs.map((run) => `
    <article class="record-item">
      <div><h3>${escapeHtml(run.collection_run_id)}</h3><p>${formatDate(run.started_at)} · ${escapeHtml(run.runtime_status)} · ${escapeHtml(run.trigger?.trigger_type || "manual")}</p><div class="meta"><span class="tag platform-tag">${escapeHtml(run.platform)}</span><span class="tag">接收 ${run.received_count}</span><span class="tag">规范化 ${run.normalized_count}</span><span class="tag status">失败 ${run.failure_count}</span>${run.latest_quality_report ? `<span class="tag ${run.latest_quality_report.status === "passed" ? "" : "status"}">质量 ${escapeHtml(run.latest_quality_report.status)}</span>` : ""}</div></div>
      <div class="action-group">
        ${run.runtime_status === "running" ? `<button class="run-button stop" data-stop-run="${escapeHtml(run.collection_run_id)}">■ 停止</button>` : `${run.runtime_status === "awaiting_screening" ? `<button class="run-button" data-continue-run="${escapeHtml(run.collection_run_id)}">▶ 继续评论采集</button>` : `<button class="secondary-button" data-retry-run="${escapeHtml(run.collection_run_id)}">↻ 重跑</button>`}<button class="secondary-button" data-quality-run="${escapeHtml(run.collection_run_id)}">质量检查</button><button class="run-button" data-export-run="${escapeHtml(run.collection_run_id)}">↓ 导出</button>`}
      </div>
    </article>`).join("");
  container.querySelectorAll("[data-stop-run]").forEach((button) => button.addEventListener("click", () => stopRun(button.dataset.stopRun, button)));
  container.querySelectorAll("[data-retry-run]").forEach((button) => button.addEventListener("click", () => retryRun(button.dataset.retryRun, button)));
  container.querySelectorAll("[data-continue-run]").forEach((button) => button.addEventListener("click", () => continueRun(button.dataset.continueRun, button)));
  container.querySelectorAll("[data-quality-run]").forEach((button) => button.addEventListener("click", () => evaluateQuality(button.dataset.qualityRun, button)));
  container.querySelectorAll("[data-export-run]").forEach((button) => button.addEventListener("click", () => exportRun(button.dataset.exportRun, button)));
}

function renderErrors(errors) {
  document.querySelector("#error-count").textContent = errors.length;
  const container = document.querySelector("#error-list");
  if (!errors.length) {
    container.innerHTML = '<div class="empty-state">没有失败记录</div>';
    return;
  }
  container.innerHTML = errors.slice(0, 50).map((error) => `
    <article class="record-item"><div><h3>${escapeHtml(error.error_code)}</h3><p class="error-message">${escapeHtml(error.message)}</p><p>${formatDate(error.created_at)} · ${error.retryable ? "可重试" : "已隔离"}</p></div></article>`).join("");
}

async function refreshRuns() {
  try {
    const [runs, errors] = await Promise.all([api("/api/runs"), api("/api/errors")]);
    state.runs = runs;
    renderRuns();
    renderErrors(errors);
    refreshHealth();
  } catch (error) {
    toast(error.message, true);
  }
}

async function stopRun(runId, button) {
  button.disabled = true;
  try {
    await api(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
    toast("采集已停止，游标和运行审计已保留");
    await refreshRuns();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

async function retryRun(runId, button) {
  button.disabled = true;
  try {
    const run = await api(`/api/runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
    toast(`重跑已启动：${run.collection_run_id}`);
    await refreshRuns();
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function continueRun(runId, button) {
  button.disabled = true;
  try {
    await api(`/api/runs/${encodeURIComponent(runId)}/continue`, { method: "POST" });
    toast("已按最新视频筛选决定继续评论采集");
    await refreshRuns();
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function evaluateQuality(runId, button) {
  button.disabled = true;
  try {
    const report = await api(`/api/runs/${encodeURIComponent(runId)}/quality`, { method: "POST" });
    const detail = report.status === "passed" ? "已通过" : `未通过：${report.blockers.join(", ")}`;
    toast(`研究发布质量检查${detail}`, report.status !== "passed");
    await refreshRuns();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function exportRun(runId, button) {
  button.disabled = true;
  try {
    const result = await api(`/api/runs/${encodeURIComponent(runId)}/export`, { method: "POST" });
    toast(`导出验证通过：${result.record_count} 条观察，${result.narrative_count} 条叙事证据`);
    window.location.assign(result.download_url);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

function formatBytes(value) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let number = Number(value || 0);
  let unit = 0;
  while (number >= 1024 && unit < units.length - 1) { number /= 1024; unit += 1; }
  return `${number.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function formatMicrousd(value) {
  if (!Number.isInteger(value)) return "—";
  return `$${(value / 1000000).toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
}

function renderSystem(monitoring, backups, audit) {
  const quota = monitoring.youtube_quota;
  const tiktokQuota = monitoring.tiktok_quota || { used_requests: 0, remaining_requests: 0, daily_request_budget: 0, reset_timezone: "UTC", policy_version: "—" };
  const mastodon = monitoring.mastodon || { state_counts: {}, sightings: 0, instances: [] };
  const xBilling = monitoring.x_billing || {};
  const xPrice = xBilling.active_price || {};
  document.querySelector("#system-database").textContent = formatBytes(monitoring.database_bytes);
  document.querySelector("#system-wal").textContent = formatBytes(monitoring.wal_bytes);
  document.querySelector("#system-disk").textContent = formatBytes(monitoring.disk_free_bytes);
  document.querySelector("#system-quota").textContent = `${quota.remaining_units} 单位 / ${quota.remaining_search_calls} 次搜索`;
  document.querySelector('#quota-form [name="daily_budget"]').value = quota.daily_budget;
  document.querySelector('#quota-form [name="search_daily_call_budget"]').value = quota.search_daily_call_budget;
  document.querySelector("#monitor-checked").textContent = formatDate(monitoring.checked_at);
  document.querySelector("#monitor-details").innerHTML = `
    <div><span>采集源</span><strong>${escapeHtml((monitoring.sources || []).join(" / "))}</strong></div>
    <div><span>YouTube 密钥</span><strong>${monitoring.youtube_api_key_configured ? "本机已配置" : "本机未配置"}</strong></div>
    <div><span>Mastodon 本机令牌</span><strong>${monitoring.mastodon_access_token_count || 0} 个实例</strong></div>
    <div><span>Reddit API</span><strong>${monitoring.reddit_credentials_configured ? `本机已配置 · ${escapeHtml(monitoring.reddit_authorization_mode)}` : "待授权"}</strong></div>
    <div><span>TikTok Research API</span><strong>${monitoring.tiktok_credentials_configured ? "本机已配置" : "待授权"}</strong></div>
    <div><span>X recent search</span><strong>${monitoring.x_collection_ready ? "凭证与费用门禁就绪" : monitoring.x_credentials_configured ? "费用门禁关闭" : "待配置"}</strong></div>
    <div><span>X post_read 价格</span><strong>${formatMicrousd(xPrice.unit_price_microusd)} · ${escapeHtml(xPrice.effective_date || "—")}</strong></div>
    <div><span>X cycle 已计 / 剩余</span><strong>${formatMicrousd(xBilling.accrued_cost_microusd)} / ${formatMicrousd(xBilling.remaining_local_cycle_microusd)}</strong></div>
    <div><span>X 本机 / Console cap</span><strong>${formatMicrousd(xBilling.local_cycle_spending_cap_microusd)} / ${formatMicrousd(xBilling.console_hard_spending_limit_microusd)}</strong></div>
    <div><span>X 费用熔断器</span><strong>${xBilling.circuit_breaker_open ? `开启 · ${escapeHtml(xBilling.circuit_breaker_reason || "未说明")}` : "关闭"}</strong></div>
    <div><span>Mastodon 实例状态</span><strong>${escapeHtml(JSON.stringify(mastodon.state_counts))}</strong></div>
    <div><span>Mastodon sightings</span><strong>${mastodon.sightings}</strong></div>
    <div><span>活动运行</span><strong>${monitoring.active_runs}</strong></div>
    <div><span>运行状态</span><strong>${escapeHtml(JSON.stringify(monitoring.run_status))}</strong></div>
    <div><span>审核状态</span><strong>${escapeHtml(JSON.stringify(monitoring.review_status))}</strong></div>
    <div><span>错误 / 可重试</span><strong>${monitoring.error_count} / ${monitoring.retryable_error_count}</strong></div>
    <div><span>调度器</span><strong>${monitoring.scheduler_running ? "运行中" : "已停止"}</strong></div>
    <div><span>YouTube 配额日</span><strong>${escapeHtml(quota.quota_date)} · ${escapeHtml(quota.reset_timezone)}</strong></div>
    <div><span>共享单位 已用 / 预算</span><strong>${quota.used_units} / ${quota.daily_budget}</strong></div>
    <div><span>搜索调用 已用 / 预算</span><strong>${quota.used_search_calls} / ${quota.search_daily_call_budget}</strong></div>
    <div><span>配额政策</span><strong>${escapeHtml(quota.policy_version)}</strong></div>
    <div><span>TikTok UTC 请求 已用 / 预算</span><strong>${tiktokQuota.used_requests} / ${tiktokQuota.daily_request_budget}</strong></div>
    <div><span>TikTok 剩余请求</span><strong>${tiktokQuota.remaining_requests} · ${escapeHtml(tiktokQuota.reset_timezone)}</strong></div>
    <div class="wide-definition"><span>TikTok 配额政策</span><strong>${escapeHtml(tiktokQuota.policy_version)}</strong></div>
    <div class="wide-definition"><span>按 API 操作用量</span><strong>${escapeHtml(JSON.stringify(quota.usage_by_operation))}</strong></div>
    <div class="wide-definition"><span>选定实例覆盖</span><strong>${escapeHtml((mastodon.instances || []).map((row) => `${row.observed_instance}: ${row.completed} 完成 / ${row.failed} 失败 / ${row.sightings} sightings`).join(" · ") || "尚无 Mastodon run")}</strong></div>
    <div class="wide-definition"><span>采样约束</span><strong>${escapeHtml(monitoring.quota_basis)}</strong></div>
    <div class="wide-definition"><span>成本口径</span><strong>${escapeHtml(monitoring.cost_basis)}</strong></div>`;

  const backupList = document.querySelector("#backup-list");
  backupList.innerHTML = backups.length ? backups.map((backup) => `
    <article class="record-item"><div><h3>${escapeHtml(backup.backup_id)}</h3><p>${formatDate(backup.created_at)} · ${formatBytes(backup.byte_size)} · ${escapeHtml(backup.reason)}</p><div class="meta"><span class="tag">schema v${backup.schema_version}</span><span class="tag">完整性 ${escapeHtml(backup.integrity_check)}</span></div></div><button class="secondary-button record-action" data-restore-backup="${escapeHtml(backup.backup_id)}">恢复</button></article>`).join("") : '<div class="empty-state">尚无数据库备份</div>';
  backupList.querySelectorAll("[data-restore-backup]").forEach((button) => button.addEventListener("click", () => restoreBackup(button.dataset.restoreBackup, button)));

  document.querySelector("#audit-count").textContent = audit.length;
  document.querySelector("#audit-list").innerHTML = audit.length ? audit.map((event) => `
    <article class="record-item"><div><h3>${escapeHtml(event.event_type)}</h3><p>${escapeHtml(event.entity_type)} / ${escapeHtml(event.entity_id)} · ${formatDate(event.created_at)}</p></div></article>`).join("") : '<div class="empty-state compact-empty">尚无操作审计</div>';
}

async function refreshSystem() {
  try {
    const [monitoring, backups, audit] = await Promise.all([api("/api/monitoring"), api("/api/backups"), api("/api/audit?limit=100")]);
    renderSystem(monitoring, backups, audit);
  } catch (error) { toast(error.message, true); }
}

async function createBackup(button) {
  button.disabled = true;
  try {
    const backup = await api("/api/backups", { method: "POST" });
    toast(`备份已校验：${backup.backup_id}`);
    await refreshSystem();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function restoreBackup(backupId, button) {
  if (!confirm(`恢复 ${backupId}？系统会先自动保存当前数据库。`)) return;
  button.disabled = true;
  try {
    const result = await api(`/api/backups/${encodeURIComponent(backupId)}/restore`, { method: "POST" });
    toast(`恢复完成；恢复前备份：${result.pre_restore_backup_id}`);
    await Promise.all([refreshSystem(), refreshScopes(), refreshDashboard()]);
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

function setDefaultWindow() {
  const start = new Date(Date.now() - 5 * 60 * 1000);
  const end = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const localValue = (date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  document.querySelector('[name="window_start"]').value = localValue(start);
  document.querySelector('[name="window_end"]').value = localValue(end);
}

function updatePlatformControls(form) {
  const isMastodon = form.elements.platform.value === "mastodon";
  const isReddit = form.elements.platform.value === "reddit";
  const isTikTok = form.elements.platform.value === "tiktok";
  const isX = form.elements.platform.value === "x";
  const mastodonOptions = form.querySelector('[data-platform-options="mastodon"]');
  mastodonOptions.hidden = !isMastodon;
  mastodonOptions.querySelectorAll("input, select").forEach((control) => {
    control.disabled = !isMastodon;
  });
  const redditOptions = form.querySelector('[data-platform-options="reddit"]');
  redditOptions.hidden = !isReddit;
  redditOptions.querySelectorAll("input, select").forEach((control) => {
    control.disabled = !isReddit;
  });
  const tiktokOptions = form.querySelector('[data-platform-options="tiktok"]');
  tiktokOptions.hidden = !isTikTok;
  tiktokOptions.querySelectorAll("input, select, textarea").forEach((control) => {
    control.disabled = !isTikTok;
  });
  const xOptions = form.querySelector('[data-platform-options="x"]');
  xOptions.hidden = !isX;
  xOptions.querySelectorAll("input").forEach((control) => {
    control.disabled = !isX;
  });
  form.elements.mastodon_instances.required = isMastodon;
  form.elements.reddit_subreddits.required = isReddit;
  form.elements.tiktok_query.required = isTikTok;
  const startInput = form.elements.window_start;
  const endInput = form.elements.window_end;
  const startValue = startInput.value;
  const endValue = endInput.value;
  if (isTikTok && startInput.type !== "date") {
    startInput.type = "date";
    endInput.type = "date";
    startInput.value = startValue.slice(0, 10);
    endInput.value = endValue.slice(0, 10);
  } else if (!isTikTok && startInput.type === "date") {
    startInput.type = "datetime-local";
    endInput.type = "datetime-local";
    startInput.value = startValue ? `${startValue}T00:00` : "";
    endInput.value = endValue ? `${endValue}T23:59` : "";
  }
  form.elements.max_videos.max = isTikTok ? 100 : 50;
  if (!isTikTok && Number(form.elements.max_videos.value) > 50) {
    form.elements.max_videos.value = 50;
  }
  form.elements.exact_query.placeholder = isMastodon
    ? "#typography"
    : isReddit || isTikTok ? "latin typography modern"
    : isX ? "(typography OR wordmark) lang:en -is:retweet"
    : '例如："Latin" typography';
}

function resetScopeForm() {
  const form = document.querySelector("#scope-form");
  form.reset();
  form.elements.scope_id.value = "";
  form.querySelectorAll('[name="platform"]').forEach((input) => { input.disabled = false; });
  form.elements.platform.value = "bluesky";
  form.elements.languages.value = "en";
  form.elements.max_items.value = 20;
  form.elements.query_family.value = "object_aesthetic";
  form.elements.phase.value = "exploratory";
  form.elements.exact_query.value = "";
  form.elements.mastodon_instances.value = "";
  form.elements.mastodon_access_method.value = "hashtag_timeline";
  form.elements.mastodon_page_size.value = 40;
  form.elements.mastodon_max_pages_per_instance.value = 1;
  form.elements.mastodon_request_delay_seconds.value = 1;
  form.elements.reddit_subreddits.value = "";
  form.elements.reddit_access_method.value = "subreddit_search";
  form.elements.reddit_sort.value = "relevance";
  form.elements.reddit_time_filter.value = "all";
  form.elements.reddit_page_size.value = 100;
  form.elements.reddit_max_pages_per_subreddit.value = 1;
  form.elements.reddit_request_delay_seconds.value = 1;
  form.elements.tiktok_query.value = JSON.stringify({
    and: [{ operation: "EQ", field_name: "keyword", field_values: ["typography"] }],
  }, null, 2);
  form.elements.tiktok_video_page_size.value = 100;
  form.elements.tiktok_max_video_pages.value = 1;
  form.elements.tiktok_comment_page_size.value = 100;
  form.elements.tiktok_max_comment_pages_per_video.value = 1;
  form.elements.tiktok_reply_page_size.value = 100;
  form.elements.tiktok_max_reply_pages_per_comment.value = 1;
  form.elements.tiktok_request_delay_seconds.value = 1;
  form.elements.x_page_size.value = 10;
  form.elements.x_max_pages.value = 1;
  form.elements.x_request_delay_seconds.value = 1;
  form.elements.x_local_run_budget_microusd.value = 50000;
  form.elements.max_videos.value = 10;
  form.elements.max_comment_threads_per_video.value = 20;
  form.elements.max_replies_per_thread.value = 5;
  form.elements.query_yield_evaluation_k.value = 20;
  form.elements.query_yield_min_included_at_k.value = 5;
  form.elements.query_yield_min_precision_at_k.value = 0.25;
  form.elements.query_yield_min_precision_lower_bound.value = 0.10;
  form.elements.query_yield_confidence_level.value = 0.95;
  form.elements.additional_exact_query.value = "";
  document.querySelector("#add-scope-query").disabled = true;
  form.elements.interval_minutes.value = 60;
  if (state.registries) applyRegistryToForm(form, state.registries);
  document.querySelector("#scope-submit").textContent = "保存范围";
  updatePlatformControls(form);
  setDefaultWindow();
}

document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.querySelector("#scope-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const scopeId = data.get("scope_id");
  const previous = state.scopes.find((item) => item.scope_id === scopeId);
  const platform = previous?.platform || data.get("platform");
  let tiktokQuery = null;
  if (platform === "tiktok") {
    try {
      tiktokQuery = JSON.parse(data.get("tiktok_query"));
      if (!tiktokQuery || Array.isArray(tiktokQuery) || typeof tiktokQuery !== "object") {
        throw new Error("not an object");
      }
    } catch (_error) {
      toast("TikTok query AST 必须是有效 JSON 对象", true);
      return;
    }
  }
  const payload = {
    platform, name: data.get("name").trim(), object_type: data.get("object_type"), object_label: data.get("object_label").trim(),
    keywords: listValues(data.get("keywords")), languages: listValues(data.get("languages")),
    window_start: platform === "tiktok" ? `${data.get("window_start")}T00:00:00Z` : new Date(data.get("window_start")).toISOString(),
    window_end: platform === "tiktok" ? `${data.get("window_end")}T23:59:59Z` : new Date(data.get("window_end")).toISOString(),
    max_items: Number(data.get("max_items")),
    query_family: data.get("query_family"), phase: data.get("phase"), exact_query: data.get("exact_query").trim(),
    max_videos: Number(data.get("max_videos")),
    max_comment_threads_per_video: Number(data.get("max_comment_threads_per_video")),
    max_replies_per_thread: Number(data.get("max_replies_per_thread")),
    query_yield_evaluation_k: Number(data.get("query_yield_evaluation_k")),
    query_yield_min_included_at_k: Number(data.get("query_yield_min_included_at_k")),
    query_yield_min_precision_at_k: Number(data.get("query_yield_min_precision_at_k")),
    query_yield_min_precision_lower_bound: Number(data.get("query_yield_min_precision_lower_bound")),
    query_yield_confidence_level: Number(data.get("query_yield_confidence_level")),
    ...(platform === "mastodon" ? {
      mastodon_instances: listValues(data.get("mastodon_instances")),
      mastodon_access_method: data.get("mastodon_access_method"),
      mastodon_page_size: Number(data.get("mastodon_page_size")),
      mastodon_max_pages_per_instance: Number(data.get("mastodon_max_pages_per_instance")),
      mastodon_request_delay_seconds: Number(data.get("mastodon_request_delay_seconds")),
    } : {}),
    ...(platform === "reddit" ? {
      reddit_subreddits: listValues(data.get("reddit_subreddits")),
      reddit_access_method: data.get("reddit_access_method"),
      reddit_sort: data.get("reddit_sort"),
      reddit_time_filter: data.get("reddit_time_filter"),
      reddit_page_size: Number(data.get("reddit_page_size")),
      reddit_max_pages_per_subreddit: Number(data.get("reddit_max_pages_per_subreddit")),
      reddit_request_delay_seconds: Number(data.get("reddit_request_delay_seconds")),
    } : {}),
    ...(platform === "tiktok" ? {
      tiktok_query: tiktokQuery,
      tiktok_video_page_size: Number(data.get("tiktok_video_page_size")),
      tiktok_max_video_pages: Number(data.get("tiktok_max_video_pages")),
      tiktok_comment_page_size: Number(data.get("tiktok_comment_page_size")),
      tiktok_max_comment_pages_per_video: Number(data.get("tiktok_max_comment_pages_per_video")),
      tiktok_reply_page_size: Number(data.get("tiktok_reply_page_size")),
      tiktok_max_reply_pages_per_comment: Number(data.get("tiktok_max_reply_pages_per_comment")),
      tiktok_request_delay_seconds: Number(data.get("tiktok_request_delay_seconds")),
    } : {}),
    ...(platform === "x" ? {
      x_page_size: Number(data.get("x_page_size")),
      x_max_pages: Number(data.get("x_max_pages")),
      x_request_delay_seconds: Number(data.get("x_request_delay_seconds")),
      x_local_run_budget_microusd: Number(data.get("x_local_run_budget_microusd")),
    } : {}),
  };
  try {
    const scope = scopeId
      ? await api(`/api/scopes/${encodeURIComponent(scopeId)}`, { method: "PUT", body: JSON.stringify({ ...payload, active: previous?.active ?? true }) })
      : await api("/api/scopes", { method: "POST", body: JSON.stringify(payload) });
    const schedule = state.schedules.find((item) => item.scope_id === scope.scope_id);
    const schedulePayload = {
      interval_minutes: Number(data.get("interval_minutes")),
      enabled: data.get("schedule_enabled") === "on",
    };
    if (schedule) {
      await api(`/api/schedules/${encodeURIComponent(schedule.schedule_id)}`, { method: "PUT", body: JSON.stringify(schedulePayload) });
    } else {
      await api("/api/schedules", { method: "POST", body: JSON.stringify({ scope_id: scope.scope_id, ...schedulePayload }) });
    }
    toast(scopeId ? "研究范围与调度已更新" : "研究范围与调度已登记");
    resetScopeForm(); await refreshScopes();
  } catch (error) { toast(error.message, true); }
});
document.querySelector("#review-form").addEventListener("submit", (event) => { event.preventDefault(); submitReview("human_verified"); });
document.querySelector("#exclude-button").addEventListener("click", () => submitReview("excluded"));
document.querySelector("#screen-include-button").addEventListener("click", () => submitScreening("include"));
document.querySelector("#screen-exclude-button").addEventListener("click", () => submitScreening("exclude"));
document.querySelector("#screen-uncertain-button").addEventListener("click", () => submitScreening("uncertain"));
document.querySelector('[name="confidence"]').addEventListener("input", (event) => { document.querySelector("#confidence-value").textContent = Number(event.target.value).toFixed(2); });
document.querySelector("#refresh-dashboard").addEventListener("click", refreshDashboard);
document.querySelector("#refresh-runs").addEventListener("click", refreshRuns);
document.querySelector("#refresh-quality").addEventListener("click", refreshQuality);
document.querySelector("#refresh-system").addEventListener("click", refreshSystem);
document.querySelector("#scope-reset").addEventListener("click", resetScopeForm);
document.querySelector("#add-scope-query").addEventListener("click", async (event) => {
  const form = document.querySelector("#scope-form");
  const scopeId = form.elements.scope_id.value;
  const exactQuery = form.elements.additional_exact_query.value.trim();
  if (!scopeId || !exactQuery) return toast("请选择既有范围并填写附加查询", true);
  event.currentTarget.disabled = true;
  try {
    await api(`/api/scopes/${encodeURIComponent(scopeId)}/queries`, {
      method: "POST",
      body: JSON.stringify({ query_family: form.elements.query_family.value, phase: form.elements.phase.value, exact_query: exactQuery }),
    });
    form.elements.additional_exact_query.value = "";
    toast("附加不可变 query 已登记");
    await refreshScopes();
  } catch (error) { toast(error.message, true); }
  finally { event.currentTarget.disabled = false; }
});
document.querySelector('#scope-form [name="object_type"]').addEventListener("change", (event) => {
  fillObjectLabels(event.target.form, state.registries);
});
document.querySelectorAll('#scope-form [name="platform"]').forEach((input) => {
  input.addEventListener("change", (event) => updatePlatformControls(event.target.form));
});
document.querySelector('#scope-form [name="phase"]').addEventListener("change", (event) => {
  if (event.target.value !== "calibration") return;
  const form = event.target.form;
  const evaluationK = Number(form.elements.query_yield_evaluation_k.value || 20);
  form.elements.max_videos.value = Math.max(Number(form.elements.max_videos.value), evaluationK);
  form.elements.max_comment_threads_per_video.value = 0;
  form.elements.max_replies_per_thread.value = 0;
});
document.querySelector('#review-form [name="object_type"]').addEventListener("change", (event) => {
  const selected = state.queue.find((record) => record.observation_id === state.selectedObservation);
  if (selected) {
    api(`/api/observations/${encodeURIComponent(selected.observation_id)}/registry`)
      .then((registry) => fillObjectLabels(event.target.form, registry.snapshot))
      .catch((error) => toast(error.message, true));
  }
});
document.querySelector('#quality-form [name="object_type"]').addEventListener("change", (event) => {
  const observation = state.quality?.observations.find((row) => row.observation_id === state.qualityObservationId);
  if (observation) api(`/api/observations/${encodeURIComponent(observation.observation_id)}/registry`).then((registry) => fillObjectLabels(event.target.form, registry.snapshot)).catch((error) => toast(error.message, true));
});
document.querySelector("#quality-form").addEventListener("submit", submitQualityDecision);
document.querySelector("#quality-run-select").addEventListener("change", (event) => { state.qualityRunId = event.target.value; state.qualityObservationId = null; refreshQuality(); });
document.querySelector("#review-run-select").addEventListener("change", (event) => { state.reviewRunId = event.target.value; state.selectedObservation = null; refreshReview(); });
document.querySelector("#evaluate-quality").addEventListener("click", async (event) => {
  if (!state.qualityRunId) return;
  await evaluateQuality(state.qualityRunId, event.currentTarget);
  await refreshQuality();
});
document.querySelector("#evaluate-query-yield").addEventListener("click", async (event) => {
  if (!state.qualityRunId) return;
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const report = await api(`/api/runs/${encodeURIComponent(state.qualityRunId)}/query-yield`, { method: "POST" });
    toast(`Query 产出报告已冻结：${queryYieldStatus(report.status)}`, report.status !== "passed");
    await refreshQuality();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
document.querySelector("#query-promotion-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.qualityRunId) return;
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const queryIds = [...document.querySelectorAll('[name="promotion_query_id"]:checked')].map((input) => input.value);
  if (!queryIds.length) {
    toast("至少选择一条可晋级 query", true);
    return;
  }
  const data = new FormData(form);
  const button = document.querySelector("#promote-query-yield");
  button.disabled = true;
  try {
    const payload = {
      query_ids: queryIds,
      name: String(data.get("name")).trim(),
      window_start: new Date(data.get("window_start")).toISOString(),
      window_end: new Date(data.get("window_end")).toISOString(),
      max_items: Number(data.get("max_items")),
      max_videos: Number(data.get("max_videos")),
      max_comment_threads_per_video: Number(data.get("max_comment_threads_per_video")),
      max_replies_per_thread: Number(data.get("max_replies_per_thread")),
    };
    const result = await api(`/api/runs/${encodeURIComponent(state.qualityRunId)}/query-yield/promote`, { method: "POST", body: JSON.stringify(payload) });
    toast(`已创建确认范围，含 ${result.promoted_queries.length} 条不可变 query`);
    await refreshScopes();
    await refreshQuality();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
document.querySelector("#run-budget-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity() || !state.pendingRun) return;
  const pending = state.pendingRun;
  const budgets = {
    youtube_run_search_call_budget: Number(form.elements.youtube_run_search_call_budget.value),
    youtube_run_shared_unit_budget: Number(form.elements.youtube_run_shared_unit_budget.value),
  };
  document.querySelector("#run-budget-dialog").close();
  state.pendingRun = null;
  await executeStartRun(pending.scopeId, pending.button, budgets);
});
function closeRunBudgetDialog() {
  document.querySelector("#run-budget-dialog").close();
  state.pendingRun = null;
}
document.querySelector("#close-run-budget").addEventListener("click", closeRunBudgetDialog);
document.querySelector("#cancel-run-budget").addEventListener("click", closeRunBudgetDialog);
document.querySelector("#run-budget-dialog").addEventListener("close", () => {
  state.pendingRun = null;
});
document.querySelectorAll("[data-release]").forEach((button) => button.addEventListener("click", () => decideRelease(button.dataset.release === "true")));
document.querySelector("#create-backup").addEventListener("click", (event) => createBackup(event.currentTarget));
document.querySelector("#quota-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const dailyBudget = Number(formData.get("daily_budget"));
  const searchDailyCallBudget = Number(formData.get("search_daily_call_budget"));
  try {
    const quota = await api("/api/youtube/quota", { method: "PUT", body: JSON.stringify({ daily_budget: dailyBudget, search_daily_call_budget: searchDailyCallBudget }) });
    toast(`配额预算已更新：${quota.daily_budget} 单位 / ${quota.search_daily_call_budget} 次搜索`);
    await refreshSystem();
  } catch (error) { toast(error.message, true); }
});
document.querySelectorAll("[data-matrix]").forEach((button) => button.addEventListener("click", () => {
  state.matrixMode = button.dataset.matrix;
  if (state.analysis) renderMatrix(state.analysis);
}));

async function initialize() {
  state.registries = await api("/api/registries");
  resetScopeForm();
  await Promise.all([refreshHealth(), refreshScopes(), refreshDashboard()]);
}

initialize().catch((error) => toast(error.message, true));
setInterval(() => {
  refreshHealth();
  if (document.querySelector("#view-runs").classList.contains("active")) refreshRuns();
  if (document.querySelector("#view-system").classList.contains("active")) refreshSystem();
}, 5000);