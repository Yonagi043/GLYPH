"use strict";

const state = {
  view: "overview",
  overview: null,
  health: null,
  cache: new Map(),
  busy: false,
  inspectorTrigger: null,
  menuTrigger: null,
  confirmationTrigger: null,
  pendingConfirmation: null,
};

const dangerousActions = {
  initialize: {
    title: "确认初始化目录",
    description: "验证四份上游 handoff，并向当前临时 catalog 写入 module、pointer 与稳定 ID 关系。",
    target: "本机临时 catalog 数据库",
    phrase: "INITIALIZE CATALOG",
  },
  "run-fixture": {
    title: "确认运行分析 fixture",
    description: "创建持久 operation、冻结 synthetic snapshot 并写入分析与审计记录。",
    target: "本机临时 catalog 数据库",
    phrase: "RUN ANALYSIS FIXTURE",
  },
  "run-system-fixture": {
    title: "确认运行完整 fixture",
    description: "创建持久 operation，并依次写入 synthetic social export、分析、demo release 与协调备份。",
    target: "本机临时 catalog、social、export 与 backup 目录",
    phrase: "RUN SYSTEM FIXTURE",
  },
  backup: {
    title: "确认协调备份",
    description: "为两个当前临时数据库创建新的只读一致性副本与 checksum manifest。",
    target: "本机临时 catalog 与 social 数据库",
    phrase: "CREATE BACKUP",
  },
  "export-demo": {
    title: "确认导出 demo 审计包",
    description: "创建新的 no-overwrite synthetic demo 目录和 zip，并登记 release candidate。",
    target: (data) => `analysis run ${data.run || "未指定"}`,
    phrase: "EXPORT DEMO",
  },
  "check-formal": {
    title: "确认检查 formal release",
    description: "执行机械门禁并向 catalog 追加不可变 release candidate 与审计事件；不会绕过 blocker。",
    target: (data) => `analysis run ${data.run || "未指定"}`,
    phrase: "CHECK FORMAL RELEASE",
  },
  restore: {
    title: "确认临时恢复演练",
    description: "将在新的本地目录创建 catalog 与 social 恢复副本并执行完整性检查。",
    target: (data) => `协调备份 ${data.backup || "未指定"}`,
    phrase: "RESTORE DRILL",
  },
  "cancel-operation": {
    title: "确认停止 operation",
    description: "请求持久 operation 在下一个安全 checkpoint 停止，并保留可恢复状态。",
    target: (data) => `operation ${data.operation || "未指定"}`,
    phrase: "STOP OPERATION",
  },
  "resume-operation": {
    title: "确认恢复 operation",
    description: "从已验证 checkpoint 创建下一次 attempt，并继续写入持久状态。",
    target: (data) => `operation ${data.operation || "未指定"}`,
    phrase: "RESUME OPERATION",
  },
};

const labels = {
  overview: ["总览", "模块健康、研究阶段与待处理门禁"],
  assets: ["来源与资产", "来源、权利、资产与刺激派生链"],
  vision: ["视觉测量", "特征运行、质量控制与构念边界"],
  experiment: ["跨文化实验", "问卷、分配、评分与真实收集锁"],
  social: ["文化叙事", "通过 v17 validated export 接入的语境证据"],
  han_style: ["汉字书体", "书体本体、字形实例、知识断言与专家门禁"],
  analysis: ["联合分析", "冻结计划、不可变快照、诊断与推断边界"],
  audit: ["审计与发布", "哈希、备份、阻断项与追加式系统事件"],
};

const moduleLabels = {
  assets: "资产",
  vision: "视觉",
  experiment: "实验",
  social: "叙事",
  han_style: "汉字书体",
  workbench: "工作台",
};

const mobileNavigation = window.matchMedia("(max-width: 760px)");

