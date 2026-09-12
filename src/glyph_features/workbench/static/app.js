"use strict";

const state = {
  view: "overview",
  defaultView: "overview",
  overview: null,
  health: null,
  cache: new Map(),
  busy: false,
  inspectorTrigger: null,
  menuTrigger: null,
  confirmationTrigger: null,
  pendingConfirmation: null,
  selectedMaterials: new Set(),
  draftConfig: null,
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
  research: ["研究运行", "synthetic_persona"],
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

function materialImage(item, representation, className = "material-thumb") {
  const record = item.representations[representation];
  if (!record?.exists || !/\.(png|jpg|jpeg|webp|gif)$/i.test(record.path)) return "";
  return `<img class="${className}" loading="lazy" src="/api/materials/${encodeURIComponent(item.material_id)}/image/${representation}" alt="${escapeHtml(representation === "original" ? "原图" : "已有标准化图")}">`;
}

function renderMaterials(data) {
  const summary = data.summary;
  return `<header class="page-head"><div><span class="eyebrow">GLYPH · EXISTING MATERIALS</span><h1>来源与资产</h1></div><div class="action-row"><span id="selection-count">已选 ${state.selectedMaterials.size}</span><button class="button primary" data-view="research">配置研究</button></div></header>
    <section class="stat-strip"><div class="stat"><span>商业原图</span><b>${summary.kinds.ecological_award_image}</b></div><div class="stat"><span>字体文件（含额外库存）</span><b>${summary.kinds.font_file}</b></div><div class="stat"><span>现成样张</span><b>${summary.kinds.existing_font_sample}</b></div><div class="stat"><span>未匹配旧变换</span><b>${summary.unmatched_transforms.length}</b></div></section>
    <section class="content-section"><div class="table-tools"><input class="search-input" type="search" data-filter placeholder="检索作品、奖项、年份、字体或 ID" aria-label="检索已有材料">
      <select id="material-kind" aria-label="材料类型">
        <option value="">全部材料</option>
        <option value="ecological_award_image">商业图像</option>
        <option value="existing_font_sample">已有字体样张</option>
        <option value="font_file">字体文件</option>
      </select></div>
    <div class="table-wrap"><table><thead><tr><th>选择</th><th>图像</th><th>材料与来源</th><th>类别</th><th>用途状态</th></tr></thead><tbody>${data.items.map((item) => {
      const candidate = item.candidate || {};
      const title = item.source?.title || item.representations.original.path.split("/").at(-1);
      return `<tr data-filter-row data-material-kind="${escapeHtml(item.kind)}"><td><input type="checkbox" data-select-material="${escapeHtml(item.material_id)}" aria-label="选择 ${escapeHtml(title)}" ${state.selectedMaterials.has(item.material_id) ? "checked" : ""} ${item.kind === "font_file" ? 'disabled title="字体文件不是图像，请选择对应样张"' : ""}></td><td>${materialImage(item, "standardized")}</td><td><button class="entity-button" data-material="${escapeHtml(item.material_id)}">${escapeHtml(title)}</button><br><span class="mono">${escapeHtml(item.material_id)}</span><br>${escapeHtml(candidate.award_context?.award || "")} ${escapeHtml(candidate.award_context?.year || "")}</td><td>${escapeHtml(item.kind)}</td><td>${badge(item.use_status.model_input)}<br>${escapeHtml(item.use_status.study_eligibility || candidate.rights_tier || "未审核")}</td></tr>`;
    }).join("")}</tbody></table></div></section>`;
}

async function showMaterial(materialId, trigger) {
  document.querySelector("#inspector-title").textContent = "材料详情";
  const content = document.querySelector("#inspector-content");
  content.textContent = "读取中...";
  openInspector(trigger);
  try {
    const item = await request(`/api/materials/${encodeURIComponent(materialId)}`);
    content.innerHTML = `<div class="material-pair"><figure>${materialImage(item, "original", "material-preview")}<figcaption>原图 / 原样张</figcaption></figure><figure>${materialImage(item, "standardized", "material-preview")}<figcaption>已有标准化图</figcaption></figure></div>
      <section class="inspector-section"><h3>来源与用途</h3><dl class="definition-list"><div><dt>材料 ID</dt><dd>${escapeHtml(item.material_id)}</dd></div><div><dt>作品 ID</dt><dd>${escapeHtml(item.work_id || "未匹配")}</dd></div><div><dt>来源 URL</dt><dd>${escapeHtml(item.source?.url || "渲染样张")}</dd></div></dl><pre class="json-block">${escapeHtml(JSON.stringify(item.use_status, null, 2))}</pre></section>
      <section class="inspector-section"><h3>原始记录与对应证据</h3><pre class="json-block">${escapeHtml(JSON.stringify(item, null, 2))}</pre></section>`;
    if (item.kind === "ecological_award_image") content.insertAdjacentHTML("afterbegin", `<section class="inspector-section"><h3>重复与作品关联</h3><p>同图哈希：${item.same_image_ids?.length || 0} · 同作品其他条目：${item.same_work_ids?.length || 0}</p>${(item.same_work_ids || []).map((otherId) => `<button class="entity-button" data-material="${escapeHtml(otherId)}">${escapeHtml(otherId)}</button>`).join("<br>")}</section>`);
  } catch (error) { content.textContent = error.message; }
}

function renderTextRegionControls(materialId) {
  return `<label>颜色<select name="color_mode"><option value="native">原色</option><option value="grayscale">灰度</option></select></label><label>输入最长边（像素）<input name="max_edge" type="number" min="128" max="4096" step="1" value="1280"></label><label>文字前景<select name="foreground"><option value="unconfirmed">未确认：构图</option><option value="dark">已确认：深色文字</option><option value="light">已确认：浅色文字</option></select></label><label>文字区域确认依据<textarea name="foreground_note" maxlength="2000"></textarea></label><button class="button" type="button" data-preview-selection="${escapeHtml(materialId)}">预览输入 / 掩码</button><div data-selection-preview></div>`;
}

function renderResearch(data, materials) {
  const selected = materials.items.filter((item) => state.selectedMaterials.has(item.material_id));
  data = {...data, runs: [...data.runs].reverse()};
  return `<header class="page-head"><div><span class="eyebrow">GLYPH · SYNTHETIC PERSONA</span><h1>研究运行</h1></div><div class="action-row"><button class="button" data-new-study>新建空白研究</button><button class="button" data-view="assets">选择材料</button></div></header>
    <section class="content-section"><details><summary>同内容字体对照</summary><form id="font-sample-form" class="study-form"><label>已有字体<select name="font_ids" multiple required size="6">${materials.items.filter((item) => item.kind === "font_file").map((item) => `<option value="${escapeHtml(item.material_id)}">${escapeHtml(item.representations.original.path.split("/").at(-1))}</option>`).join("")}</select></label><label>文字内容<textarea name="texts" required></textarea></label><div class="study-options"><label>名义字重<input name="weight" type="number" min="100" max="900" step="1" value="400" required></label><label>字号（像素）<input name="font_size" type="number" min="16" max="256" value="96" required></label><label>画布宽<input name="width" type="number" min="256" max="2048" value="1280" required></label><label>画布高<input name="height" type="number" min="128" max="1024" value="320" required></label></div><button class="button" type="submit">生成并选择样张</button></form></details></section>
    <section class="content-section"><div class="section-head"><h2>已保存运行</h2><span>${data.runs.length}</span></div><div class="table-wrap"><table><thead><tr><th>研究</th><th>状态</th><th>材料</th><th>来源</th><th>操作</th></tr></thead><tbody>${data.runs.map((run) => `<tr><td><button class="entity-button" data-study="${escapeHtml(run.run_id)}">${escapeHtml(run.config.name)}</button><br><span class="mono">${escapeHtml(run.run_id)}</span></td><td>${badge(run.status)}</td><td>${run.snapshot.materials.length}</td><td>synthetic_persona</td><td><button class="button" data-study-measure="${escapeHtml(run.run_id)}">测量</button></td></tr>`).join("") || emptyRow(5)}</tbody></table></div></section>
    <section class="content-section"><div class="section-head"><h2>新研究配置</h2><span>美观 · 探索性</span></div><form id="study-form" class="study-form">
      <label>研究名称<input name="name" required minlength="2" maxlength="160"></label>
      <label>表示比较的参考运行<select name="reference_run_id"><option value="">无参考运行</option>${data.runs.map((run) => `<option value="${escapeHtml(run.run_id)}">${escapeHtml(run.config.name)}</option>`).join("")}</select></label>
      <label>研究问题<textarea name="question" required minlength="5">在当前材料与提示条件下，哪些文字视觉实例更美观，差异是否随身份条件改变？</textarea></label>
      <label>候选解释<textarea name="explanations" required>视觉形式\n熟悉与识读的身份提示\n习得文化联想\n具体设计与商业语境</textarea></label>
      <label>比较依据<textarea name="design_rationale" maxlength="5000"></textarea></label>
      <label>各解释的可反驳预期<textarea name="predictions"></textarea></label>
      <input name="parent_assessment_id" type="hidden">
      <fieldset><legend>身份条件</legend>${["baseline", "zh", "en", "ja", "ko"].map((role) => `<label class="inline-choice"><input type="checkbox" name="roles" value="${role}" ${["baseline", "zh"].includes(role) ? "checked" : ""} ${role === "baseline" ? "disabled" : ""}>${escapeHtml({baseline:"无身份基线",zh:"中文背景",en:"英语背景",ja:"日语背景",ko:"韩语背景"}[role])}</label>`).join("")}</fieldset>
      <div class="study-options"><label>问卷语言<select name="questionnaire_language"><option value="en">English</option><option value="zh-Hans">简体中文</option></select></label><label>身份措辞<select name="wording"><option value="background">背景描述</option><option value="profile">档案描述</option></select></label><label>同条件重复<input name="repetitions" type="number" value="1" min="1" step="1" required></label></div>
      <label>宿主执行 agent<select name="executor_agent"><option value="Explore">Explore（只读）</option><option value="default">当前默认 agent</option></select></label>
      <label>每份问卷图片数<input name="task_size" type="number" min="1" step="1" value="4"></label>
      <label>呈现设计<select name="presentation_mode"><option value="legacy">固定分组正反序</option><option value="triplet_pairs">三字体六排列与两焦点字体</option><option value="measurement_bridge">单图四条件测量桥接</option><option value="explicit">沿用冻结的显式任务表</option></select></label>
      <label>题项模式<select name="questionnaire_mode"><option value="q2">q2 美观、清晰度</option><option value="aesthetic_only">q3 仅美观</option><option value="premium_only">q3 仅高端定位</option><option value="aesthetic_premium">q3 美观先、高端后</option><option value="premium_aesthetic">q3 高端先、美观后</option><option value="aesthetic_pair">q4 成对美观、粗细核对</option><option value="aesthetic_pair_only">q5 仅成对美观</option></select></label>
      <fieldset><legend>单图桥接条件</legend>${[["aesthetic_only", "仅美观"], ["premium_only", "仅高端定位"], ["aesthetic_premium", "美观先、高端后"], ["premium_aesthetic", "高端先、美观后"]].map(([value, label]) => `<label class="inline-choice"><input type="checkbox" name="bridge_modes" value="${value}" checked>${label}</label>`).join("")}</fieldset>
      <label>焦点字体<select name="focal_font_ids" multiple size="4">${materials.items.filter((item) => item.kind === "font_file").map((item) => `<option value="${escapeHtml(item.material_id)}">${escapeHtml(item.representations.original.path.split("/").at(-1))}</option>`).join("")}</select></label>
      <label>分配种子<input name="schedule_seed" type="number" value="20260911" step="1"></label>
      <fieldset><legend>呈现顺序</legend><label class="inline-choice"><input type="checkbox" name="orders" value="forward" checked>正序</label><label class="inline-choice"><input type="checkbox" name="orders" value="reverse" checked>反序</label></fieldset>
      <div class="table-wrap"><table><thead><tr><th>所选材料</th><th>表示</th><th>选择理由</th></tr></thead><tbody>${selected.map((item) => `<tr data-study-selection="${escapeHtml(item.material_id)}"><td>${escapeHtml(item.source?.title || item.representations.original.path.split("/").at(-1))}<br>${badge(item.use_status.model_input)}</td><td><select name="representation">${item.representations.standardized ? '<option value="standardized">已有标准化图</option>' : ""}<option value="original">原图 / 原样张</option></select><details><summary>矩形区域（可选，像素）</summary>${["left", "top", "right", "bottom"].map((edge, index) => `<label>${["左", "上", "右", "下"][index]}<input name="crop_${edge}" type="number" min="0" step="1"></label>`).join("")}</details>${renderTextRegionControls(item.material_id)}</td><td><input name="reason" required minlength="3" value="现有实例比较"></td></tr>`).join("") || emptyRow(3, "尚未选择材料")}</tbody></table></div>
      <label>选择范围与未用原因<textarea name="selection_scope" required minlength="5">本次按内容、字体或商业实例进行有针对性比较；其余材料未纳入本次配置，不代表质量不合格。</textarea></label>
      <label>继续 / 停止规则<textarea name="stopping_rule" required minlength="5">完成匹配基线、身份与顺序条件，检查缺失和重复波动；不为预期排序或显著性重复抽取。</textarea></label>
      <button class="button primary" type="submit" ${selected.length ? "" : "disabled"}>保存研究配置</button>
    </form></section>`;
}

function researchNumber(value) {
  return Number.isFinite(value) ? String(Number(value.toFixed(4))) : "NA";
}

function differenceRange(items) {
  const values = items.map((item) => item.difference).filter(Number.isFinite);
  return values.length ? `${Math.min(...values)} 至 ${Math.max(...values)}（${values.length} 配对）` : "无有效配对";
}

function renderResearchJudgments(run, results) {
  const judgments = {supported: "支持", not_supported: "不支持", unresolved: "无法区分"};
  const workSummary = results.representation_comparison?.work_summary;
  const titleFor = (materialId) => results.materials.find((item) => item.material_id === materialId)?.title || materialId;
  const latest = results.research_assessments?.at(-1);
  return `<section class="inspector-section"><h3>当前研究结论</h3><p>${escapeHtml(latest?.conclusion || "尚未保存研究判断；下列为实际结果及冻结比较。")}</p><details><summary>冻结问题、比较依据与预期</summary><p>${escapeHtml(run.config.question)}</p><p>${escapeHtml(run.config.design_rationale || "未登记比较依据")}</p>${(run.config.predictions || []).map((prediction) => `<p>${escapeHtml(prediction)}</p>`).join("")}${run.config.parent_assessment_id ? `<p class="mono">沿用判断 ${escapeHtml(run.config.parent_assessment_id)}</p>` : ""}</details>
    ${workSummary?.works.length ? `<h4>作品级表示差值</h4><p>本运行减参考。${workSummary.observed_work_count} 个作品等权均差 ${researchNumber(workSummary.equal_work_mean_difference)}；负向 ${workSummary.negative_works}、持平 ${workSummary.tied_works}、正向 ${workSummary.positive_works}。</p><div class="table-wrap"><table><thead><tr><th>作品</th><th>均差 / 范围</th><th>负 / 零 / 正条件</th></tr></thead><tbody>${workSummary.works.map((work) => `<tr><td>${work.material_ids.map((materialId) => escapeHtml(titleFor(materialId))).join(" / ")}</td><td>${researchNumber(work.mean_difference)} / ${work.range_difference.map(researchNumber).join(" 至 ")}</td><td>${work.negative_conditions} / ${work.tied_conditions} / ${work.positive_conditions}</td></tr>`).join("")}</tbody></table></div><p>有序评分的描述性均差；同一作品的多次调用不作独立样本。逐一去掉一个作品的均差范围：${differenceRange((workSummary.leave_one_work_out || []).map((item) => ({difference: item.mean_difference})))}。这不是置信区间。</p>` : ""}
    ${(results.font_comparison_summaries || []).length ? `<h4>同内容字体比较</h4><p>比较项减参考项。美观为主要结果，清晰度另列；同一字体的文本和调用不是独立字体家族。</p><div class="table-wrap"><table><thead><tr><th>内容 / 条件</th><th>比较减参考</th><th>美观逐对差值</th><th>正序 / 反序均差</th><th>清晰度均差</th></tr></thead><tbody>${results.font_comparison_summaries.map((summary) => `<tr><td>${escapeHtml(summary.content)}<br>${escapeHtml(summary.role)} · ${escapeHtml(summary.model_display_name)}</td><td>${escapeHtml(summary.comparison_title)}<br>减 ${escapeHtml(summary.reference_title)}</td><td>${summary.aesthetic_differences.map(researchNumber).join(", ")}</td><td>${researchNumber(summary.order_mean_differences.forward)} / ${researchNumber(summary.order_mean_differences.reverse)}</td><td>${researchNumber(summary.mean_clarity_difference)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${(results.research_assessments || []).map((assessment) => `<article class="research-source"><h4>已保存判断 · ${escapeHtml(assessment.assessment_id)}</h4><p>研究者 / agent 解释，非独立因果证据</p><p>${escapeHtml(assessment.conclusion)}</p>${assessment.explanation_updates.map((update) => `<h4>${escapeHtml(judgments[update.judgment])}：${escapeHtml(update.explanation)}</h4><p>${escapeHtml(update.evidence)}</p><p>${update.material_ids.map((materialId) => escapeHtml(titleFor(materialId))).join(" / ")}</p>`).join("")}<h4>尚未区分</h4>${assessment.remaining_confounds.map((confound) => `<p>${escapeHtml(confound)}</p>`).join("")}<h4>下一问题</h4><p>${escapeHtml(assessment.next_question)}</p><p>${escapeHtml(assessment.next_comparison)}</p><p class="mono">依据结果 ${escapeHtml(assessment.basis_result_sha256)}</p><button class="button" data-continue-assessment="${escapeHtml(assessment.assessment_id)}">据此继续研究</button></article>`).join("") || "<p>尚未保存研究判断。</p>"}
    <details><summary>记录新的研究判断</summary><form class="study-form" data-assessment-form="${escapeHtml(run.run_id)}" data-basis-result="${escapeHtml(results.result_sha256)}"><label>当前结论<textarea name="conclusion" required minlength="10" maxlength="6000"></textarea></label>${run.config.explanations.map((explanation, index) => `<fieldset data-explanation-index="${index}"><legend>${escapeHtml(explanation)}</legend><input type="hidden" name="explanation" value="${escapeHtml(explanation)}"><label>判断<select name="judgment">${Object.entries(judgments).map(([value, title]) => `<option value="${value}" ${value === "unresolved" ? "selected" : ""}>${title}</option>`).join("")}</select></label><label>具体比较与证据<textarea name="evidence" minlength="5" maxlength="5000" required></textarea></label>${run.snapshot.materials.map((record) => `<label class="inline-choice"><input type="checkbox" name="material_ids" value="${escapeHtml(record.selection.material_id)}" checked>${escapeHtml(titleFor(record.selection.material_id))}</label>`).join("")}</fieldset>`).join("")}<label>未决混杂<textarea name="remaining_confounds" required></textarea></label><label>下一问题<textarea name="next_question" required minlength="5"></textarea></label><label>下一比较及选择依据<textarea name="next_comparison" required minlength="10"></textarea></label><label>研究决定<select name="decision"><option value="new_comparison">改变比较条件</option><option value="independent_materials">增加独立材料</option><option value="repeat_check">检验重复波动</option><option value="stop_path">停止当前路径</option></select></label><button class="button primary" type="submit">保存判断</button></form></details></section>`;
}

function renderStudyOverview(run, results) {
  const comparison = results.representation_comparison || {pairs: []};
  const workIds = run.snapshot.materials.map((record) => {
    if (record.material.work_id) return record.material.work_id;
    try { return JSON.parse(record.material.source.notes)?.work_id || null; }
    catch { return null; }
  });
  const validCalls = new Set(results.rows.map((row) => row.task_id)).size;
  const missingCodes = {REPRESENTATION_NOT_APPLICABLE: "表示不适用", MEASUREMENT_NOT_IMPLEMENTED: "未实现", GLYPH_UNITS_NOT_AVAILABLE: "缺少字形单元"};
  return `<section class="inspector-section research-overview"><h3>比较问题</h3><p>${escapeHtml(run.config.question)}</p><p>登记作品组 ${new Set(workIds.filter(Boolean)).size} · 未登记作品的输入 ${workIds.filter((value) => !value).length} · 本运行输入 ${run.snapshot.materials.length} · 实际调用 ${results.actual_calls} / ${results.planned_tasks} · 纳入调用 ${validCalls} · 回答条目 ${results.rows.length}</p><p>synthetic_persona · 作品组不是人类样本；Auto显示名不保证固定底层模型。</p>
    ${comparison.reference_run_id ? `<p>参考运行：<button class="entity-button" data-study="${escapeHtml(comparison.reference_run_id)}">${escapeHtml(run.snapshot.reference_run.config.name)}</button> · 调用 ${comparison.reference_actual_calls} / ${comparison.reference_planned_tasks}</p><p>下列表示差值为本运行减参考运行；变换条件见各输入，独立调用的波动仍无法与表示差异完全分离。</p>` : ""}
    <div class="research-inputs">${run.snapshot.materials.map((record) => {
      const materialId = record.selection.material_id;
      const summary = results.materials.find((item) => item.material_id === materialId);
      const referenceInput = run.snapshot.reference_run?.snapshot.materials.find((item) => item.selection.material_id === materialId);
      return `<article class="research-input"><h4>${escapeHtml(summary.title)}</h4><div class="material-pair">${referenceInput ? `<figure><img class="material-preview" src="/api/research/${comparison.reference_run_id}/inputs/${materialId}" alt="${escapeHtml(summary.title)} 参考输入"><figcaption>参考输入</figcaption></figure>` : ""}${record.input_path ? `<figure><img class="material-preview" src="/api/research/${run.run_id}/inputs/${materialId}" alt="${escapeHtml(summary.title)} 本次输入"><figcaption>本次输入 · ${escapeHtml(record.selection.representation)}${record.selection.crop_box ? ` · ${record.selection.crop_box.join(", ")}` : " · 完整图"}</figcaption></figure>` : "<p>无可用输入</p>"}</div>
      <p>颜色 ${escapeHtml(record.selection.color_mode || "native")} · 最长边 ${record.selection.max_edge ?? "未限制"} · ${results.measurement_bridge?.rows.length ? "评分按题项条件另列" : `美观中位数 ${summary.median_aesthetic ?? "未评分"} · 范围 ${summary.range_aesthetic?.join(" 至 ") || "无"}`} · 美观有效 ${summary.observed_aesthetic} / 计划 ${summary.planned_observations} · 缺失或未执行 ${summary.missing_or_unexecuted}</p>
      <dl class="research-differences">${[...["zh", "en", "ja", "ko"].filter((role) => run.config.roles.includes(role)).map((role) => [`${role} 减基线`, results.identity_differences.filter((item) => item.role === role)]), ["重复减首次", results.repeat_differences], ["反序减正序", results.order_and_call_differences], ...(comparison.reference_run_id ? [["本表示减参考", comparison.pairs]] : [])].map(([label, items]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(differenceRange(items.filter((item) => item.material_id === materialId)))}</dd></div>`).join("")}</dl>
      ${comparison.reference_run_id ? `<p>逐对表示差值：${comparison.pairs.filter((pair) => pair.material_id === materialId).map((pair) => researchNumber(pair.difference)).join(", ") || "无有效配对"}</p><details><summary>表示配对与未匹配记录</summary><pre class="json-block">${escapeHtml(JSON.stringify({pairs: comparison.pairs.filter((pair) => pair.material_id === materialId), unmatched: (comparison.unmatched || []).filter((item) => item.material_id === materialId)}, null, 2))}</pre></details>` : ""}
      <details><summary>测量对象与适用量</summary><p>${escapeHtml(summary.measurement?.scope || "尚未测量")} · ${escapeHtml(summary.measurement?.measurement_kind || "NA")} · 前景 ${escapeHtml(summary.measurement?.foreground || "unconfirmed")}</p><p>${escapeHtml(record.selection.foreground_note || "未确认文字前景，构图量不能解释为独立字形量。")}</p><p>阈值 96 / 128 / 160。连通域不是字符数；测量不是美感真值。</p><div class="table-wrap"><table><thead><tr><th>原始量</th><th>三阈值</th><th>不适用 / 缺失</th></tr></thead><tbody>${(summary.threshold_sensitivity || []).map((metric) => {
        const codes = [...new Set((summary.measurement?.thresholds || []).map((entry) => entry.metrics[metric.feature].missing_code).filter(Boolean))];
        return `<tr><td>${escapeHtml(metric.feature)}</td><td>${metric.values.map(researchNumber).join(" / ")}</td><td>${codes.map((code) => escapeHtml(missingCodes[code] || code)).join(", ") || "适用"}</td></tr>`;
      }).join("") || emptyRow(3, "尚未测量")}</tbody></table></div></details></article>`;
    }).join("")}</div></section>
    <section class="inspector-section"><h3>条件覆盖</h3><div class="table-wrap"><table><thead><tr><th>身份 / 顺序 / 重复 / 图片组</th><th>状态</th><th>实际尝试</th><th>有效美观回答 / 输入数</th></tr></thead><tbody>${results.tasks_and_raw_returns.map((task) => `<tr><td>${escapeHtml(task.condition.role)} / ${escapeHtml(task.condition.order)} / ${task.condition.repetition + 1} / ${(task.condition.block ?? 0) + 1}</td><td>${badge(task.status)}</td><td>${task.attempts.length}</td><td>${results.rows.filter((row) => row.task_id === task.task_id && (row.aesthetic != null || ["A", "B", "tie"].includes(row.preference_choice))).length} / ${task.inputs?.length ?? run.snapshot.materials.length}</td></tr>`).join("") || emptyRow(4)}</tbody></table></div></section>
    <section class="inspector-section"><h3>本次具体来源</h3>${(results.four_line_evidence.specific_sources?.entries || []).map((entry) => `<article class="research-source"><h4>${escapeHtml(entry.evidence_id)}</h4><p><a href="${escapeHtml(entry.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(entry.source_url)}</a></p><p>核验位置：${escapeHtml(entry.locator)} · ${escapeHtml(entry.accessed_at)}</p><p>来源事实：${escapeHtml(entry.source_facts)}</p><p>可支持：${escapeHtml(entry.supports)}</p><p>不能支持：${escapeHtml(entry.does_not_support)}</p><details><summary>核验范围与局限</summary><p>${escapeHtml(entry.verification_scope)}</p><p>${escapeHtml(entry.evidence_level)} · ${escapeHtml(entry.limitations)}</p></details></article>`).join("") || "<p>本运行尚未绑定具体来源。后面的通用文献仅作背景，不是每件资产的直接证据。</p>"}</section>`;
}

function renderPresentationComparison(results) {
  const comparison = results.presentation_comparison;
  if (!comparison?.pairs.length) return "";
  const titleFor = (materialId) => results.materials.find((item) => item.material_id === materialId)?.title || materialId;
  return `<section class="inspector-section"><h3>读取顺序与比较集合</h3><p>相同焦点字体、内容、绝对槽位、身份及重复编号匹配；三图减两图仍包含集合大小、第三图和调用变化，不是纯第三字体效应。</p><div class="table-wrap"><table><thead><tr><th>内容 / 焦点槽位</th><th>字体差值方向</th><th>三图 / 两图差值</th><th>差值之差</th></tr></thead><tbody>${comparison.matched_slot_set_contrasts.map((item) => `<tr><td>${escapeHtml(item.group_id)} · ${item.reference_position}, ${item.comparison_position}<br>重复 ${item.repetition + 1}</td><td>${escapeHtml(titleFor(item.comparison_material_id))}<br>减 ${escapeHtml(titleFor(item.reference_material_id))}</td><td>${researchNumber(item.triple_difference)} / ${researchNumber(item.pair_difference)}</td><td>${researchNumber(item.difference_of_differences)}</td></tr>`).join("") || emptyRow(4, "尚无同槽位合格配对")}</tbody></table></div><details><summary>各精确序列的同调用差值</summary><div class="table-wrap"><table><thead><tr><th>内容 / 序列 / 重复</th><th>比较减参考</th><th>槽位</th><th>美观差值</th></tr></thead><tbody>${comparison.pairs.map((item) => `<tr><td>${escapeHtml(item.group_id)} / ${escapeHtml(item.order)} / ${item.repetition + 1}</td><td>${escapeHtml(titleFor(item.comparison_material_id))}<br>减 ${escapeHtml(titleFor(item.reference_material_id))}</td><td>${item.comparison_position} - ${item.reference_position}</td><td>${researchNumber(item.differences.aesthetic)}</td></tr>`).join("")}</tbody></table></div></details></section>`;
}

function renderPairedChoices(results) {
  if (!results.paired_choices?.length) return "";
  const choices = {A: "A", B: "B", tie: "持平", same: "相同", unable: "无法判断"};
  const contrasts = {"w400-w100": "400 / 100", "w900-w400": "900 / 400", "w900-w100": "900 / 100", "serif400-sans400": "宋体400 / 黑体400", "serif400-sans100": "宋体400 / 黑体100"};
  return `<section class="inspector-section"><h3>成对美观选择</h3><p>synthetic_persona · 数字美观未采集 · ${results.paired_choices.length} 条选择</p><div class="table-wrap"><table><thead><tr><th>字样 / 对比</th><th>前项位置</th><th>美观选择</th><th>较粗选择</th></tr></thead><tbody>${results.paired_choices.map((row) => `<tr><td><button class="entity-button" data-material="${escapeHtml(row.material_id)}">${escapeHtml(row.content || row.material_id)}</button><br>${escapeHtml(contrasts[row.contrast] || row.contrast || "未映射")}</td><td>${escapeHtml(row.positive_label || "未映射")}</td><td>${escapeHtml(choices[row.preference_choice] || "缺失")}</td><td>${escapeHtml(choices[row.heavier_choice] || "未采集")}</td></tr>`).join("")}</tbody></table></div></section>`;
}

async function showStudy(runId, trigger) {
  const run = await request(`/api/research/${encodeURIComponent(runId)}`);
  const tasks = await request(`/api/research/${encodeURIComponent(runId)}/tasks`);
  const results = await request(`/api/research/${encodeURIComponent(runId)}/results`);
  document.querySelector("#inspector-title").textContent = run.config.name;
  document.querySelector("#inspector-content").innerHTML = `<section class="inspector-section"><h3>${escapeHtml(run.status)}</h3><p>${escapeHtml(run.config.question)}</p>${run.snapshot.materials.map((record) => `<button class="entity-button" data-material="${escapeHtml(record.selection.material_id)}">${escapeHtml(record.material.source?.title || record.selection.material_id)}</button>`).join("<br>")}</section>
    <section class="inspector-section"><h3>实际模型结果</h3><p>已记录调用 ${results.actual_calls} / 计划任务 ${results.planned_tasks} · 协议偏离 ${results.protocol_deviation_calls} · 失败 ${results.failed_calls} · 重试 ${results.retries}</p>
    ${results.measurement_bridge?.rows.length ? "" : `<div class="table-wrap"><table><thead><tr><th>实例</th><th>美观中位数</th><th>范围</th><th>有效 / 缺失或未执行</th></tr></thead><tbody>${results.materials.map((item) => `<tr><td><button class="entity-button" data-material="${escapeHtml(item.material_id)}">${escapeHtml(item.title)}</button></td><td>${item.median_aesthetic ?? "未评分"}</td><td>${escapeHtml(item.range_aesthetic?.join(" - ") || "未评分")}</td><td>${item.observed_aesthetic} / ${item.missing_or_unexecuted}</td></tr>`).join("")}</tbody></table></div>`}
    <p>synthetic_persona · 有序评分的描述比较，不代表真实人群或因果贡献。</p>
    <button class="button" data-export-study="${escapeHtml(runId)}">导出内部审计包</button><div id="research-download"></div></section>
    <section class="inspector-section"><h3>逐次评分与模型事后描述</h3><div class="table-wrap"><table><thead><tr><th>任务 / 材料</th><th>条件</th><th>美观 / 高端定位 / 清晰度</th><th>模型理由与联想</th></tr></thead><tbody>${results.rows.map((row) => `<tr><td class="mono">${escapeHtml(row.task_id)}<br>${escapeHtml(row.material_id)}</td><td>${escapeHtml(row.role)} / ${escapeHtml(row.order)} / ${row.repetition}<br>${escapeHtml(row.questionnaire_version || "synthetic_persona-q2")}</td><td>${["aesthetic", "premium_positioning", "visual_clarity"].map((scale) => scoreText(row, scale)).join(" / ")}</td><td>${escapeHtml(row.reason)}<br>${escapeHtml(row.associations)}</td></tr>`).join("") || emptyRow(4, "尚无通过视觉证据核验的回答")}</tbody></table></div></section>
    <section class="inspector-section"><h3>匹配比较与视觉量</h3><details><summary>身份减基线、同条件重复、顺序与同内容字体差值</summary><pre class="json-block">${escapeHtml(JSON.stringify({identity: results.identity_differences, repetition: results.repeat_differences, order_and_call: results.order_and_call_differences, font_pairs: results.within_content_font_pairs}, null, 2))}</pre></details><details><summary>三阈值原始测量及敏感性</summary><pre class="json-block">${escapeHtml(JSON.stringify(results.materials, null, 2))}</pre></details></section>
    <section class="inspector-section"><h3>通用背景文献与未匹配项</h3>${results.four_line_evidence.literature.map((item) => `<details><summary>${escapeHtml(item.evidence_id)} · 背景记录，非资产特定证据</summary><p>${escapeHtml(item.original_record)}</p></details>`).join("")}<details><summary>当前字体字符映射、汉字实例与文化叙事缺口</summary><pre class="json-block">${escapeHtml(JSON.stringify({instances: results.four_line_evidence.instances, task04_source: results.four_line_evidence.task04_source, social_evidence: results.four_line_evidence.social_evidence}, null, 2))}</pre></details></section>
    <section class="inspector-section"><h3>用途阻塞</h3><pre class="json-block">${escapeHtml(JSON.stringify(run.snapshot.blockers, null, 2))}</pre><details><summary>配置、输入与推断限制</summary><pre class="json-block">${escapeHtml(JSON.stringify({run, limits: results.limits}, null, 2))}</pre></details></section>`;
  openInspector(trigger);
  const controls = document.createElement("section");
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", `<section class="inspector-section"><details><summary>本次实际输入与表示</summary><div class="material-pair">${run.snapshot.materials.filter((record) => record.input_path).map((record) => `<figure><img class="material-preview" loading="lazy" src="/api/research/${encodeURIComponent(runId)}/inputs/${encodeURIComponent(record.selection.material_id)}" alt="本次研究输入"><figcaption>${escapeHtml(record.material.source?.title || record.selection.material_id)} · ${escapeHtml(record.selection.representation)}${record.selection.crop_box ? ` · 区域 ${record.selection.crop_box.join(", ")}` : ""}</figcaption></figure>`).join("")}</div></details></section>`);
  controls.className = "inspector-section";
  controls.innerHTML = `<h3>视觉问卷</h3><p>执行端：${escapeHtml(tasks.executor)}</p><button class="button" data-prepare-personas="${escapeHtml(runId)}" ${run.snapshot.blockers.length || tasks.tasks.length ? "disabled" : ""}>生成问卷任务</button><div class="table-wrap"><table><thead><tr><th>条件</th><th>状态</th><th>调用</th><th>操作</th></tr></thead><tbody>${tasks.tasks.map((task) => `<tr><td>${escapeHtml(task.condition.role)} / ${escapeHtml(task.condition.order)} / ${task.condition.repetition}</td><td>${badge(task.status)}</td><td>${task.attempts.length}</td><td>${task.status === "failed" ? `<button class="button" data-study-transition="tasks/${escapeHtml(task.task_id)}/retry" data-run="${escapeHtml(runId)}">重新排队</button>` : ""}</td></tr>`).join("") || emptyRow(4)}</tbody></table></div><details><summary>任务、原始回答与看图证据</summary><pre class="json-block">${escapeHtml(JSON.stringify(tasks, null, 2))}</pre></details>`;
  document.querySelector("#inspector-content").prepend(controls);
  controls.insertAdjacentHTML("afterbegin", `<div class="action-row"><button class="button" data-clone-study="${escapeHtml(runId)}">复用配置</button>${run.status === "suspended" ? `<button class="button" data-study-transition="resume" data-run="${escapeHtml(runId)}">恢复队列</button>` : `<button class="button" data-suspend-study="${escapeHtml(runId)}">暂停队列</button>`}<button class="icon-button" data-study="${escapeHtml(runId)}" aria-label="刷新运行状态" title="刷新运行状态">↻</button></div>`);
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderStudyOverview(run, results));
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderPresentationComparison(results));
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderMeasurementBridge(results));
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderOutcomeRepresentation(results));
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderPairedChoices(results));
  document.querySelector("#inspector-content").insertAdjacentHTML("afterbegin", renderResearchJudgments(run, results));
}

function scoreText(row, scale) {
  if (row.outcome_status?.[scale] === "not_collected" || (!row.questionnaire_mode && scale === "premium_positioning")) return "未采集";
  return row[scale] ?? "缺失";
}

function renderOutcomeRepresentation(results) {
  const pairs = results.representation_comparison?.pairs.filter((pair) => pair.questionnaire_mode && pair.questionnaire_mode !== "q2") || [];
  if (!pairs.length) return "";
  const titleFor = (materialId) => results.materials.find((item) => item.material_id === materialId)?.title || materialId;
  return `<section class="inspector-section"><h3>表示变化与两种评分</h3><p>本表示减参考表示；相同图源、身份、题项模式与重复编号匹配。美观和高端定位分别列出；变换与独立调用的共同变化仍在。</p><div class="table-wrap"><table><thead><tr><th>作品 / 题序 / 重复</th><th>美观 当前 / 参考 / 差</th><th>高端 当前 / 参考 / 差</th></tr></thead><tbody>${pairs.map((pair) => `<tr><td>${escapeHtml(titleFor(pair.material_id))}<br>${pair.questionnaire_mode === "aesthetic_premium" ? "美观先" : "高端先"} / ${pair.repetition + 1}</td><td>${pair.aesthetic} / ${pair.reference_aesthetic} / ${pair.difference}</td><td>${researchNumber(pair.premium_positioning)} / ${researchNumber(pair.reference_premium_positioning)} / ${researchNumber(pair.premium_difference)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

function renderMeasurementBridge(results) {
  if (!results.measurement_bridge?.rows.length || results.paired_choices?.length) return "";
  const modes = {aesthetic_only: "仅美观", premium_only: "仅高端", aesthetic_premium: "美观→高端", premium_aesthetic: "高端→美观"};
  const titleFor = (materialId) => results.materials.find((item) => item.material_id === materialId)?.title || materialId;
  return `<section class="inspector-section"><h3>美观与高端定位</h3><p>q3 · 美观为主要结果，高端定位独立记录。只问一题时另一题为未采集；双题才有同调用联合观测。不与旧q2混分。</p><div class="table-wrap"><table><thead><tr><th>实例</th><th>题项条件</th><th>美观逐次值</th><th>高端逐次值</th></tr></thead><tbody>${results.materials.flatMap((item) => Object.entries(modes).filter(([mode]) => item.outcomes_by_condition?.some((outcome) => outcome.questionnaire_mode === mode)).map(([mode, title]) => `<tr><td>${escapeHtml(item.title)}</td><td>${title}</td>${["aesthetic", "premium_positioning"].map((scale) => { const outcome = item.outcomes_by_condition.find((entry) => entry.questionnaire_mode === mode && entry.outcome === scale); return `<td>${outcome?.status === "not_collected" ? "未采集" : `${outcome?.values.join(", ") || "无评分"} · 缺失/未执行 ${outcome?.missing_or_unexecuted ?? "未知"}`}</td>`; }).join("")}</tr>`)).join("")}</tbody></table></div><details><summary>加题与题序的同材料配对差值</summary><p>当前条件减参考条件；图像、身份、重复编号与模型显示名匹配，调用波动仍在。未匹配 ${results.measurement_bridge.unmatched.length} 项。</p><div class="table-wrap"><table><thead><tr><th>实例 / 重复</th><th>结果</th><th>当前减参考</th><th>差值</th></tr></thead><tbody>${results.measurement_bridge.contrasts.map((pair) => `<tr><td>${escapeHtml(titleFor(pair.material_id))} / ${pair.repetition + 1}</td><td>${pair.outcome === "aesthetic" ? "美观" : "高端定位"}</td><td>${modes[pair.condition]} 减 ${modes[pair.reference_condition]}</td><td>${pair.difference}</td></tr>`).join("") || emptyRow(4)}</tbody></table></div></details></section>`;
}

function submittedDesignContract(draft) {
  const previous = draft?.design_contract || {};
  return {
    status: "exploratory_ui_revision",
    evidence_level: "synthetic_persona",
    primary_outcome: "aesthetic",
    ...(previous.board_mapping ? {board_mapping: previous.board_mapping, board_mapping_scope: "unchanged source-board member provenance, not a frozen hypothesis"} : {}),
    inherited_contract: previous.inherited_contract || previous,
    inherited_contract_status: "provenance_only_not_current_protocol",
  };
}

function captureStudyDraft() {
  const form = document.querySelector("#study-form");
  if (!form) return;
  const config = {design_version: state.draftConfig?.design_version, design_contract: state.draftConfig?.design_contract, presentation_plan: state.draftConfig?.presentation_plan};
  for (const key of ["presentation_mode", "schedule_seed", "questionnaire_mode"]) config[key] = form.querySelector(`[name='${key}']`)?.value;
  config.focal_font_ids = [...(form.querySelector("[name='focal_font_ids']")?.selectedOptions || [])].map((option) => option.value);
  config.bridge_modes = [...(form.querySelectorAll("[name='bridge_modes']") || [])].filter((field) => field.checked).map((field) => field.value);
  for (const key of ["name", "question", "questionnaire_language", "wording", "repetitions", "selection_scope", "stopping_rule", "executor_agent", "reference_run_id", "task_size", "design_rationale", "parent_assessment_id"]) config[key] = form.querySelector(`[name='${key}']`).value;
  config.explanations = form.querySelector("[name='explanations']").value.split("\n");
  config.predictions = form.querySelector("[name='predictions']").value.split("\n");
  for (const key of ["roles", "orders"]) config[key] = [...form.querySelectorAll(`[name='${key}']`)].filter((field) => field.checked).map((field) => field.value);
  config.selections = [...form.querySelectorAll("[data-study-selection]")].map((row) => ({
    material_id: row.dataset.studySelection,
    representation: row.querySelector("[name='representation']").value,
    reason: row.querySelector("[name='reason']").value,
    crop_box: ["left", "top", "right", "bottom"].map((edge) => row.querySelector(`[name='crop_${edge}']`).value),
    foreground: row.querySelector("[name='foreground']").value,
    foreground_note: row.querySelector("[name='foreground_note']").value,
    color_mode: row.querySelector("[name='color_mode']").value,
    max_edge: row.querySelector("[name='max_edge']").value,
  }));
  state.draftConfig = config;
}

function fillStudyDraft() {
  const config = state.draftConfig;
  const form = document.querySelector("#study-form");
  if (!config || !form) return;
  for (const key of ["presentation_mode", "schedule_seed", "questionnaire_mode"]) {
    const field = form.querySelector(`[name='${key}']`);
    if (field && config[key] !== undefined) field.value = config[key];
  }
  for (const option of form.querySelector("[name='focal_font_ids']")?.options || []) option.selected = (config.focal_font_ids || []).includes(option.value);
  for (const field of form.querySelectorAll("[name='bridge_modes']") || []) field.checked = (config.bridge_modes || ["aesthetic_only", "premium_only", "aesthetic_premium", "premium_aesthetic"]).includes(field.value);
  for (const key of ["name", "question", "questionnaire_language", "wording", "repetitions", "selection_scope", "stopping_rule", "executor_agent", "reference_run_id", "task_size", "design_rationale", "parent_assessment_id"]) {
    const field = form.querySelector(`[name='${key}']`);
    if (field && config[key] !== undefined) field.value = config[key] ?? "";
  }
  form.querySelector("[name='explanations']").value = config.explanations.join("\n");
  form.querySelector("[name='predictions']").value = (config.predictions || []).join("\n");
  for (const key of ["roles", "orders"]) form.querySelectorAll(`[name='${key}']`).forEach((input) => { input.checked = config[key].includes(input.value); });
  for (const selection of config.selections) {
    const row = form.querySelector(`[data-study-selection='${selection.material_id}']`);
    if (row) {
      row.querySelector("[name='representation']").value = selection.representation;
      row.querySelector("[name='reason']").value = selection.reason;
      row.querySelector("[name='foreground']").value = selection.foreground ?? "unconfirmed";
      row.querySelector("[name='foreground_note']").value = selection.foreground_note ?? "";
      row.querySelector("[name='color_mode']").value = selection.color_mode ?? "native";
      row.querySelector("[name='max_edge']").value = selection.max_edge ?? "";
      ["left", "top", "right", "bottom"].forEach((edge, index) => { row.querySelector(`[name='crop_${edge}']`).value = selection.crop_box?.[index] ?? ""; });
    }
  }
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
        const kind = document.querySelector("#material-kind")?.value;
        row.hidden = (Boolean(query) && !row.textContent.toLocaleLowerCase("zh-Hans").includes(query)) || (Boolean(kind) && row.dataset.materialKind !== kind);
      });
    });
  });
}

async function loadBase(force = false) {
  if (!state.overview || force) state.overview = await request("/api/overview");
  if (!state.health || force) state.health = await request("/api/health");
  document.querySelector("#rail-health").textContent = state.health.status === "ready" ? "系统可用" : "系统阻断";
}

async function navigate(view, force = false, preserveDraft = true) {
  if (!labels[view]) view = "overview";
  if (preserveDraft) captureStudyDraft();
  closeInspector();
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
    } else if (view === "assets") {
      content = renderMaterials(await request("/api/materials?limit=500"));
    } else if (view === "research") {
      content = renderResearch(await request("/api/research"), await request("/api/materials?limit=500"));
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
    if (view === "research") fillStudyDraft();
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
  const previewButton = event.target.closest("[data-preview-selection]");
  if (previewButton) {
    const row = previewButton.closest("[data-study-selection]");
    const parameters = new URLSearchParams();
    for (const edge of ["left", "top", "right", "bottom"]) {
      const value = row.querySelector(`[name='crop_${edge}']`).value;
      if (value !== "") parameters.set(edge, value);
    }
    const foreground = row.querySelector("[name='foreground']").value;
    parameters.set("foreground", foreground);
    parameters.set("color_mode", row.querySelector("[name='color_mode']").value);
    const maxEdge = row.querySelector("[name='max_edge']").value;
    if (maxEdge !== "") parameters.set("max_edge", maxEdge);
    const layers = foreground === "unconfirmed" ? ["input"] : ["input", "mask", "overlay"];
    const representation = row.querySelector("[name='representation']").value;
    row.querySelector("[data-selection-preview]").innerHTML = layers.map((layer) => `<figure><img class="material-preview" src="/api/materials/${encodeURIComponent(previewButton.dataset.previewSelection)}/preview/${representation}?${parameters}&layer=${layer}" alt="${{input:"实际输入",mask:"文字掩码：阈值128",overlay:"前景叠加：阈值128"}[layer]}"><figcaption>${{input:"实际输入",mask:"文字掩码：阈值128",overlay:"前景叠加：阈值128"}[layer]}</figcaption></figure>`).join("");
    return;
  }
  if (event.target.closest("[data-new-study]")) {
    state.draftConfig = null;
    state.selectedMaterials = new Set();
    navigate("research", true, false);
    return;
  }
  const transitionButton = event.target.closest("[data-study-transition]");
  if (transitionButton) {
    transitionButton.disabled = true;
    request(`/api/research/${transitionButton.dataset.run}/${transitionButton.dataset.studyTransition}`, {method: "POST"}).then(() => showStudy(transitionButton.dataset.run, state.inspectorTrigger)).catch((error) => {toast(error.message, true); transitionButton.disabled = false;});
    return;
  }
  const cloneButton = event.target.closest("[data-clone-study]");
  const continueButton = event.target.closest("[data-continue-assessment]");
  if (continueButton) {
    request(`/api/research-assessments/${continueButton.dataset.continueAssessment}/continue`).then(({config}) => {
      state.draftConfig = config;
      state.selectedMaterials = new Set(config.selections.map((item) => item.material_id));
      closeInspector();
      return navigate("research", true, false);
    }).catch((error) => toast(error.message, true));
    return;
  }
  if (cloneButton) {
    request(`/api/research/${cloneButton.dataset.cloneStudy}`).then((run) => {
      state.draftConfig = {...run.config, name: `${run.config.name}-新版本`};
      state.selectedMaterials = new Set(run.config.selections.map((item) => item.material_id));
      closeInspector();
      return navigate("research", true, false);
    }).catch((error) => toast(error.message, true));
    return;
  }
  const suspendButton = event.target.closest("[data-suspend-study]");
  if (suspendButton) {
    request(`/api/research/${suspendButton.dataset.suspendStudy}/suspend`, {method:"POST"}).then(() => showStudy(suspendButton.dataset.suspendStudy, state.inspectorTrigger)).catch((error) => toast(error.message, true));
    return;
  }
  const prepareButton = event.target.closest("[data-prepare-personas]");
  if (prepareButton) {
    prepareButton.disabled = true;
    request(`/api/research/${prepareButton.dataset.preparePersonas}/tasks`, {method: "POST"}).then(() => showStudy(prepareButton.dataset.preparePersonas, state.inspectorTrigger)).catch((error) => {toast(error.message, true); prepareButton.disabled = false;});
    return;
  }
  const exportStudy = event.target.closest("[data-export-study]");
  if (exportStudy) {
    exportStudy.disabled = true;
    request(`/api/research/${exportStudy.dataset.exportStudy}/export`, {method: "POST"}).then((result) => {
      document.querySelector("#research-download").innerHTML = `<a href="${escapeHtml(result.download_url)}" download>下载 ${escapeHtml(result.export_id)}.zip</a><p class="mono">SHA-256: ${escapeHtml(result.sha256)}</p>`;
    }).catch((error) => toast(error.message, true)).finally(() => {exportStudy.disabled = false;});
    return;
  }
  const studyButton = event.target.closest("[data-study]");
  if (studyButton) { showStudy(studyButton.dataset.study, studyButton).catch((error) => toast(error.message, true)); return; }
  const measureButton = event.target.closest("[data-study-measure]");
  if (measureButton) {
    measureButton.disabled = true;
    request(`/api/research/${measureButton.dataset.studyMeasure}/measure`, {method: "POST"}).then(() => navigate("research", true)).catch((error) => { toast(error.message, true); measureButton.disabled = false; });
    return;
  }
  const materialButton = event.target.closest("[data-material]");
  if (materialButton) { showMaterial(materialButton.dataset.material, materialButton); return; }
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

document.addEventListener("submit", async (event) => {
  if (event.target.id === "font-sample-form") {
    event.preventDefault();
    captureStudyDraft();
    const form = event.target;
    const fields = new FormData(form);
    const config = Object.fromEntries(["weight", "font_size", "width", "height"].map((key) => [key, Number(fields.get(key))]));
    config.font_ids = fields.getAll("font_ids");
    config.texts = String(fields.get("texts")).split("\n").filter(Boolean);
    const button = form.querySelector("[type='submit']");
    button.disabled = true;
    try {
      const {items} = await request("/api/research/font-samples", {method: "POST", body: JSON.stringify(config)});
      state.selectedMaterials = new Set(items.map((item) => item.material_id));
      state.draftConfig.selections = items.map((item) => ({material_id: item.material_id, representation: "original", reason: "同内容、固定画布、明确字重的字体对照"}));
      await navigate("research", true, false);
    } catch (error) { toast(error.message, true); button.disabled = false; }
    return;
  }
  if (event.target.matches("[data-assessment-form]")) {
    event.preventDefault();
    const form = event.target;
    const fields = new FormData(form);
    const payload = Object.fromEntries(["conclusion", "next_question", "next_comparison", "decision"].map((key) => [key, fields.get(key)]));
    payload.basis_result_sha256 = form.dataset.basisResult;
    payload.remaining_confounds = String(fields.get("remaining_confounds")).split("\n").filter(Boolean);
    payload.explanation_updates = [...form.querySelectorAll("[data-explanation-index]")].map((group) => ({explanation: group.querySelector("[name='explanation']").value, judgment: group.querySelector("[name='judgment']").value, evidence: group.querySelector("[name='evidence']").value, material_ids: [...group.querySelectorAll("[name='material_ids']:checked")].map((input) => input.value)}));
    const button = form.querySelector("[type='submit']");
    button.disabled = true;
    try {
      await request(`/api/research/${form.dataset.assessmentForm}/assessments`, {method: "POST", body: JSON.stringify(payload)});
      await showStudy(form.dataset.assessmentForm, state.inspectorTrigger);
    } catch (error) { toast(error.message, true); button.disabled = false; }
    return;
  }
  if (event.target.id !== "study-form") return;
  event.preventDefault();
  const form = event.target;
  const fields = new FormData(form);
  const config = Object.fromEntries(fields.entries());
  config.roles = ["baseline", ...fields.getAll("roles")];
  config.orders = fields.getAll("orders");
  config.repetitions = Number(fields.get("repetitions"));
  config.reference_run_id = fields.get("reference_run_id") || null;
  config.parent_assessment_id = fields.get("parent_assessment_id") || null;
  config.task_size = fields.get("task_size") ? Number(fields.get("task_size")) : null;
  config.presentation_mode = fields.get("presentation_mode") || "legacy";
  config.questionnaire_mode = fields.get("questionnaire_mode") || "q2";
  config.bridge_modes = fields.getAll("bridge_modes");
  config.focal_font_ids = fields.getAll("focal_font_ids");
  config.schedule_seed = Number(fields.get("schedule_seed") || 20260911);
  config.design_contract = submittedDesignContract(state.draftConfig);
  config.design_version = "exploratory-ui-v1";
  config.presentation_plan = config.presentation_mode === "explicit" ? (state.draftConfig?.presentation_plan || []) : [];
  if (config.presentation_mode !== "legacy") config.task_size = null;
  config.explanations = String(fields.get("explanations")).split("\n").filter(Boolean);
  config.predictions = String(fields.get("predictions")).split("\n").filter(Boolean);
  const selectionRows = [...form.querySelectorAll("[data-study-selection]")];
  const cropValues = (row) => ["left", "top", "right", "bottom"].map((edge) => row.querySelector(`[name='crop_${edge}']`).value);
  if (selectionRows.some((row) => cropValues(row).some(Boolean) && !cropValues(row).every(Boolean))) { toast("矩形区域需填写四个边界。", true); return; }
  config.selections = selectionRows.map((row) => ({material_id: row.dataset.studySelection, representation: row.querySelector("[name='representation']").value, reason: row.querySelector("[name='reason']").value, crop_box: cropValues(row).some(Boolean) ? cropValues(row).map(Number) : null, foreground: row.querySelector("[name='foreground']").value, foreground_note: row.querySelector("[name='foreground_note']").value, color_mode: row.querySelector("[name='color_mode']").value, max_edge: row.querySelector("[name='max_edge']").value ? Number(row.querySelector("[name='max_edge']").value) : null}));
  for (const edge of ["left", "top", "right", "bottom"]) delete config[`crop_${edge}`];
  delete config.representation;
  delete config.reason;
  delete config.foreground;
  delete config.foreground_note;
  delete config.color_mode;
  delete config.max_edge;
  const button = form.querySelector("[type='submit']");
  button.disabled = true;
  try {
    await request("/api/research", {method: "POST", body: JSON.stringify(config)});
    await navigate("research", true);
  } catch (error) { toast(error.message, true); button.disabled = false; }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "material-kind") {
    document.querySelector("[data-filter]").dispatchEvent(new Event("input"));
    return;
  }
  const materialId = event.target.dataset.selectMaterial;
  if (!materialId) return;
  if (event.target.checked) state.selectedMaterials.add(materialId);
  else {
    state.selectedMaterials.delete(materialId);
    if (state.draftConfig) state.draftConfig.selections = state.draftConfig.selections.filter((item) => item.material_id !== materialId);
  }
  const counter = document.querySelector("#selection-count");
  if (counter) counter.textContent = `已选 ${state.selectedMaterials.size}`;
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

window.addEventListener("hashchange", () => navigate(window.location.hash.slice(1) || state.defaultView));
request("/api/session").then((session) => {
  if (session.material_catalog_configured) {
    state.defaultView = "research";
    document.querySelector(".environment-label").textContent = "LOCAL / RESEARCH";
    document.querySelector(".mode-chip").textContent = "内部研究 · 未正式发布";
    document.querySelector(".brand").href = "#research";
  }
  navigate(window.location.hash.slice(1) || state.defaultView);
}).catch(() => navigate(window.location.hash.slice(1) || state.defaultView));