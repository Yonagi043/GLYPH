const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(`${__dirname}/../src/glyph_features/workbench/static/app.js`, 'utf8');

function formFor(ids) {
  const fields = Object.fromEntries(['name', 'question', 'explanations', 'questionnaire_language', 'wording', 'repetitions', 'selection_scope', 'stopping_rule', 'executor_agent', 'reference_run_id', 'task_size', 'design_rationale', 'predictions', 'parent_assessment_id'].map((key) => [key, {value: `default-${key}`} ]));
  const groups = {roles: ['baseline', 'zh', 'en', 'ja'].map((value) => ({value, checked: ['baseline', 'zh'].includes(value)})), orders: ['forward', 'reverse'].map((value) => ({value, checked: true})), bridge_modes: ['aesthetic_only', 'premium_only', 'aesthetic_premium', 'premium_aesthetic'].map((value) => ({value, checked: true}))};
  const rows = ids.map((materialId) => {
    const controls = {representation: {value: 'standardized'}, reason: {value: 'default'}, foreground: {value: 'unconfirmed'}, foreground_note: {value: ''}, color_mode: {value: 'native'}, max_edge: {value: '1280'}, ...Object.fromEntries(['left', 'top', 'right', 'bottom'].map((edge) => [`crop_${edge}`, {value: ''}]))};
    return {dataset: {studySelection: materialId}, querySelector: (selector) => controls[selector.match(/name='([^']+)'/)[1]]};
  });
  return {fields, rows, groups,
    querySelector: (selector) => selector.startsWith('[data-study-selection') ? rows.find((row) => selector.includes(row.dataset.studySelection)) : fields[selector.match(/name='([^']+)'/)[1]],
    querySelectorAll: (selector) => selector === '[data-study-selection]' ? rows : groups[selector.match(/name='([^']+)'/)[1]],
  };
}

test('navigation preserves edited conditions and retained crop; clone and blank bypass old form', async () => {
  let form = formFor(['paris', 'removed']);
  const root = {setAttribute() {}, set innerHTML(value) {form = value.includes('research-content') ? formFor([...context.state.selectedMaterials]) : null;}};
  const context = {state: {draftConfig: null, selectedMaterials: new Set(['paris', 'removed']), cache: new Map()}, labels: {assets: ['assets'], research: ['research']}, document: {
    querySelector: (selector) => selector === '#study-form' ? form : selector === '#app' ? root : {}, querySelectorAll: () => [],
  }, closeInspector() {}, closeMenu() {}, loadBase: async () => {}, request: async () => ({}), renderMaterials: () => 'assets-content', renderResearch: () => 'research-content', bindFilters() {}, escapeHtml: String};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function captureStudyDraft()'), source.indexOf('function wpCards(')) + source.slice(source.indexOf('async function navigate('), source.indexOf('function invalidate()')), context);
  form.fields.name.value = 'edited-name';
  form.fields.repetitions.value = '3';
  form.fields.explanations.value = 'first\n\nsecond';
  form.fields.predictions.value = 'opposing predictions\nretain counterexamples';
  form.fields.task_size.value = '4';
  form.groups.roles.forEach((field) => {field.checked = field.value !== 'zh';});
  form.groups.bridge_modes.forEach((field) => {field.checked = !field.value.endsWith('_only');});
  form.rows[0].querySelector("[name='representation']").value = 'original';
  form.rows[0].querySelector("[name='foreground']").value = 'dark';
  form.rows[0].querySelector("[name='foreground_note']").value = 'fixture observation';
  form.rows[0].querySelector("[name='color_mode']").value = 'grayscale';
  form.rows[0].querySelector("[name='max_edge']").value = '1024';
  ['0', '0', '1140', '740'].forEach((value, index) => {form.rows[0].querySelector(`[name='crop_${['left', 'top', 'right', 'bottom'][index]}']`).value = value;});
  const expectedFields = JSON.parse(JSON.stringify(form.fields));
  await context.navigate('assets');
  context.state.selectedMaterials = new Set(['paris', 'added']);
  await context.navigate('research');
  assert.deepEqual(form.fields, expectedFields);
  assert.deepEqual(form.groups.roles.filter((field) => field.checked).map((field) => field.value), ['baseline', 'en', 'ja']);
  assert.deepEqual(form.groups.bridge_modes.filter((field) => field.checked).map((field) => field.value), ['aesthetic_premium', 'premium_aesthetic']);
  assert.equal(form.rows[0].querySelector("[name='crop_right']").value, '1140');
  assert.equal(form.rows[0].querySelector("[name='representation']").value, 'original');
  assert.equal(form.rows[0].querySelector("[name='foreground']").value, 'dark');
  assert.equal(form.rows[0].querySelector("[name='foreground_note']").value, 'fixture observation');
  assert.equal(form.rows[0].querySelector("[name='color_mode']").value, 'grayscale');
  assert.equal(form.rows[0].querySelector("[name='max_edge']").value, '1024');
  assert.equal(form.rows[1].querySelector("[name='max_edge']").value, '1280');
  assert.equal(form.rows[1].querySelector("[name='representation']").value, 'standardized');
  await context.navigate('assets');
  await context.navigate('research');
  assert.deepEqual(form.fields, expectedFields);
  context.state.draftConfig.name = 'another-clone';
  await context.navigate('research', true, false);
  assert.equal(form.fields.name.value, 'another-clone');
  context.state.draftConfig = null;
  context.state.selectedMaterials = new Set();
  await context.navigate('research', true, false);
  assert.equal(form.fields.name.value, 'default-name');
  assert.equal(form.rows.length, 0);
});

test('new UI submissions retain prior contract as provenance, not a current frozen protocol', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function submittedDesignContract('), source.indexOf('function captureStudyDraft(')), context);
  const previous = {protocol: 'AB02-fixture', repeat_selection: 'old fixed items', board_mapping: {fixture: {positive_label: 'A'}}};
  const updated = context.submittedDesignContract({design_contract: previous});
  assert.equal(updated.protocol, undefined);
  assert.equal(updated.status, 'exploratory_ui_revision');
  assert.equal(updated.inherited_contract, previous);
  assert.equal(updated.inherited_contract_status, 'provenance_only_not_current_protocol');
  assert.equal(updated.board_mapping, previous.board_mapping);
  assert.ok(updated.board_mapping_scope.includes('not a frozen hypothesis'));
  assert.equal(previous.protocol, 'AB02-fixture');
  assert.equal(context.submittedDesignContract({design_contract: updated}).inherited_contract, previous);
  assert.equal(context.submittedDesignContract(null).primary_outcome, 'aesthetic');
  assert.ok(source.includes('config.design_contract = submittedDesignContract(state.draftConfig);'));
});

test('research overview shows coverage, zero differences, input provenance and source boundaries', () => {
  const context = {escapeHtml: String, badge: String, emptyRow: () => ''};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function researchNumber('), source.indexOf('async function showStudy(')), context);
  const record = {selection: {material_id: 'fixture', representation: 'original', crop_box: [0, 0, 100, 80]}, material: {source: {notes: '{"work_id":"fixture-work"}'}}, input_path: '/fixture'};
  const run = {run_id: 'current', config: {question: 'Fixture question', roles: ['baseline']}, snapshot: {materials: [record], reference_run: {config: {name: 'reference'}, snapshot: {materials: [record]}}}};
  const result = {actual_calls: 1, planned_tasks: 2, rows: [{task_id: 'valid', aesthetic: 0}], identity_differences: [], repeat_differences: [{material_id: 'fixture', difference: 0}], order_and_call_differences: [], representation_comparison: {reference_run_id: 'reference', pairs: [{material_id: 'fixture', difference: -1}], reference_actual_calls: 1, reference_planned_tasks: 2}, tasks_and_raw_returns: [{task_id: 'valid', condition: {role: 'baseline', order: 'forward', repetition: 0}, status: 'completed', attempts: [{}]}], four_line_evidence: {specific_sources: {entries: []}}, materials: [{material_id: 'fixture', title: 'Fixture title', median_aesthetic: 5, range_aesthetic: [5, 5], observed_aesthetic: 1, planned_observations: 2, missing_or_unexecuted: 1}]};
  const html = context.renderStudyOverview(run, result);
  assert.ok(html.includes('/api/research/current/inputs/fixture'));
  assert.ok(html.includes('/api/research/reference/inputs/fixture'));
  assert.ok(html.includes('0 至 0（1 配对）'));
  assert.ok(html.includes('-1 至 -1（1 配对）'));
  assert.ok(html.includes('缺失或未执行 1'));
  assert.ok(html.includes('后面的通用文献仅作背景'));
  assert.equal(context.researchNumber(null), 'NA');
  assert.ok(html.includes('逐对表示差值：-1'));
  run.snapshot.materials.push(record, {...record, material: {source: {notes: null}}});
  const grouped = context.renderStudyOverview(run, result);
  assert.ok(grouped.includes('登记作品组 1 · 未登记作品的输入 1 · 本运行输入 3'));
  result.tasks_and_raw_returns[0].inputs = [{material_id: 'fixture'}];
  assert.ok(context.renderStudyOverview(run, result).includes('<td>1 / 1</td>'));
  run.snapshot.materials[2].material.work_id = 'direct-work';
  assert.ok(context.renderStudyOverview(run, result).includes('登记作品组 2 · 未登记作品的输入 0'));
  run.config.explanations = ['Fixture hypothesis'];
  result.research_assessments = [{assessment_id: 'assessment-fixture', conclusion: 'Counterexample retained', explanation_updates: [{explanation: 'Fixture hypothesis', judgment: 'not_supported', evidence: 'One opposing pair', material_ids: ['fixture']}], remaining_confounds: ['Call variation'], next_question: 'Different comparison?', next_comparison: 'Matched text regions', basis_result_sha256: 'basis-fixture'}];
  const assessmentHtml = context.renderResearchJudgments(run, result);
  assert.ok(assessmentHtml.includes('Counterexample retained'));
  assert.ok(assessmentHtml.includes('data-continue-assessment="assessment-fixture"'));
  assert.ok(assessmentHtml.includes('basis-fixture'));
  result.rows = [{task_id: 'valid', aesthetic: null, preference_choice: 'tie'}];
  const choiceOverview = context.renderStudyOverview(run, result);
  assert.ok(choiceOverview.includes('回答条目 1'));
  assert.ok(choiceOverview.includes('<td>1 / 1</td>'));
});

test('paired choices retain ties and uncollected weight checks', () => {
  const context = {escapeHtml: String};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function renderPairedChoices('), source.indexOf('async function showStudy(')), context);
  assert.equal(context.renderPairedChoices({}), '');
  const html = context.renderPairedChoices({paired_choices: [{material_id: 'fixture', content: 'Example', contrast: 'w900-w400', positive_label: 'B', preference_choice: 'tie'}]});
  assert.ok(html.includes('Example'));
  assert.ok(html.includes('900 / 400'));
  assert.ok(html.includes('<td>B</td><td>持平</td><td>未采集</td>'));
  assert.ok(html.includes('数字美观未采集'));
  assert.ok(source.includes('value="aesthetic_pair_only"'));
  assert.ok(source.includes('value="aesthetic_pair"'));
});