function syncNavigationInert() {
  const rail = document.querySelector("#side-rail");
  rail.inert = mobileNavigation.matches && !rail.classList.contains("open");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortHash(value) {
  const text = String(value ?? "");
  return text.length > 20 ? `${text.slice(0, 12)}…${text.slice(-6)}` : text;
}

function statusClass(value) {
  const text = String(value ?? "").toLowerCase();
  if (["ready", "passed", "completed", "valid", "ok", "demo_ready"].some((word) => text.includes(word))) return "ready";
  if (["blocked", "failed", "absent", "ineligible"].some((word) => text.includes(word))) return "blocked";
  if (["fixture", "pending", "awaiting", "instance_level"].some((word) => text.includes(word))) return "pending";
  return "neutral";
}

function badge(value, fallback = "未记录") {
  const text = value ?? fallback;
  return `<span class="badge ${statusClass(text)}">${escapeHtml(text)}</span>`;
}

function entity(value) {
  if (!value) return "—";
  return `<button type="button" class="entity-button" data-entity="${escapeHtml(value)}">${escapeHtml(value)}</button>`;
}

function tags(values) {
  if (!values?.length) return "—";
  return `<span class="tag-list">${values.map((value) => badge(value)).join("")}</span>`;
}

async function request(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const unsafe = !["GET", "HEAD", "OPTIONS"].includes(method);
  let csrfHeader = {};
  if (unsafe) {
    const sessionResponse = await fetch("/api/session", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const session = await sessionResponse.json().catch(() => ({}));
    if (!sessionResponse.ok || !session.csrf_token) throw new Error("CSRF_TOKEN_UNAVAILABLE");
    csrfHeader = { "X-GLYPH-CSRF": session.csrf_token };
  }
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...csrfHeader,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({ detail: "响应不可解析" }));
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}

function toast(message, isError = false) {
  const region = document.querySelector("#toast-region");
  const item = document.createElement("div");
  item.className = `toast${isError ? " error" : ""}`;
  item.textContent = message;
  region.append(item);
  window.setTimeout(() => item.remove(), 5200);
}

function pageHead(view, actions = "") {
  const [title, subtitle] = labels[view];
  return `<header class="page-head">
    <div><span class="eyebrow">SYNTHETIC / DEMO · ${escapeHtml(view)}</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div>
    <div class="action-row">${actions}</div>
  </header>`;
}

function emptyRow(columns, text = "尚无登记记录") {
  return `<tr><td class="empty-cell" colspan="${columns}">${escapeHtml(text)}</td></tr>`;
}

function readinessCell(key, value, copy) {
  return `<article class="readiness-cell">
    <header><h2>${escapeHtml(key)}</h2><i class="status-mark ${value ? "ready" : "blocked"}" aria-hidden="true"></i></header>
    <strong>${value ? "已达成" : "未达成"}</strong><p>${escapeHtml(copy)}</p>
  </article>`;
}

function moduleRows(modules) {
  if (!modules?.length) return emptyRow(7, "目录未初始化");
  return modules.map((item) => `<tr data-filter-row>
    <td><b>${escapeHtml(moduleLabels[item.module_id] || item.module_id)}</b><br><span class="mono">${escapeHtml(item.module_id)}</span></td>
    <td>${badge(item.health)}</td>
    <td>${badge(item.flow_status)}</td>
    <td>${item.readiness?.engineering_ready ? "通过" : "阻断"}</td>
    <td>${item.readiness?.pilot_ready ? "通过" : "未通过"}</td>
    <td>${item.readiness?.research_validated ? "通过" : "未通过"}</td>
    <td>${tags(item.human_gates)}</td>
  </tr>`).join("");
}

function renderOverview(data) {
  const modules = data.modules || [];
  const runs = data.analysis_runs || [];
  const latest = runs.at(-1);
  const actions = modules.length
    ? `<button class="button primary" data-action="run-system-fixture">运行完整 fixture</button>`
    : `<button class="button primary" data-action="initialize">初始化目录</button>`;
  return `${pageHead("overview", actions)}
    <section class="summary-band" aria-label="独立就绪度">
      ${readinessCell("ENGINEERING_READY", data.readiness?.engineering_ready, "契约、fixture 与工程守卫")}
      ${readinessCell("PILOT_READY", data.readiness?.pilot_ready, "真实试运行与人工门禁")}
      ${readinessCell("RESEARCH_VALIDATED", data.readiness?.research_validated, "真人研究与推断验证")}
    </section>
    <section class="stat-strip" aria-label="系统摘要">
      <div class="stat"><span>登记模块</span><b>${modules.length}</b></div>
      <div class="stat"><span>分析运行</span><b>${runs.length}</b></div>
      <div class="stat"><span>未决人工门禁</span><b>${data.blocked_human_gates?.length || 0}</b></div>
      <div class="stat"><span>Catalog integrity</span><b>${escapeHtml(data.catalog_integrity || "—")}</b></div>
    </section>
    <section class="content-section">
      <div class="section-head"><div><h2>模块完成矩阵</h2><p>工程完成、pilot 就绪与研究验证分列显示</p></div><span class="section-count">${modules.length} MODULES</span></div>
      <div class="table-tools"><input class="search-input" type="search" data-filter placeholder="筛选模块、状态或门禁" aria-label="筛选模块"></div>
      <div class="table-wrap"><table><thead><tr><th>模块</th><th>健康</th><th>流程状态</th><th>工程</th><th>Pilot</th><th>研究验证</th><th>人工门禁</th></tr></thead><tbody>${moduleRows(modules)}</tbody></table></div>
    </section>
    <div class="split-grid">
      <section class="content-section"><div class="section-head"><div><h2>最近分析</h2><p>冻结 snapshot 与结果状态</p></div></div>
        ${latest ? `<dl class="definition-list"><div><dt>analysis_run_id</dt><dd>${entity(latest.analysis_run_id)}</dd></div><div><dt>状态</dt><dd>${badge(latest.status)}</dd></div><div><dt>数据来源</dt><dd>${badge(latest.data_origin)}</dd></div><div><dt>snapshot</dt><dd>${escapeHtml(shortHash(latest.snapshot_sha256))}</dd></div></dl>` : `<p class="empty-cell">尚无分析运行</p>`}
      </section>
      <section class="content-section"><div class="section-head"><div><h2>发布边界</h2><p>Formal release 不可从界面绕过</p></div></div>
        <ul class="boundary-list"><li class="blocker">Synthetic rating 只能进入 demo export</li><li class="blocker">WP3 独立 source stimulus 不足</li><li class="blocker">WP4 仅允许实例级结论</li><li>WP2 保持 context-only，不附着参与者暴露</li></ul>
      </section>
    </div>`;
}

function artifactRows(items) {
  if (!items?.length) return emptyRow(7);
  return items.map((item) => `<tr data-filter-row>
    <td>${entity(item.artifact_id)}</td><td>${escapeHtml(item.logical_type)}</td><td class="mono">${escapeHtml(item.location)}</td>
    <td>${badge(item.data_classification)}</td><td>${escapeHtml(item.schema_version || "—")}</td><td>${escapeHtml(item.record_count ?? "—")}</td><td class="hash" title="${escapeHtml(item.sha256)}">${escapeHtml(shortHash(item.sha256))}</td>
  </tr>`).join("");
}

function relationshipRows(items) {
  if (!items?.length) return emptyRow(5);
  return items.map((item) => `<tr data-filter-row>
    <td>${entity(item.source_id)}<br><span class="mono">${escapeHtml(item.source_module)} / ${escapeHtml(item.source_type)}</span></td>
    <td>${escapeHtml(item.relation)}</td><td>${entity(item.target_id)}<br><span class="mono">${escapeHtml(item.target_module)} / ${escapeHtml(item.target_type)}</span></td>
    <td>${escapeHtml(item.cluster_id || "—")}</td><td>${badge(item.analysis_boundary || "registered")}</td>
  </tr>`).join("");
}

function renderModule(view, data) {
  const module = data.module;
  const health = module?.health || "absent";
  return `${pageHead(view)}
    <section class="stat-strip"><div class="stat"><span>模块健康</span><b>${escapeHtml(health)}</b></div><div class="stat"><span>工件指针</span><b>${data.artifact_count || 0}</b></div><div class="stat"><span>稳定 ID 关系</span><b>${data.relationship_count || 0}</b></div><div class="stat"><span>人工门禁</span><b>${module?.human_gates?.length || 0}</b></div></section>
    <section class="content-section"><div class="section-head"><div><h2>公开契约</h2><p>${escapeHtml(module?.module_version || "未登记")} · ${escapeHtml(module?.handoff_schema_version || "无 handoff")}</p></div>${badge(health)}</div>
      ${module ? `<dl class="definition-list"><div><dt>能力</dt><dd>${escapeHtml(module.capabilities.join(" · "))}</dd></div><div><dt>读取入口</dt><dd>${escapeHtml(module.read_endpoints.join(" · "))}</dd></div><div><dt>命令入口</dt><dd>${escapeHtml(module.command_endpoints.join(" · "))}</dd></div><div><dt>数据分类</dt><dd>${escapeHtml(module.data_classifications.join(" · "))}</dd></div></dl>` : `<p class="empty-cell">模块未登记</p>`}
    </section>
    <section class="content-section"><div class="section-head"><div><h2>工件目录</h2><p>仅显示 pointer、schema、分类和哈希</p></div><span class="section-count">${data.artifact_count || 0} ARTIFACTS</span></div>
      <div class="table-tools"><input class="search-input" type="search" data-filter placeholder="筛选工件" aria-label="筛选工件"></div>
      <div class="table-wrap"><table><thead><tr><th>artifact_id</th><th>类型</th><th>位置</th><th>分类</th><th>Schema</th><th>记录</th><th>SHA-256</th></tr></thead><tbody>${artifactRows(data.artifacts)}</tbody></table></div>
    </section>
    <section class="content-section"><div class="section-head"><div><h2>跨模块关系</h2><p>稳定 ID、cluster 与分析边界</p></div><span class="section-count">${data.relationship_count || 0} LINKS</span></div>
      <div class="table-tools"><input class="search-input" type="search" data-filter placeholder="筛选 ID 或关系" aria-label="筛选关系"></div>
      <div class="table-wrap"><table><thead><tr><th>来源实体</th><th>关系</th><th>目标实体</th><th>Cluster</th><th>边界</th></tr></thead><tbody>${relationshipRows(data.relationships)}</tbody></table></div>
    </section>`;
}

function wpCards(packages) {
  const names = ["WP1", "WP2", "WP3", "WP4"];
  return names.map((name) => {
    const item = packages?.[name] || {};
    const status = item.status || (name === "WP2" ? "context_only" : "not_run");
    const detail = name === "WP2"
      ? `participant exposure: ${item.participant_exposure_attached === true ? "attached" : "not attached"}`
      : name === "WP4"
        ? `category effect: ${item.category_effect_allowed === true ? "allowed" : "blocked"}`
        : name === "WP3"
          ? `visual increment: ${item.visual_increment_eligible === true ? "eligible" : "blocked"}`
          : "participant × stimulus hierarchy";
    return `<article class="wp-item"><header><h3>${name}</h3>${badge(status)}</header><strong>${escapeHtml(status)}</strong><p>${escapeHtml(detail)}</p></article>`;
  }).join("");
}

function effectPlot(effect) {
  if (!effect) return `<p class="empty-cell">暂无效应估计</p>`;
  const estimate = Number(effect.estimate_log_odds || 0);
  const [low, high] = effect.confidence_interval_95 || [0, 0];
  const min = Math.min(-0.5, low - 0.2);
  const max = Math.max(0.5, high + 0.2);
  return `<div role="img" aria-label="native match log odds ${estimate.toFixed(3)}, 95 percent interval ${Number(low).toFixed(3)} to ${Number(high).toFixed(3)}">
    <meter class="effect-meter" min="${min}" max="${max}" value="${estimate}">${estimate.toFixed(4)}</meter>
    <dl class="definition-list"><div><dt>估计值</dt><dd>${estimate.toFixed(4)} log-odds</dd></div><div><dt>95% CI</dt><dd>[${Number(low).toFixed(4)}, ${Number(high).toFixed(4)}]</dd></div><div><dt>用途</dt><dd>engineering recovery only</dd></div></dl>
  </div>`;
}

function renderAnalysis(data) {
  const run = data.runs?.at(-1);
  const plan = data.plans?.at(-1);
  const actions = `<button class="button primary" data-action="run-fixture">运行分析 fixture</button>${run ? `<button class="button" data-action="export-demo" data-run="${escapeHtml(run.analysis_run_id)}">导出 demo 审计包</button>` : ""}`;
  return `${pageHead("analysis", actions)}
    <section class="stat-strip"><div class="stat"><span>冻结计划</span><b>${data.plans?.length || 0}</b></div><div class="stat"><span>不可变运行</span><b>${data.runs?.length || 0}</b></div><div class="stat"><span>模型族</span><b>${escapeHtml(plan?.model?.family || "—")}</b></div><div class="stat"><span>数据来源</span><b>${escapeHtml(run?.data_origin || "—")}</b></div></section>
    <section class="content-section"><div class="section-head"><div><h2>工作包边界</h2><p>推断门槛按计划机械路由</p></div>${run ? badge(run.status) : badge("not_run")}</div><div class="wp-grid">${wpCards(run?.work_packages)}</div></section>
    <div class="split-grid"><section class="content-section"><div class="section-head"><div><h2>计划与快照</h2><p>旧 run 不随上游变化</p></div></div>
      ${run && plan ? `<dl class="definition-list"><div><dt>plan</dt><dd>${escapeHtml(plan.plan_id)} / ${escapeHtml(plan.version)}</dd></div><div><dt>analysis_unit</dt><dd>${escapeHtml(plan.analysis_unit)}</dd></div><div><dt>analysis_run_id</dt><dd>${entity(run.analysis_run_id)}</dd></div><div><dt>snapshot</dt><dd>${escapeHtml(run.snapshot_sha256)}</dd></div><div><dt>状态</dt><dd>${badge(run.status)}</dd></div></dl>` : `<p class="empty-cell">尚无冻结运行</p>`}
      </section><section class="content-section"><div class="section-head"><div><h2>Native match</h2><p>Ordinal fixture 参数恢复</p></div></div>${effectPlot(run?.effect_estimates?.[0])}</section></div>
    <section class="content-section"><div class="section-head"><div><h2>模型诊断</h2><p>收敛、分组 holdout 与研究模型资格</p></div></div>
      ${run?.model_diagnostics ? `<dl class="definition-list"><div><dt>converged</dt><dd>${badge(String(run.model_diagnostics.converged))}</dd></div><div><dt>probability rows</dt><dd>${badge(String(run.model_diagnostics.probability_rows_sum_to_one))}</dd></div><div><dt>research eligible</dt><dd>${badge(String(run.model_diagnostics.research_model_eligible))}</dd></div><div><dt>holdout folds</dt><dd>${escapeHtml(run.model_diagnostics.double_group_holdout?.length || 0)}</dd></div></dl>` : `<p class="empty-cell">尚无模型诊断</p>`}
    </section>
    <section class="content-section"><div class="section-head"><div><h2>已知局限</h2><p>随运行结果固化</p></div></div><ul class="boundary-list">${(run?.limitations || ["尚无运行结果"]).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
}

function releaseRows(items) {
  if (!items?.length) return emptyRow(5);
  return items.slice().reverse().map((item) => `<tr data-filter-row><td>${entity(item.release_candidate_id)}</td><td>${escapeHtml(item.purpose)}</td><td>${badge(item.status)}</td><td>${badge(item.data_origin)}</td><td>${item.formal_blockers?.length || 0}</td></tr>`).join("");
}

function backupRows(items) {
  if (!items?.length) return emptyRow(5);
  return items.map((item) => `<tr data-filter-row><td class="mono">${escapeHtml(item.backup_id)}</td><td>${escapeHtml(item.completed_at)}</td><td>${escapeHtml(item.consistency_model)}</td><td>${badge(item.components?.catalog?.integrity_check)}</td><td>${badge(item.components?.social?.integrity_check)}</td></tr>`).join("");
}

function auditRows(items) {
  if (!items?.length) return emptyRow(4);
  return items.map((item) => `<tr data-filter-row><td class="mono">${escapeHtml(item.occurred_at)}</td><td>${escapeHtml(item.event_type)}</td><td>${escapeHtml(item.object_type)}</td><td>${entity(item.object_id)}</td></tr>`).join("");
}

function operationRows(items) {
  if (!items?.length) return emptyRow(6);
  return items.map((item) => {
    const action = ["queued", "running", "cancel_requested"].includes(item.status)
      ? `<button class="button danger" data-action="cancel-operation" data-operation="${escapeHtml(item.operation_id)}">停止</button>`
      : ["canceled", "failed"].includes(item.status)
        ? `<button class="button" data-action="resume-operation" data-operation="${escapeHtml(item.operation_id)}">恢复</button>`
        : "—";
    return `<tr data-filter-row><td class="mono">${escapeHtml(item.operation_id)}</td><td>${escapeHtml(item.kind)}</td><td>${badge(item.status)}</td><td>${escapeHtml(item.stage)}</td><td>${item.attempts}</td><td>${action}</td></tr>`;
  }).join("");
}

function renderAudit(data) {
  const run = state.overview?.analysis_runs?.at(-1);
  const latestRelease = data.release_candidates?.at(-1);
  const latestBackup = data.backups?.[0];
  const actions = `${run ? `<button class="button danger" data-action="check-formal" data-run="${escapeHtml(run.analysis_run_id)}">检查 formal release</button>` : ""}<button class="button" data-action="backup">协调备份</button>${latestBackup ? `<button class="button" data-action="restore" data-backup="${escapeHtml(latestBackup.backup_id)}">临时恢复演练</button>` : ""}`;
  return `${pageHead("audit", actions)}
    <section class="stat-strip"><div class="stat"><span>发布候选</span><b>${data.release_candidates?.length || 0}</b></div><div class="stat"><span>协调备份</span><b>${data.backups?.length || 0}</b></div><div class="stat"><span>审计事件</span><b>${data.audit_events?.length || 0}</b></div><div class="stat"><span>Formal release</span><b>${escapeHtml(latestRelease?.status || "未检查")}</b></div></section>
    ${latestRelease?.formal_blockers?.length ? `<section class="content-section"><div class="section-head"><div><h2>当前阻断项</h2><p>机器码、范围与人类可读原因</p></div><span class="section-count">${latestRelease.formal_blockers.length} BLOCKERS</span></div><div class="blocker-stack">${latestRelease.formal_blockers.map((item) => `<article class="blocker-row"><b>${escapeHtml(item.code)}</b><p>${escapeHtml(item.scope)} · ${escapeHtml(item.message)}</p></article>`).join("")}</div></section>` : ""}
    <section class="content-section"><div class="section-head"><div><h2>长任务</h2><p>单 worker、固定任务类型与阶段化恢复</p></div><span class="section-count">${data.operations?.length || 0} OPERATIONS</span></div><div class="table-wrap"><table><thead><tr><th>operation_id</th><th>类型</th><th>状态</th><th>阶段</th><th>尝试</th><th>动作</th></tr></thead><tbody>${operationRows(data.operations)}</tbody></table></div></section>
    <section class="content-section"><div class="section-head"><div><h2>发布候选</h2><p>Demo 与 formal 目的分开记录</p></div></div><div class="table-wrap"><table><thead><tr><th>candidate_id</th><th>目的</th><th>状态</th><th>来源</th><th>阻断数</th></tr></thead><tbody>${releaseRows(data.release_candidates)}</tbody></table></div></section>
    <section class="content-section"><div class="section-head"><div><h2>协调备份</h2><p>Catalog 与 social 使用各自 SQLite 一致性机制</p></div></div><div class="table-wrap"><table><thead><tr><th>backup_id</th><th>完成时间</th><th>一致性模型</th><th>Catalog</th><th>Social</th></tr></thead><tbody>${backupRows(data.backups)}</tbody></table></div></section>
    <section class="content-section"><div class="section-head"><div><h2>追加式审计</h2><p>最近 200 条 catalog 事件</p></div></div><div class="table-tools"><input class="search-input" type="search" data-filter placeholder="筛选事件或对象" aria-label="筛选审计事件"></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>事件</th><th>对象类型</th><th>对象 ID</th></tr></thead><tbody>${auditRows(data.audit_events)}</tbody></table></div></section>`;
}

function bindFilters() {
  document.querySelectorAll("[data-filter]").forEach((input) => {
    input.addEventListener("input", () => {
      const table = input.closest(".content-section")?.querySelector("tbody");
      const query = input.value.trim().toLocaleLowerCase("zh-Hans");
      table?.querySelectorAll("[data-filter-row]").forEach((row) => {
        row.hidden = Boolean(query) && !row.textContent.toLocaleLowerCase("zh-Hans").includes(query);
      });
    });
  });
}

async function loadBase(force = false) {
  if (!state.overview || force) state.overview = await request("/api/overview");
  if (!state.health || force) state.health = await request("/api/health");
  document.querySelector("#rail-health").textContent = state.health.status === "ready" ? "系统可用" : "系统阻断";
}

async function navigate(view, force = false) {
  if (!labels[view]) view = "overview";
  state.view = view;
  document.querySelector("#view-crumb").textContent = labels[view][0];
  document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  closeMenu();
  const root = document.querySelector("#app");
  root.setAttribute("aria-busy", "true");
  root.innerHTML = `<section class="loading-state"><span class="loading-rule"></span><p>正在读取本机目录...</p></section>`;
  try {
    await loadBase(force);
    let content;
    if (view === "overview") {
      content = renderOverview(state.overview);
    } else {
      const endpoint = view === "analysis" ? "/api/analysis" : view === "audit" ? "/api/audit" : `/api/views/${view}`;
      let data = !force ? state.cache.get(endpoint) : null;
      if (!data) {
        data = await request(endpoint);
        if (view === "audit") data.operations = (await request("/api/operations")).operations;
        state.cache.set(endpoint, data);
      }
      content = view === "analysis" ? renderAnalysis(data) : view === "audit" ? renderAudit(data) : renderModule(view, data);
    }
    root.innerHTML = `<div class="page-enter">${content}</div>`;
    bindFilters();
  } catch (error) {
    root.innerHTML = `<section class="error-state"><span class="eyebrow">REQUEST BLOCKED</span><h1>视图无法加载</h1><code>${escapeHtml(error.message)}</code><p><button class="button" data-action="refresh">重新检查</button></p></section>`;
  } finally {
    root.setAttribute("aria-busy", "false");
  }
}

function invalidate() {
  state.overview = null;
  state.health = null;
  state.cache.clear();
}

async function perform(action, data = {}) {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("[data-action]").forEach((button) => { button.disabled = true; });
  const confirmation = data.confirmationPhrase
    ? { confirmation_phrase: data.confirmationPhrase }
    : {};
  const routes = {
    initialize: ["/api/actions/initialize", confirmation],
    "run-fixture": ["/api/operations/analysis-fixture", confirmation],
    "run-system-fixture": ["/api/operations/system-fixture", confirmation],
    "export-demo": ["/api/actions/export-demo", { analysis_run_id: data.run, ...confirmation }],
    "check-formal": ["/api/actions/check-formal-release", { analysis_run_id: data.run, ...confirmation }],
    backup: ["/api/actions/backup", confirmation],
    restore: ["/api/actions/restore-drill", { backup_id: data.backup, confirmation_phrase: data.confirmationPhrase }],
    "cancel-operation": [`/api/operations/${data.operation}/cancel`, confirmation],
    "resume-operation": [`/api/operations/${data.operation}/resume`, confirmation],
  };
  try {
    const [path, body] = routes[action];
    const result = await request(path, { method: "POST", body: JSON.stringify(body) });
    invalidate();
    if (action === "check-formal") toast(`Formal release：${result.status}，${result.formal_blockers.length} 项阻断`);
    else if (action === "restore") toast(`恢复演练通过：${result.drill_id}`);
    else if (action === "backup") toast(`协调备份完成：${result.backup_id}`);
    else if (["run-system-fixture", "run-fixture"].includes(action)) toast(`任务已入队：${result.operation_id}`);
    else if (action === "cancel-operation") toast(`停止请求：${result.status}`);
    else if (action === "resume-operation") toast(`恢复请求：${result.status}`);
    else toast("操作已完成并写入审计");
    const auditActions = ["check-formal", "backup", "restore", "run-system-fixture", "run-fixture", "cancel-operation", "resume-operation"];
    await navigate(auditActions.includes(action) ? "audit" : state.view, true);
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.busy = false;
    document.querySelectorAll("[data-action]").forEach((button) => { button.disabled = false; });
  }
}

function focusableElements(container) {
  return [...container.querySelectorAll("button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])")]
    .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
}

function trapFocus(event, container) {
  if (event.key !== "Tab") return;
  const elements = focusableElements(container);
  if (!elements.length) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = elements[0];
  const last = elements.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (!container.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  }
}

function restoreFocus(element) {
  if (element?.isConnected && !element.closest("[inert]")) element.focus();
}

function openInspector(trigger) {
  closeMenu(false);
  state.inspectorTrigger = trigger || document.activeElement;
  const inspector = document.querySelector("#inspector");
  document.querySelector(".app-shell").inert = true;
  inspector.inert = false;
  inspector.classList.add("open");
  inspector.setAttribute("aria-hidden", "false");
  document.querySelector("#scrim").classList.add("visible");
  window.requestAnimationFrame(() => inspector.querySelector("[data-action='close-inspector']")?.focus());
}

async function showEvidence(entityId, trigger) {
  const inspector = document.querySelector("#inspector");
  const content = document.querySelector("#inspector-content");
  document.querySelector("#inspector-title").textContent = entityId;
  content.innerHTML = `<section class="loading-state"><span class="loading-rule"></span><p>正在解析关系...</p></section>`;
  openInspector(trigger);
  try {
    const data = await request(`/api/evidence/${encodeURIComponent(entityId)}`);
    content.innerHTML = `<section class="inspector-section"><h3>实体</h3><dl class="definition-list"><div><dt>ID</dt><dd>${escapeHtml(data.entity_id)}</dd></div><div><dt>关系数</dt><dd>${data.relationships.length}</dd></div><div><dt>证据工件</dt><dd>${data.evidence_artifacts.length}</dd></div></dl></section>
      <section class="inspector-section"><h3>稳定 ID 关系</h3>${data.relationships.length ? data.relationships.map((item) => `<div class="blocker-row"><b>${escapeHtml(item.relation)}</b><p>${escapeHtml(item.source_id)} → ${escapeHtml(item.target_id)}</p></div>`).join("") : `<p class="empty-cell">未登记相邻关系</p>`}</section>
      <section class="inspector-section"><h3>证据 pointer</h3><pre class="json-block">${escapeHtml(JSON.stringify(data.evidence_artifacts, null, 2))}</pre></section>`;
  } catch (error) {
    content.innerHTML = `<p class="empty-cell">${escapeHtml(error.message)}</p>`;
  }
}

async function showHealth(trigger) {
  try {
    state.health = await request("/api/health");
    const health = state.health;
    const configured = Object.entries(health.credentials_configured).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${badge(value ? "configured" : "not configured")}</dd></div>`).join("");
    document.querySelector("#inspector-title").textContent = "本机系统健康";
    document.querySelector("#inspector-content").innerHTML = `<section class="inspector-section"><h3>数据库</h3><dl class="definition-list"><div><dt>Catalog</dt><dd>${badge(health.catalog.integrity_check)}</dd></div><div><dt>Social</dt><dd>${badge(health.social.health)}</dd></div><div><dt>Scheduler</dt><dd>${badge(health.scheduler_started ? "started" : "not started")}</dd></div><div><dt>失败任务</dt><dd>${health.failed_task_count}</dd></div></dl></section><section class="inspector-section"><h3>平台凭据状态</h3><dl class="definition-list">${configured}</dl></section><section class="inspector-section"><h3>磁盘</h3><dl class="definition-list"><div><dt>可用</dt><dd>${(health.disk.free_bytes / 1073741824).toFixed(1)} GiB</dd></div><div><dt>总量</dt><dd>${(health.disk.total_bytes / 1073741824).toFixed(1)} GiB</dd></div></dl></section>`;
    openInspector(trigger);
  } catch (error) { toast(error.message, true); }
}

