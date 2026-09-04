"use strict";

const ui = {
  "zh-Hans": {
    language: "语言", gate: "真实收集已锁定", draft: "翻译草案 / 未经人工审核",
    stages: ["信息", "背景", "评价", "完成"], eyebrow: "跨文化视觉感知 / 工程验收",
    title: "在不泄漏文字身份的条件下评价视觉形式", boundary: "当前页面只生成 synthetic fixture。伦理、参与者与翻译门禁均未通过，无法收集或发布真人响应。",
    continue: "继续", setupTitle: "确认参与条件与文字经验", consent: "我理解当前为合成测试，并同意继续。",
    age: "我已达到最低参与年龄。", understood: "我能充分理解当前问卷语言。", scripts: "请选择你从小熟练使用的文字系统（可多选）",
    attention: "注意力检查：请选择圆形", start: "开始练习与评价", practiceTitle: "练习一次评分", practiceBody: "练习只用于熟悉操作，不会保存或进入分析。", practiceContinue: "完成练习并开始评价", latin: "拉丁", han: "汉字", kana: "假名", hangul: "韩文",
    circle: "圆形", square: "方形", triangle: "三角形", trial: "视觉评价", firstImpression: "请根据第一印象作答；无法判断时选择“不适用”。",
    submit: "提交并继续", notApplicable: "不适用", loadError: "刺激未能通过完整性校验，本试次已停止。", required: "请完成所有必答评分。",
    completeTitle: "合成流程已完成", completeBody: "本次记录仅用于工程验收，不会进入正式分析或 release。", restart: "开始新的合成会话"
  },
  en: {
    language: "Language", gate: "Real collection is locked", draft: "Translation draft / not human reviewed",
    stages: ["Information", "Background", "Ratings", "Complete"], eyebrow: "Cross-cultural visual perception / engineering check",
    title: "Rate visual form without revealing writing-system identity", boundary: "This page creates synthetic fixtures only. Ethics, participant and translation gates are blocked, so real responses cannot be collected or released.",
    continue: "Continue", setupTitle: "Confirm participation conditions and script experience", consent: "I understand this is a synthetic test and agree to continue.",
    age: "I meet the minimum participation age.", understood: "I can fully understand this questionnaire language.", scripts: "Select writing systems used proficiently since childhood (multiple allowed)",
    attention: "Attention check: select the circle", start: "Start practice and ratings", practiceTitle: "Practice one rating", practiceBody: "Practice is only for learning the controls. It is not saved or analyzed.", practiceContinue: "Finish practice and start ratings", latin: "Latin", han: "Han", kana: "Kana", hangul: "Hangul",
    circle: "Circle", square: "Square", triangle: "Triangle", trial: "Visual rating", firstImpression: "Answer from your first impression; choose not applicable when you cannot judge.",
    submit: "Submit and continue", notApplicable: "Not applicable", loadError: "The stimulus failed integrity verification. This trial has stopped.", required: "Complete every required rating.",
    completeTitle: "Synthetic flow complete", completeBody: "These records are for engineering checks only and cannot enter formal analysis or release.", restart: "Start a new synthetic session"
  },
  ja: {
    language: "言語", gate: "実データ収集はロック中", draft: "翻訳草案 / 人手未確認",
    stages: ["情報", "背景", "評価", "完了"], eyebrow: "異文化視覚知覚 / 工学確認",
    title: "文字体系の識別情報を示さずに視覚形式を評価", boundary: "このページは合成 fixture のみを生成します。倫理、参加者、翻訳のゲートが未承認のため、実在する参加者の回答は収集・公開できません。",
    continue: "続ける", setupTitle: "参加条件と文字経験の確認", consent: "合成テストであることを理解し、続行に同意します。",
    age: "最低参加年齢に達しています。", understood: "現在の質問票の言語を十分理解できます。", scripts: "幼少期から習熟して使う文字体系を選択（複数可）",
    attention: "注意確認：円を選択", start: "練習と評価を開始", practiceTitle: "評価を一度練習", practiceBody: "練習は操作に慣れるためだけのもので、保存も分析もされません。", practiceContinue: "練習を終えて評価を開始", latin: "ラテン", han: "漢字", kana: "仮名", hangul: "ハングル",
    circle: "円", square: "四角", triangle: "三角", trial: "視覚評価", firstImpression: "第一印象で回答し、判断できない場合は「該当なし」を選んでください。",
    submit: "送信して続ける", notApplicable: "該当なし", loadError: "刺激の完全性を確認できなかったため、この試行を停止しました。", required: "必須評価をすべて完了してください。",
    completeTitle: "合成フロー完了", completeBody: "記録は工学確認専用で、正式分析や release には入りません。", restart: "新しい合成セッション"
  },
  ko: {
    language: "언어", gate: "실제 수집 잠김", draft: "번역 초안 / 인적 검토 전",
    stages: ["정보", "배경", "평가", "완료"], eyebrow: "교차문화 시각 인식 / 엔지니어링 확인",
    title: "문자 체계 정체성을 공개하지 않고 시각적 형태 평가", boundary: "이 페이지는 합성 fixture만 생성합니다. 윤리, 참여자 및 번역 게이트가 승인되지 않아 실제 응답을 수집하거나 공개할 수 없습니다.",
    continue: "계속", setupTitle: "참여 조건과 문자 경험 확인", consent: "합성 테스트임을 이해하고 계속하는 데 동의합니다.",
    age: "최소 참여 연령을 충족합니다.", understood: "현재 설문 언어를 충분히 이해합니다.", scripts: "어릴 때부터 능숙하게 사용한 문자 체계를 선택하십시오(복수 선택 가능)",
    attention: "주의력 확인: 원을 선택하십시오", start: "연습 및 평가 시작", practiceTitle: "평가 한 번 연습", practiceBody: "연습은 조작을 익히기 위한 것이며 저장되거나 분석되지 않습니다.", practiceContinue: "연습 완료 후 평가 시작", latin: "라틴", han: "한자", kana: "가나", hangul: "한글",
    circle: "원", square: "사각형", triangle: "삼각형", trial: "시각 평가", firstImpression: "첫인상에 따라 답하고 판단할 수 없으면 해당 없음을 선택하십시오.",
    submit: "제출하고 계속", notApplicable: "해당 없음", loadError: "자극의 무결성 검증에 실패하여 이 시행을 중단했습니다.", required: "필수 평가를 모두 완료하십시오.",
    completeTitle: "합성 흐름 완료", completeBody: "이 기록은 엔지니어링 확인 전용이며 공식 분석이나 release에 들어갈 수 없습니다.", restart: "새 합성 세션"
  }
};

