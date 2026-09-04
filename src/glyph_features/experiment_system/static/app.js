"use strict";

const ui = {
  "zh-Hans": {
    language: "语言", gate: "真实收集已锁定", draft: "翻译草案 / 未经人工审核",
    stages: ["信息", "背景", "评价", "完成"], eyebrow: "跨文化视觉感知 / 工程验收",
    title: "在不泄漏文字身份的条件下评价视觉形式", boundary: "当前页面只生成 synthetic fixture。伦理、参与者与翻译门禁均未通过，无法收集或发布真人响应。",
    continue: "继续", setupTitle: "确认参与条件与文字经验", consent: "我理解当前为合成测试，并同意继续。",
    age: "我已达到最低参与年龄。", understood: "我能充分理解当前问卷语言。", scripts: "请选择你从小熟练使用的文字系统（可多选）",
    motherTongues: "母语（可多选）", dominantLanguage: "主导语言", proficiencyTitle: "各目标文字的熟练度", reading: "阅读", writing: "书写", exposure: "接触",
    backgroundTitle: "训练与粗粒度背景", designTraining: "设计训练", typographyTraining: "字体排印训练", calligraphyTraining: "书法训练", region: "居住地区类别", crossCulture: "跨文化接触", ageBand: "年龄段", education: "教育层级",
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
    motherTongues: "Mother tongues (multiple allowed)", dominantLanguage: "Dominant language", proficiencyTitle: "Target-script proficiency", reading: "Reading", writing: "Writing", exposure: "Exposure",
    backgroundTitle: "Training and coarse background", designTraining: "Design training", typographyTraining: "Typography training", calligraphyTraining: "Calligraphy training", region: "Region category", crossCulture: "Cross-cultural exposure", ageBand: "Age band", education: "Education level",
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
    motherTongues: "母語（複数選択可）", dominantLanguage: "主要言語", proficiencyTitle: "対象文字体系の習熟度", reading: "読む", writing: "書く", exposure: "接触",
    backgroundTitle: "訓練と大まかな背景", designTraining: "デザイン訓練", typographyTraining: "タイポグラフィ訓練", calligraphyTraining: "書道訓練", region: "居住地域区分", crossCulture: "異文化接触", ageBand: "年齢層", education: "教育段階",
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
    motherTongues: "모국어(복수 선택 가능)", dominantLanguage: "주 언어", proficiencyTitle: "대상 문자 숙련도", reading: "읽기", writing: "쓰기", exposure: "노출",
    backgroundTitle: "교육 및 대략적 배경", designTraining: "디자인 교육", typographyTraining: "타이포그래피 교육", calligraphyTraining: "서예 교육", region: "거주 지역 범주", crossCulture: "교차문화 노출", ageBand: "연령대", education: "교육 수준",
    attention: "주의력 확인: 원을 선택하십시오", start: "연습 및 평가 시작", practiceTitle: "평가 한 번 연습", practiceBody: "연습은 조작을 익히기 위한 것이며 저장되거나 분석되지 않습니다.", practiceContinue: "연습 완료 후 평가 시작", latin: "라틴", han: "한자", kana: "가나", hangul: "한글",
    circle: "원", square: "사각형", triangle: "삼각형", trial: "시각 평가", firstImpression: "첫인상에 따라 답하고 판단할 수 없으면 해당 없음을 선택하십시오.",
    submit: "제출하고 계속", notApplicable: "해당 없음", loadError: "자극의 무결성 검증에 실패하여 이 시행을 중단했습니다.", required: "필수 평가를 모두 완료하십시오.",
    completeTitle: "합성 흐름 완료", completeBody: "이 기록은 엔지니어링 확인 전용이며 공식 분석이나 release에 들어갈 수 없습니다.", restart: "새 합성 세션"
  }
};