function closeInspector(restore = true) {
  const inspector = document.querySelector("#inspector");
  const wasOpen = inspector.classList.contains("open");
  inspector.classList.remove("open");
  inspector.setAttribute("aria-hidden", "true");
  inspector.inert = true;
  document.querySelector(".app-shell").inert = false;
  if (!document.querySelector("#side-rail").classList.contains("open")) document.querySelector("#scrim").classList.remove("visible");
  if (wasOpen && restore) restoreFocus(state.inspectorTrigger);
  state.inspectorTrigger = null;
}

function closeMenu(restore = true) {
  const rail = document.querySelector("#side-rail");
  const wasOpen = rail.classList.contains("open");
  rail.classList.remove("open");
  rail.removeAttribute("role");
  rail.removeAttribute("aria-modal");
  syncNavigationInert();
  document.querySelector("#workspace").inert = false;
  document.querySelector("#menu-button").setAttribute("aria-expanded", "false");
  if (!document.querySelector("#inspector").classList.contains("open")) document.querySelector("#scrim").classList.remove("visible");
  if (wasOpen && restore) restoreFocus(state.menuTrigger);
  state.menuTrigger = null;
}

function openConfirmation(action, data, trigger) {
  const config = dangerousActions[action];
  if (!config) return perform(action, data);
  closeInspector(false);
  closeMenu(false);
  state.confirmationTrigger = trigger || document.activeElement;
  state.pendingConfirmation = { action, data: { ...data }, phrase: config.phrase };
  document.querySelector("#confirmation-title").textContent = config.title;
  document.querySelector("#confirmation-description").textContent = config.description;
  document.querySelector("#confirmation-target").textContent = typeof config.target === "function"
    ? config.target(data)
    : config.target;
  document.querySelector("#confirmation-phrase").textContent = config.phrase;
  const input = document.querySelector("#confirmation-input");
  input.value = "";
  document.querySelector("#confirmation-error").textContent = "";
  document.querySelector("#confirmation-submit").disabled = true;
  document.querySelector(".app-shell").inert = true;
  const dialog = document.querySelector("#confirmation-dialog");
  dialog.showModal();
  window.requestAnimationFrame(() => input.focus());
}