const state = {
  language: localStorage.getItem("glyph_task03_language") || "zh-Hans",
  status: null,
  questionnaire: null,
  assignment: null,
  nativeScripts: [],
  attentionPassed: false,
  trialStartedAt: null,
  trialStartedPerf: 0,
  preloadMs: 0,
  displayedHash: null,
  focusLosses: 0
};

const app = document.getElementById("app");
const languageSelect = document.getElementById("language-select");

document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.trialStartedAt) state.focusLosses += 1;
});

languageSelect.value = state.language;
languageSelect.addEventListener("change", () => {
  state.language = languageSelect.value;
  localStorage.setItem("glyph_task03_language", state.language);
  document.documentElement.lang = state.language;
  applyChrome();
  if (!state.assignment) renderIntro();
  else renderTrial();
});

async function init() {
  try {
    [state.status, state.questionnaire] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/questionnaire")
    ]);
    applyChrome();
    const participantId = localStorage.getItem("glyph_task03_participant");
    const scripts = JSON.parse(localStorage.getItem("glyph_task03_scripts") || "[]");
    if (participantId && scripts.length) {
      const response = await fetch(`/api/session/${encodeURIComponent(participantId)}`);
      if (response.ok) {
        state.assignment = await response.json();
        state.nativeScripts = scripts;
        if (state.assignment.status === "completed") renderComplete();
        else renderTrial();
        return;
      }
    }
    renderIntro();
  } catch (error) {
    app.innerHTML = `<p class="inline-error">${escapeHtml(String(error))}</p>`;
  }
}