const profileOptions = {
  "zh-Hans": {
    languages: [["zh-Hans", "简体中文"], ["en", "英语"], ["ja", "日语"], ["ko", "韩语"]],
    training: [["none", "无"], ["informal", "非正式"], ["formal", "正式"]],
    regions: [["east_asia", "东亚"], ["southeast_asia", "东南亚"], ["europe", "欧洲"], ["north_america", "北美"], ["south_america", "南美"], ["africa", "非洲"], ["oceania", "大洋洲"], ["west_central_asia", "西亚/中亚"], ["multiple", "多个地区"], ["prefer_not_to_say", "不愿回答"], ["other", "其他"]],
    exposure: [["low", "较少"], ["moderate", "中等"], ["high", "较多"], ["prefer_not_to_say", "不愿回答"]],
    ages: [["18_24", "18–24"], ["25_34", "25–34"], ["35_44", "35–44"], ["45_54", "45–54"], ["55_64", "55–64"], ["65_plus", "65+"], ["prefer_not_to_say", "不愿回答"]],
    education: [["secondary_or_less", "中学及以下"], ["vocational", "职业教育"], ["undergraduate", "本科"], ["postgraduate", "研究生"], ["prefer_not_to_say", "不愿回答"], ["other", "其他"]]
  },
  en: {
    languages: [["zh-Hans", "Chinese"], ["en", "English"], ["ja", "Japanese"], ["ko", "Korean"]],
    training: [["none", "None"], ["informal", "Informal"], ["formal", "Formal"]],
    regions: [["east_asia", "East Asia"], ["southeast_asia", "Southeast Asia"], ["europe", "Europe"], ["north_america", "North America"], ["south_america", "South America"], ["africa", "Africa"], ["oceania", "Oceania"], ["west_central_asia", "West/Central Asia"], ["multiple", "Multiple regions"], ["prefer_not_to_say", "Prefer not to say"], ["other", "Other"]],
    exposure: [["low", "Low"], ["moderate", "Moderate"], ["high", "High"], ["prefer_not_to_say", "Prefer not to say"]],
    ages: [["18_24", "18–24"], ["25_34", "25–34"], ["35_44", "35–44"], ["45_54", "45–54"], ["55_64", "55–64"], ["65_plus", "65+"], ["prefer_not_to_say", "Prefer not to say"]],
    education: [["secondary_or_less", "Secondary or less"], ["vocational", "Vocational"], ["undergraduate", "Undergraduate"], ["postgraduate", "Postgraduate"], ["prefer_not_to_say", "Prefer not to say"], ["other", "Other"]]
  },
  ja: {
    languages: [["zh-Hans", "中国語"], ["en", "英語"], ["ja", "日本語"], ["ko", "韓国語"]],
    training: [["none", "なし"], ["informal", "非正式"], ["formal", "正式"]],
    regions: [["east_asia", "東アジア"], ["southeast_asia", "東南アジア"], ["europe", "ヨーロッパ"], ["north_america", "北米"], ["south_america", "南米"], ["africa", "アフリカ"], ["oceania", "オセアニア"], ["west_central_asia", "西・中央アジア"], ["multiple", "複数地域"], ["prefer_not_to_say", "回答しない"], ["other", "その他"]],
    exposure: [["low", "少ない"], ["moderate", "中程度"], ["high", "多い"], ["prefer_not_to_say", "回答しない"]],
    ages: [["18_24", "18–24"], ["25_34", "25–34"], ["35_44", "35–44"], ["45_54", "45–54"], ["55_64", "55–64"], ["65_plus", "65+"], ["prefer_not_to_say", "回答しない"]],
    education: [["secondary_or_less", "中等教育以下"], ["vocational", "職業教育"], ["undergraduate", "学部"], ["postgraduate", "大学院"], ["prefer_not_to_say", "回答しない"], ["other", "その他"]]
  },
  ko: {
    languages: [["zh-Hans", "중국어"], ["en", "영어"], ["ja", "일본어"], ["ko", "한국어"]],
    training: [["none", "없음"], ["informal", "비공식"], ["formal", "정규"]],
    regions: [["east_asia", "동아시아"], ["southeast_asia", "동남아시아"], ["europe", "유럽"], ["north_america", "북미"], ["south_america", "남미"], ["africa", "아프리카"], ["oceania", "오세아니아"], ["west_central_asia", "서/중앙아시아"], ["multiple", "여러 지역"], ["prefer_not_to_say", "응답하지 않음"], ["other", "기타"]],
    exposure: [["low", "낮음"], ["moderate", "보통"], ["high", "높음"], ["prefer_not_to_say", "응답하지 않음"]],
    ages: [["18_24", "18–24"], ["25_34", "25–34"], ["35_44", "35–44"], ["45_54", "45–54"], ["55_64", "55–64"], ["65_plus", "65+"], ["prefer_not_to_say", "응답하지 않음"]],
    education: [["secondary_or_less", "중등 이하"], ["vocational", "직업 교육"], ["undergraduate", "학부"], ["postgraduate", "대학원"], ["prefer_not_to_say", "응답하지 않음"], ["other", "기타"]]
  }
};