function closeConfirmation() {
  const dialog = document.querySelector("#confirmation-dialog");
  if (dialog.open) dialog.close();
}

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    window.location.hash = viewButton.dataset.view;
    return;
  }
  const entityButton = event.target.closest("[data-entity]");
  if (entityButton) { showEvidence(entityButton.dataset.entity, entityButton); return; }
  const actionButton = event.target.closest("[data-action]");
  if (!actionButton) return;
  const action = actionButton.dataset.action;
  if (action === "refresh") { invalidate(); navigate(state.view, true); }
  else if (action === "close-inspector") closeInspector();
  else if (action === "close-overlays") { closeInspector(); closeMenu(); }
  else if (action === "show-health") showHealth(actionButton);
  else if (dangerousActions[action]) openConfirmation(action, actionButton.dataset, actionButton);
  else perform(action, actionButton.dataset);
});

document.querySelector("#menu-button").addEventListener("click", () => {
  const rail = document.querySelector("#side-rail");
  const open = rail.classList.toggle("open");
  state.menuTrigger = open ? document.querySelector("#menu-button") : null;
  document.querySelector("#menu-button").setAttribute("aria-expanded", String(open));
  document.querySelector("#scrim").classList.toggle("visible", open);
  document.querySelector("#workspace").inert = open;
  if (open) {
    rail.inert = false;
    rail.setAttribute("role", "dialog");
    rail.setAttribute("aria-modal", "true");
    window.requestAnimationFrame(() => rail.querySelector("[data-view]")?.focus());
  }
});