function applyChrome() {
  const copy = ui[state.language];
  document.getElementById("language-label").textContent = copy.language;
  document.getElementById("gate-copy").textContent = copy.gate;
  document.getElementById("translation-state").textContent = copy.draft;
  ["intro", "setup", "trial", "complete"].forEach((stage, index) => {
    document.getElementById(`stage-${stage}`).textContent = copy.stages[index];
  });
}

function renderIntro() {
  setStage("intro");
  setProgress(0, 8);
  const copy = ui[state.language];
  const info = item("item_study_information");
  app.innerHTML = `
    <p class="eyebrow">${escapeHtml(copy.eyebrow)}</p>
    <h1>${escapeHtml(copy.title)}</h1>
    <p class="lead">${escapeHtml(info.translations[state.language].text)}</p>
    <p class="boundary-note">${escapeHtml(copy.boundary)}</p>
    <div class="actions"><button id="continue-button" class="primary-button" type="button">${escapeHtml(copy.continue)} <span aria-hidden="true">→</span></button></div>`;
  document.getElementById("continue-button").addEventListener("click", renderSetup);
}

function renderSetup() {
  setStage("setup");
  const copy = ui[state.language];
  app.innerHTML = `
    <p class="eyebrow">02 / ${escapeHtml(copy.stages[1])}</p>
    <h2>${escapeHtml(copy.setupTitle)}</h2>
    ${checkField("consent", copy.consent)}
    ${checkField("age", copy.age)}
    ${checkField("understood", copy.understood)}
    <fieldset class="form-section"><legend>${escapeHtml(copy.scripts)}</legend><div class="choice-grid">
      ${["latin", "han", "kana", "hangul"].map(script => choice("checkbox", "script", script, copy[script])).join("")}
    </div></fieldset>
    <fieldset class="form-section"><legend>${escapeHtml(copy.attention)}</legend><div class="choice-grid compact">
      ${choice("radio", "attention", "square", `□ ${copy.square}`)}
      ${choice("radio", "attention", "circle", `○ ${copy.circle}`)}
      ${choice("radio", "attention", "triangle", `△ ${copy.triangle}`)}
    </div></fieldset>
    <p id="setup-error" class="inline-error" hidden></p>
    <div class="actions"><button id="start-button" class="primary-button" type="button">${escapeHtml(copy.start)} <span aria-hidden="true">→</span></button></div>`;
  document.getElementById("start-button").addEventListener("click", startPractice);
}

function startPractice() {
  const copy = ui[state.language];
  const scripts = [...document.querySelectorAll('input[name="script"]:checked')].map(input => input.value);
  const attention = document.querySelector('input[name="attention"]:checked')?.value;
  const required = ["consent-yes", "age-yes", "understood-yes"].every(id => document.getElementById(id).checked);
  if (!required || !scripts.length || !attention) {
    showSetupError(copy.required);
    return;
  }
  state.nativeScripts = scripts;
  state.attentionPassed = attention === "circle";
  renderPractice();
}