const state = {
  language: localStorage.getItem("glyph_task03_language") || "zh-Hans",
  status: null,
  questionnaire: null,
  assignment: null,
  profile: null,
  consent: null,
  nativeScripts: [],
  attentionResponse: null,
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
  if (state.assignment) {
    languageSelect.value = state.language;
    return;
  }
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
    if (participantId) {
      const response = await fetch(`/api/session/${encodeURIComponent(participantId)}`);
      if (response.ok) {
        state.assignment = await response.json();
        state.profile = state.assignment.profile;
        state.consent = state.assignment.consent;
        state.nativeScripts = state.profile.native_scripts;
        state.attentionResponse = localStorage.getItem("glyph_task03_attention");
        state.language = state.profile.questionnaire_language;
        localStorage.setItem("glyph_task03_language", state.language);
        languageSelect.value = state.language;
        document.documentElement.lang = state.language;
        applyChrome();
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
  const options = profileOptions[state.language];
  app.innerHTML = `
    <p class="eyebrow">02 / ${escapeHtml(copy.stages[1])}</p>
    <h2>${escapeHtml(copy.setupTitle)}</h2>
    ${checkField("consent", copy.consent)}
    ${checkField("age", copy.age)}
    ${checkField("understood", copy.understood)}
    <fieldset class="form-section"><legend>${escapeHtml(copy.motherTongues)}</legend><div class="choice-grid">
      ${options.languages.map(([value, label]) => choice("checkbox", "mother-tongue", value, label, value === state.language)).join("")}
    </div>${selectField("dominant-language", copy.dominantLanguage, options.languages, state.language)}</fieldset>
    <fieldset class="form-section"><legend>${escapeHtml(copy.scripts)}</legend><div class="choice-grid">
      ${["latin", "han", "kana", "hangul"].map(script => choice("checkbox", "script", script, copy[script])).join("")}
    </div></fieldset>
    <fieldset class="form-section"><legend>${escapeHtml(copy.proficiencyTitle)}</legend><div class="proficiency-grid">
      ${["latin", "han", "kana", "hangul"].map(script => proficiencyRow(script, copy)).join("")}
    </div></fieldset>
    <fieldset class="form-section"><legend>${escapeHtml(copy.backgroundTitle)}</legend><div class="select-grid">
      ${selectField("training-design", copy.designTraining, options.training, "none")}
      ${selectField("training-typography", copy.typographyTraining, options.training, "none")}
      ${selectField("training-calligraphy", copy.calligraphyTraining, options.training, "none")}
      ${selectField("region-category", copy.region, options.regions, "prefer_not_to_say")}
      ${selectField("cross-cultural-exposure", copy.crossCulture, options.exposure, "moderate")}
      ${selectField("age-band", copy.ageBand, options.ages, "prefer_not_to_say")}
      ${selectField("education-level", copy.education, options.education, "prefer_not_to_say")}
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
  const motherTongues = [...document.querySelectorAll('input[name="mother-tongue"]:checked')].map(input => input.value);
  const dominantLanguage = document.getElementById("dominant-language").value;
  const attention = document.querySelector('input[name="attention"]:checked')?.value;
  const required = ["consent-yes", "age-yes", "understood-yes"].every(id => document.getElementById(id).checked);
  if (!required || !scripts.length || !motherTongues.includes(dominantLanguage) || !attention) {
    showSetupError(copy.required);
    return;
  }
  state.nativeScripts = scripts;
  state.profile = {
    mother_tongues: motherTongues.map(bcp47 => ({bcp47, dominance: bcp47 === dominantLanguage ? "primary" : "additional"})),
    native_scripts: scripts,
    script_proficiencies: ["latin", "han", "kana", "hangul"].map(script => ({
      script,
      reading: Number(document.getElementById(`proficiency-reading-${script}`).value),
      writing: Number(document.getElementById(`proficiency-writing-${script}`).value),
      exposure_frequency: Number(document.getElementById(`proficiency-exposure-${script}`).value)
    })),
    region_category: document.getElementById("region-category").value,
    cross_cultural_exposure: document.getElementById("cross-cultural-exposure").value,
    training: {
      design: document.getElementById("training-design").value,
      typography: document.getElementById("training-typography").value,
      calligraphy: document.getElementById("training-calligraphy").value
    },
    age_band: document.getElementById("age-band").value,
    education_level: document.getElementById("education-level").value,
    language_understood: true
  };
  state.consent = {consent_version: state.status.protocol_version, status: "consented", age_eligible: true};
  state.attentionResponse = attention;
  localStorage.setItem("glyph_task03_attention", attention);
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
      body: JSON.stringify({language: state.language, session_nonce: nonce, profile: state.profile, consent: state.consent})
    });
    localStorage.setItem("glyph_task03_participant", state.assignment.participant_id);
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
  const zoomAnomaly = Boolean(window.visualViewport && Math.abs(window.visualViewport.scale - 1) > 0.05);
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
    focus_loss_count: state.focusLosses, zoom_anomaly: zoomAnomaly,
    attention_response: state.attentionResponse
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
    ["glyph_task03_participant", "glyph_task03_nonce", "glyph_task03_attention"].forEach(key => localStorage.removeItem(key));
    state.assignment = null;
    state.profile = null;
    state.consent = null;
    state.nativeScripts = [];
    state.attentionResponse = null;
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

function proficiencyRow(script, copy) {
  const scale = Array.from({length: 7}, (_, index) => [String(index + 1), String(index + 1)]);
  return `<div class="proficiency-row"><b>${escapeHtml(copy[script])}</b>${selectField(`proficiency-reading-${script}`, copy.reading, scale, "4")}${selectField(`proficiency-writing-${script}`, copy.writing, scale, "4")}${selectField(`proficiency-exposure-${script}`, copy.exposure, scale, "4")}</div>`;
}

function selectField(id, label, options, selected) {
  const optionMarkup = options.map(([value, text]) => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(text)}</option>`).join("");
  return `<label class="select-field" for="${escapeHtml(id)}"><span>${escapeHtml(label)}</span><select id="${escapeHtml(id)}" name="${escapeHtml(id)}">${optionMarkup}</select></label>`;
}

function choice(type, name, value, label, checked = false) {
  const id = `${name}-${value}`;
  return `<label class="choice-label" for="${escapeHtml(id)}"><input id="${escapeHtml(id)}" type="${type}" name="${escapeHtml(name)}" value="${escapeHtml(value)}"${checked ? " checked" : ""}><span>${escapeHtml(label)}</span></label>`;
}

function setStage(activeStage) {
  languageSelect.disabled = Boolean(state.assignment);
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