mobileNavigation.addEventListener("change", syncNavigationInert);

document.addEventListener("keydown", (event) => {
  const confirmation = document.querySelector("#confirmation-dialog");
  if (confirmation.open) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeConfirmation();
    } else {
      trapFocus(event, confirmation);
    }
    return;
  }
  const inspector = document.querySelector("#inspector");
  if (inspector.classList.contains("open")) {
    if (event.key === "Escape") { event.preventDefault(); closeInspector(); }
    else trapFocus(event, inspector);
    return;
  }
  const rail = document.querySelector("#side-rail");
  if (rail.classList.contains("open")) {
    if (event.key === "Escape") { event.preventDefault(); closeMenu(); }
    else trapFocus(event, rail);
  }
});

document.querySelector("#confirmation-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeConfirmation();
});

document.querySelector("#confirmation-dialog").addEventListener("close", () => {
  document.querySelector(".app-shell").inert = false;
  const trigger = state.confirmationTrigger;
  state.confirmationTrigger = null;
  state.pendingConfirmation = null;
  restoreFocus(trigger);
});

document.querySelector("#confirmation-input").addEventListener("input", (event) => {
  const matches = event.target.value === state.pendingConfirmation?.phrase;
  document.querySelector("#confirmation-submit").disabled = !matches;
  document.querySelector("#confirmation-error").textContent = event.target.value && !matches ? "确认短语不匹配" : "";
});

document.querySelector("#confirmation-cancel").addEventListener("click", closeConfirmation);

document.querySelector("#confirmation-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const pending = state.pendingConfirmation;
  const phrase = document.querySelector("#confirmation-input").value;
  if (!pending || phrase !== pending.phrase) return;
  const requestData = { ...pending.data, confirmationPhrase: phrase };
  const action = pending.action;
  closeConfirmation();
  perform(action, requestData);
});

window.addEventListener("hashchange", () => navigate(window.location.hash.slice(1) || "overview"));
navigate(window.location.hash.slice(1) || "overview");