async function renderPractice() {
  const copy = ui[state.language];
  setStage("trial");
  setProgress(0, 8);
  app.innerHTML = `
    <p class="eyebrow">${escapeHtml(copy.stages[2])} / PRACTICE</p>
    <h2>${escapeHtml(copy.practiceTitle)}</h2>
    <p class="lead">${escapeHtml(copy.practiceBody)}</p>
    <div class="stimulus-wrap"><div id="stimulus-stage" class="stimulus-stage"><p class="loading">Loading...</p></div></div>
    <form id="practice-form" class="ratings" hidden>
      ${ratingField(item("item_aesthetic"))}
      <p id="practice-error" class="inline-error" hidden></p>
      <div class="actions"><button class="primary-button" type="submit">${escapeHtml(copy.practiceContinue)} <span aria-hidden="true">→</span></button></div>
    </form>`;
  try {
    const practice = await fetchJson("/api/practice");
    const response = await fetch(practice.asset_url, {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const bytes = await response.arrayBuffer();
    const actualHash = await sha256Hex(bytes);
    if (actualHash !== practice.expected_asset_sha256) throw new Error("SHA256_MISMATCH");
    const imageUrl = URL.createObjectURL(new Blob([bytes], {type: response.headers.get("content-type") || "image/png"}));
    document.getElementById("stimulus-stage").innerHTML = `<img id="practice-image" src="${imageUrl}" alt="Neutral visual study practice stimulus">`;
    const form = document.getElementById("practice-form");
    form.hidden = false;
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (new FormData(form).get("item_aesthetic") === null) {
        const error = document.getElementById("practice-error");
        error.textContent = copy.required;
        error.hidden = false;
        return;
      }
      form.querySelector("button").disabled = true;
      createSession();
    });
  } catch (error) {
    document.getElementById("stimulus-stage").innerHTML = `<p class="asset-error">${escapeHtml(copy.loadError)}</p>`;
    announce(`${copy.loadError} ${String(error)}`);
  }
}

async function createSession() {
  let nonce = localStorage.getItem("glyph_task03_nonce");
  if (!nonce) {
    nonce = `browser_${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`;
    localStorage.setItem("glyph_task03_nonce", nonce);
  }
  try {
    state.assignment = await fetchJson("/api/session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({language: state.language, native_scripts: state.nativeScripts, session_nonce: nonce})
    });
    localStorage.setItem("glyph_task03_participant", state.assignment.participant_id);
    localStorage.setItem("glyph_task03_scripts", JSON.stringify(state.nativeScripts));
    renderTrial();
  } catch (error) {
    const errorElement = document.getElementById("practice-error");
    errorElement.textContent = String(error);
    errorElement.hidden = false;
    document.querySelector("#practice-form button").disabled = false;
  }
}

async function renderTrial() {
  const copy = ui[state.language];
  const index = Math.max(1, state.assignment.resume_next_trial);
  if (index > state.assignment.trials.length) {
    renderComplete();
    return;
  }
  setStage("trial");
  setProgress(index - 1, state.assignment.trials.length);
  const trial = state.assignment.trials[index - 1];
  app.innerHTML = `
    <div class="trial-header"><div><p class="eyebrow">03 / ${escapeHtml(copy.trial)}</p><h2>${escapeHtml(copy.firstImpression)}</h2></div><span class="trial-count">${index} / ${state.assignment.trials.length}</span></div>
    <div class="stimulus-wrap"><div id="stimulus-stage" class="stimulus-stage"><p class="loading">Loading...</p></div></div>
    <form id="ratings-form" class="ratings" hidden></form>
    <p id="trial-error" class="inline-error" hidden></p>`;
  state.focusLosses = 0;
  state.trialStartedAt = null;
  const preloadStart = performance.now();
  try {
    const response = await fetch(trial.asset_url, {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const bytes = await response.arrayBuffer();
    state.displayedHash = await sha256Hex(bytes);
    if (state.displayedHash !== trial.expected_asset_sha256) throw new Error("SHA256_MISMATCH");
    state.preloadMs = Math.round(performance.now() - preloadStart);
    const imageUrl = URL.createObjectURL(new Blob([bytes], {type: response.headers.get("content-type") || "image/png"}));
    document.getElementById("stimulus-stage").innerHTML = `<img id="stimulus-image" src="${imageUrl}" alt="Neutral visual study stimulus">`;
    const form = document.getElementById("ratings-form");
    form.innerHTML = `${ratingItems().map(ratingField).join("")}<p id="ratings-error" class="inline-error" hidden></p><div class="actions"><button class="primary-button" type="submit">${escapeHtml(copy.submit)} <span aria-hidden="true">→</span></button></div>`;
    form.hidden = false;
    form.addEventListener("submit", event => submitTrial(event, trial));
    state.trialStartedAt = new Date().toISOString();
    state.trialStartedPerf = performance.now();
  } catch (error) {
    document.getElementById("stimulus-stage").innerHTML = `<p class="asset-error">${escapeHtml(copy.loadError)}</p>`;
    announce(`${copy.loadError} ${String(error)}`);
  }
}

async function submitTrial(submitEvent, trial) {
  submitEvent.preventDefault();
  const copy = ui[state.language];
  const form = submitEvent.currentTarget;
  const responses = ratingItems().map(itemDefinition => ({item: itemDefinition, value: new FormData(form).get(itemDefinition.item_id)}));
  if (responses.some(response => response.value === null)) {
    const error = document.getElementById("ratings-error");
    error.textContent = copy.required;
    error.hidden = false;
    return;
  }
  const responseMs = Math.max(0, Math.round(performance.now() - state.trialStartedPerf));
  const now = new Date().toISOString();
  const imageRect = document.getElementById("stimulus-image").getBoundingClientRect();
  const viewportWidth = Math.round(window.innerWidth);
  const viewportHeight = Math.round(window.innerHeight);
  const qualitySignals = [];
  if (responseMs < 350) qualitySignals.push("TOO_FAST");
  if (viewportWidth < 320 || viewportHeight < 480) qualitySignals.push("VIEWPORT_UNUSABLE");
  if (state.focusLosses) qualitySignals.push("FOCUS_LOSS");
  const zoomAnomaly = Boolean(window.visualViewport && Math.abs(window.visualViewport.scale - 1) > 0.05);
  if (zoomAnomaly) qualitySignals.push("ZOOM_ANOMALY");
  const suffix = trial.presentation_id.slice(-20);
  const event = {
    schema_version: "1.0.0", event_id: `event_${suffix}`, request_id: `request_${suffix}`,
    study_id: state.assignment.study_id, assignment_id: state.assignment.assignment_id,
    presentation_id: trial.presentation_id, participant_id: state.assignment.participant_id,
    data_origin: "synthetic", stimulus_id: trial.stimulus_id,
    expected_asset_sha256: trial.expected_asset_sha256, displayed_asset_sha256: state.displayedHash,
    load_status: "loaded", trial_index: trial.trial_index, started_at: state.trialStartedAt, ended_at: now,
    preload_ms: state.preloadMs, response_ms: responseMs,
    viewport: {css_width: viewportWidth, css_height: viewportHeight, stimulus_css_width: Math.round(imageRect.width), stimulus_css_height: Math.round(imageRect.height), device_pixel_ratio: window.devicePixelRatio || 1},
    focus_loss_count: state.focusLosses, zoom_anomaly: zoomAnomaly, quality_signals: qualitySignals
  };
  const ratings = responses.map(({item: definition, value}) => {
    const missing = value === "not_applicable";
    return {
      schema_version: "2.0.0", rating_id: `rating_${suffix}_${definition.item_id.slice(5)}`,
      study_id: state.assignment.study_id, questionnaire_version: state.assignment.questionnaire_version,
      assignment_id: state.assignment.assignment_id, block_id: state.assignment.block_id,
      presentation_id: trial.presentation_id, stimulus_id: trial.stimulus_id,
      participant_id: state.assignment.participant_id, data_origin: "synthetic",
      respondent_language_bcp47: state.language, native_scripts: state.nativeScripts,
      item_id: definition.item_id, construct: definition.construct, rating_scale: "likert_1_7",
      response: {value: missing ? null : Number(value), missing_reason: missing ? "not_applicable" : null},
      displayed_asset_sha256: state.displayedHash, trial_index: trial.trial_index, response_time_ms: responseMs,
      attention_check: state.attentionPassed,
      quality: {rule_version: "1.0.0", exclude_from_analysis: !state.attentionPassed, reason_codes: state.attentionPassed ? [] : ["ATTENTION_FAILED"]},
      collected_at: now
    };
  });
  form.querySelector("button").disabled = true;
  try {
    await fetchJson("/api/submissions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({event, ratings})});
    state.assignment = await fetchJson(`/api/session/${encodeURIComponent(state.assignment.participant_id)}`);
    renderTrial();
  } catch (error) {
    form.querySelector("button").disabled = false;
    const errorElement = document.getElementById("ratings-error");
    errorElement.textContent = String(error);
    errorElement.hidden = false;
  }
}

function renderComplete() {
  setStage("complete");
  setProgress(8, 8);
  const copy = ui[state.language];
  app.innerHTML = `
    <p class="eyebrow">04 / ${escapeHtml(copy.stages[3])}</p>
    <h1>${escapeHtml(copy.completeTitle)}</h1>
    <p class="lead">${escapeHtml(copy.completeBody)}</p>
    <div class="actions"><button id="restart-button" class="secondary-button" type="button"><span aria-hidden="true">↻</span> ${escapeHtml(copy.restart)}</button></div>`;
  document.getElementById("restart-button").addEventListener("click", () => {
    ["glyph_task03_participant", "glyph_task03_scripts", "glyph_task03_nonce"].forEach(key => localStorage.removeItem(key));
    state.assignment = null;
    state.nativeScripts = [];
    renderIntro();
  });
}

function ratingItems() {
  return state.questionnaire.items.filter(itemDefinition => itemDefinition.response_type === "likert_1_7" && itemDefinition.item_id !== "item_brand_fit");
}

function ratingField(itemDefinition) {
  const copy = ui[state.language];
  const anchors = state.questionnaire.scale_definitions.likert_1_7.anchors[state.language];
  const options = [1, 2, 3, 4, 5, 6, 7].map(value => choice("radio", itemDefinition.item_id, String(value), String(value))).join("");
  return `<fieldset class="rating-row"><legend>${escapeHtml(itemDefinition.translations[state.language].text)}</legend><div class="scale">${options}${choice("radio", itemDefinition.item_id, "not_applicable", copy.notApplicable)}</div><div class="scale-hints"><span>${escapeHtml(anchors.low)}</span><span>${escapeHtml(anchors.high)}</span></div></fieldset>`;
}

function checkField(id, text) {
  return `<fieldset class="form-section"><legend>${escapeHtml(text)}</legend>${choice("checkbox", id, "yes", "✓")}</fieldset>`;
}

function choice(type, name, value, label) {
  const id = `${name}-${value}`;
  return `<label class="choice-label" for="${escapeHtml(id)}"><input id="${escapeHtml(id)}" type="${type}" name="${escapeHtml(name)}" value="${escapeHtml(value)}"><span>${escapeHtml(label)}</span></label>`;
}

function setStage(activeStage) {
  const order = ["intro", "setup", "trial", "complete"];
  const activeIndex = order.indexOf(activeStage);
  document.querySelectorAll(".stage-list li").forEach((element, index) => {
    element.classList.toggle("active", index === activeIndex);
    element.classList.toggle("done", index < activeIndex);
  });
}

function setProgress(done, total) {
  document.getElementById("progress-text").textContent = `${done} / ${total}`;
}

function item(itemId) {
  return state.questionnaire.items.find(itemDefinition => itemDefinition.item_id === itemId);
}

function showSetupError(message) {
  const element = document.getElementById("setup-error");
  element.textContent = message;
  element.hidden = false;
  announce(message);
}

function announce(message) {
  document.getElementById("live-region").textContent = message;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail?.code || value.detail || `HTTP ${response.status}`);
  return value;
}

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}[character]));
}

init();