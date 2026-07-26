// SimAgent reasoning notebook.
//
// A math problem goes in as text (or a bundled problem id); an embodied agent
// session runs server-side; this page streams the mind trace as notebook
// cells — thought, act, the rendered scene, the harness's equation translation
// of that scene, and a diff vs the previous step. Clicking a cell's image
// opens the interactive 3D scene (three.js) for that exact step. The page
// renders kernel state only; it never mints verdicts.
import * as THREE from 'three';
import { OrbitControls } from '/static/OrbitControls.js';

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ---------------------------------------------------------------- notebook --
const nb = {
  run: null,        // run currently displayed
  total: 0,         // highest step rendered
  lanes: [],        // one entry per distinct configuration, for the combined view
  done: false,
  job: false,       // true when this page started the session (status endpoint exists)
  tracePoll: null,
  statusPoll: null,
  commentTarget: null,
};

function stopPolling() {
  if (nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
  if (nb.statusPoll) { clearInterval(nb.statusPoll); nb.statusPoll = null; }
}

function resetNotebook() {
  stopPolling();
  nb.run = null; nb.total = 0; nb.done = false; nb.job = false;
  nb.approach = null; nb.approachIdea = null; nb.finishSummary = null;
  nb.lanes = [];
  $('cells').replaceChildren();
  $('progressionWrap')?.remove(); // lives outside #cells, so clear it by hand
  $('statementWrap').style.display = 'none';
  $('verdictWrap').style.display = 'none';
  $('statusWrap').style.display = 'none';
  $('btnStop').disabled = true;
  closeComment();
  if (ov?.open) close3d();
}

function nearBottom() {
  return window.innerHeight + window.scrollY > document.body.offsetHeight - 260;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function showStatement(spec) {
  if (!spec) return;
  const s = $('statement');
  s.replaceChildren();
  s.appendChild(el('h2', null, spec.title ?? spec.id ?? ''));
  if (spec.conjecture) s.appendChild(el('div', 'conj', spec.conjecture));
  if (spec.latex) s.appendChild(el('div', 'latex mono', spec.latex));
  if (spec.quantifier) s.appendChild(el('div', 'conj mono', `quantifier: ${spec.quantifier}`));
  s.style.display = 'block';
  $('statementWrap').style.display = 'block';
}

function markCommentTarget(node, target) {
  node.classList.add('commentable');
  node.dataset.commentTarget = JSON.stringify(target);
  node.title = 'select text or double-click to comment';
  node.addEventListener('dblclick', (event) => {
    event.stopPropagation();
    openComment(target);
  });
  return node;
}

function thoughtBlock(step) {
  const t = el('div', 'thought');
  const parts = [...(step.thought ?? [])];
  if (step.tool === 'finish' && step.args?.summary) {
    parts.push({ kind: 'summary', text: step.args.summary });
  }
  if (!parts.length) return null;
  parts.forEach((p, index) => {
    t.appendChild(el('span', 'kind', p.kind === 'thinking' ? 'thinking' : p.kind === 'summary' ? 'final summary (narrative)' : 'says'));
    t.appendChild(markCommentTarget(
      el('span', p.kind === 'thinking' ? 'think' : 'say', p.text),
      { step: step.step, kind: 'thought', index, thought_kind: p.kind },
    ));
  });
  return t;
}

function actLine(step) {
  const a = markCommentTarget(el('div', 'act mono'), { step: step.step, kind: 'act' });
  let argsText = '';
  if (step.tool === 'finish') argsText = '';
  else if (step.args && Object.keys(step.args).length) argsText = JSON.stringify(step.args);
  a.appendChild(el('span', null, step.tool ? `${step.tool}(${argsText})` : '— narrative only —'));
  if (step.error) a.appendChild(el('span', 'err', '  ✗ error'));
  for (const [k, v] of Object.entries(step.extra ?? {})) {
    if (['view', 'expect', 'resolved_expectations', 'construct'].includes(k)) continue; // rendered as chips/badges in Out
    a.appendChild(el('span', 'badge', `  ${k}=${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`));
  }
  return a;
}

function equationBlock(step) {
  const lines = step.equation?.text ?? [];
  if (!lines.length) return null;
  const box = el('div', 'eq mono');
  lines.forEach((line, index) => {
    box.appendChild(markCommentTarget(
      el('div', 'eqline', line),
      { step: step.step, kind: 'equation', index },
    ));
  });
  return box;
}

function cellActions(cell, step) {
  const actions = el('div', 'cellactions');
  const comment = el('button', 'mini', 'comment');
  comment.onclick = () => openComment({ step: step.step, kind: 'cell' });
  const branch = el('button', 'mini', 'branch');
  branch.textContent = 'branch from here';
  branch.title = 'stop this lane, replay this exact prefix, and continue in a new pi session';
  branch.onclick = () => branchFromTarget({ step: step.step, kind: 'cell' });
  actions.append(comment, branch);
  cell.appendChild(actions);
}

function diffBlock(step) {
  const lines = [];
  for (const c of step.diff?.changed ?? []) {
    const where = c.row === null || c.row === undefined ? c.var : `${c.var}[${c.row}]`;
    lines.push(['del', `- ${where} = ${c.before ?? '(new)'}`]);
    lines.push(['add', `+ ${where} = ${c.after}`]);
  }
  const m = step.diff?.margin;
  if (m && m.before !== m.after && (m.before !== null || m.after !== null)) {
    const f = (x) => (x === null || x === undefined ? '—' : Number(x).toFixed(4));
    lines.push([m.after !== null && m.after > 0 ? 'add' : 'del', `~ margin ${f(m.before)} → ${f(m.after)}`]);
  }
  if (!lines.length) return null;
  const d = el('div', 'diffblock mono');
  for (const [cls, text] of lines) d.appendChild(el('div', cls, text));
  return d;
}

function statBadge(check) {
  if (!check) return null;
  if (check.error) return el('span', 'stat dim', `degenerate — ${check.error}`);
  const m = check.margin;
  const b = el('span', `stat ${check.holds ? 'good' : 'bad'}`,
    `${check.holds ? 'PROPERTY HOLDS' : 'PROPERTY FAILS'}${m === null || m === undefined ? '' : ` · margin ${m >= 0 ? '+' : ''}${Number(m).toFixed(4)}`}`);
  return b;
}

function imagineCell(step) {
  // Thought experiment: dashed cell, ghost image, per-op outcomes — and an
  // explicit "mainline unchanged" note. The Einstein move, visible.
  const cell = el('article', 'cell imagine');
  cell.appendChild(el('div', 'gut im', `Im [${step.step}]:`));
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);
  const inner = el('div');
  inner.appendChild(el('div', 'imnote', 'thought experiment — the real configuration is unchanged'));
  const ops = step.branch?.ops ?? step.args?.ops ?? [];
  const act = markCommentTarget(
    el('div', 'act mono'),
    { step: step.step, kind: 'act' },
  );
  act.textContent = `imagine(${ops.map((o) => `${o.op} ${o.target ?? o.name ?? ''}`).join(' · ')})`;
  inner.appendChild(act);
  if (step.image) {
    const img = el('img', 'sceneimg');
    img.loading = 'lazy';
    img.alt = `imagined scene at step ${step.step}`;
    img.src = `/api/trace/${encodeURIComponent(nb.run)}/file/${step.image}`;
    img.onerror = () => img.remove();
    if (Array.isArray(step.scene) && step.scene.length) img.onclick = () => open3d(step);
    inner.appendChild(img);
    inner.appendChild(el('div', 'caption', 'ghost view: grey = real state · solid = imagined'));
  }
  for (const oc of step.branch?.outcomes ?? []) {
    const line = el('div', 'imoutcome mono');
    if (oc.error) {
      line.appendChild(el('span', 'bad', `op ${oc.op}: ${oc.error}`));
    } else if (oc.check?.error) {
      line.appendChild(el('span', 'bad', `op ${oc.op}: degenerate — ${oc.check.error}`));
    } else {
      const m = oc.check?.margin;
      const holds = oc.check?.holds;
      const span = el('span', holds ? 'good' : 'bad',
        `op ${oc.op}: would ${holds ? 'HOLD' : 'FAIL'}${m === null || m === undefined ? '' : ` (margin ${Number(m).toFixed(4)})`}`);
      line.appendChild(span);
    }
    inner.appendChild(line);
  }
  const equations = equationBlock(step);
  if (equations) inner.appendChild(equations);
  body.appendChild(inner);
  cell.appendChild(body);
  cellActions(cell, step);
  $('cells').appendChild(cell);
  return cell;
}

function annotationCell(step) {
  // plan/expect ride tool steps; free annotations (user_comment, provenance)
  // land here — rendered like an approach box, tagged with their kind.
  const cell = el('article', 'cell');
  cell.appendChild(el('div', 'gut', `— [${step.step}]`));
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);
  const box = el('div', 'planbox');
  const label = step.kind === 'user_comment'
    ? 'comment (steering only, never verdict material)'
    : step.kind === 'provenance' ? 'branch provenance' : (step.kind ?? 'annotation');
  box.appendChild(el('div', 'pm', label));
  if (step.text) box.appendChild(el('div', 'pi', step.text));
  if (step.target) box.appendChild(el('div', 'pi', `on: ${JSON.stringify(step.target)}`));
  if (step.source) {
    const source = step.source;
    box.appendChild(el('span', 'chip pending',
      `forked from ${source.run} step ${source.step} · ${String(source.stateHash ?? '').slice(0, 10)}`));
  }
  body.appendChild(box);
  cell.appendChild(body);
  cellActions(cell, step);
  $('cells').appendChild(cell);
  return cell;
}

// Keep one lane per state the configuration actually reached. A run has many
// steps that do not move anything (look, measure, view), and drawing those
// again would stack identical geometry and make the progression unreadable.
function recordLane(step) {
  if (!Array.isArray(step.scene) || !step.scene.length) return;
  const key = JSON.stringify(step.scene);
  if (nb.lanes.length && nb.lanes[nb.lanes.length - 1].key === key) return;
  nb.lanes.push({ step: step.step, tool: step.tool, check: step.check, key, scene: step.scene });
}

function appendStep(step) {
  if (step.mode === 'imagine') return imagineCell(step);
  if (step.mode === 'annotation') return annotationCell(step);
  recordLane(step);
  const cell = el('article', 'cell');
  const gut = el('div', 'gut in', `In [${step.step}]:`);
  cell.appendChild(gut);
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);

  // A declared line of attack renders as its own approach cell — intent,
  // clearly distinct from the acts. The kernel still stamps the verdict.
  if (step.tool === 'plan') {
    const box = el('div', 'planbox');
    if (step.error) {
      box.appendChild(el('div', 'pm', 'approach — (invalid declaration)'));
      box.appendChild(el('div', 'perr', step.result ?? '✗ error'));
    } else {
      nb.approach = step.extra?.declared_method ?? step.args?.method ?? null;
      nb.approachIdea = step.extra?.idea ?? step.args?.idea ?? null;
      box.appendChild(el('div', 'pm', `approach — ${nb.approach}`));
      if (nb.approachIdea) box.appendChild(el('div', 'pi', nb.approachIdea));
    }
    body.appendChild(box);
    cell.appendChild(body);
    cellActions(cell, step);
    $('cells').appendChild(cell);
    return cell;
  }

  body.appendChild(actLine(step));

  const out = el('div', 'outblock');
  // FUTURE band: declared predictions (pending) and their mechanical scoring
  const exp = step.extra?.expect;
  if (exp) {
    out.appendChild(el('span', 'chip pending',
      `◌ expects margin ${exp.relation} ${exp.value ?? ''}${exp.note ? ` — ${exp.note}` : ''}`));
  }
  const resolved = step.extra?.resolved_expectations;
  if (resolved?.length) {
    const box = el('div');
    for (const r of resolved) {
      box.appendChild(el('span', `chip ${r.ok ? 'ok' : 'bad'}`,
        `${r.ok ? '✓' : '✗'} #${r.id} margin ${r.relation} ${r.value ?? ''} → ${r.actual}`));
    }
    out.appendChild(box);
  }
  const built = step.extra?.construct;
  if (built) {
    out.appendChild(el('span', 'chip pending',
      `✎ ${built.name} = ${built.ctor}(${(built.args ?? []).join(', ')})${built.degenerate ? ' — degenerate here' : ''}`));
  }
  const vmeta = step.extra?.view;
  if (vmeta) {
    const b = el('div');
    b.appendChild(el('span', 'viewbadge', `view: ${vmeta.kind}`));
    const bits = [];
    if (vmeta.zero_contour) bits.push('zero-contour visible — the boundary has a shape');
    if (vmeta.fail_fraction !== undefined) bits.push(`FAILS on ${(vmeta.fail_fraction * 100).toFixed(0)}% of the slice`);
    if (vmeta.min_margin !== undefined) bits.push(`min margin ${Number(vmeta.min_margin).toFixed(4)}`);
    if (vmeta.zero_crossings?.length) bits.push(`${vmeta.zero_crossings.length} zero crossing(s)`);
    if (vmeta.final_margin !== undefined) bits.push(`final margin ${Number(vmeta.final_margin).toFixed(4)}`);
    if (bits.length) b.appendChild(el('span', 'caption', '  ' + bits.join(' · ')));
    out.appendChild(b);
  }
  const hasScene = Array.isArray(step.scene) && step.scene.length;
  if (step.tool) {
    const img = el('img', 'sceneimg');
    img.loading = 'lazy';
    img.alt = `scene at step ${step.step}`;
    img.src = step.image
      ? `/api/trace/${encodeURIComponent(nb.run)}/file/${step.image}`
      : `/api/trace/${encodeURIComponent(nb.run)}/render/${step.step}`;
    img.onerror = () => { img.remove(); cap.remove(); };
    const cap = el('div', 'caption',
      step.image ? 'what the agent saw (its own eyes) — click for interactive 3D'
                 : 'scene after this step — click for interactive 3D');
    if (hasScene) img.onclick = () => open3d(step);
    out.appendChild(img);
    out.appendChild(cap);
  }
  const equations = equationBlock(step);
  if (equations) out.appendChild(equations);
  const df = diffBlock(step);
  if (df) out.appendChild(df);
  const st = statBadge(step.check);
  if (st) out.appendChild(st);
  if (out.children.length) {
    const og = el('div', 'gut out', `Out[${step.step}]:`);
    // nested output block; its gutter label reaches back into the left column
    const outCell = el('div', 'cell');
    outCell.style.margin = '8px 0 0';
    outCell.style.paddingLeft = '0';
    og.style.top = '0';
    og.style.left = '-86px';
    outCell.appendChild(og);
    outCell.appendChild(out);
    body.appendChild(outCell);
  }
  cell.appendChild(body);
  cellActions(cell, step);
  $('cells').appendChild(cell);
  return cell;
}

function showVerdict(tr, finishSummary) {
  const v = $('verdict');
  v.replaceChildren();
  v.className = '';
  let cls = 'none';
  if (tr.proof) {
    const text = tr.verdict ?? tr.proof.claim ?? 'kernel-grade result on record';
    if (/DISPROVED|counterexample/i.test(text)) cls = 'bad';
    else if (/PROVED|witness/i.test(text)) cls = 'good';
    v.appendChild(el('h2', null, 'Kernel verdict'));
    v.appendChild(el('div', 'vd', text));
    v.appendChild(el('div', 'meta',
      `method: ${tr.proof.method} · verified by ${tr.proof.verified_by}`
      + (tr.proof.statement_review && tr.proof.statement_review !== 'bundled-trusted'
        ? ` · statement review: ${tr.proof.statement_review}` : '')));
  } else {
    v.appendChild(el('h2', null, 'No kernel-grade result'));
    v.appendChild(el('div', 'meta',
      'Nothing was certified or kernel-checked in this session. The narrative above is not a proof.'));
    if (finishSummary) v.appendChild(el('div', 'meta', `agent's own summary: ${finishSummary}`));
  }
  // Declared intent vs what the kernel actually stamped — divergence is
  // honest information (the plan failed; the machinery caught something else).
  if (nb.approach) {
    const est = tr.proof?.method;
    v.appendChild(el('div', 'meta',
      !est ? `declared approach: ${nb.approach} (nothing kernel-established)`
        : est === nb.approach ? `declared and established: ${est}`
        : `declared: ${nb.approach} → established: ${est}`));
  }
  v.classList.add(cls === 'bad' ? 'bad' : cls === 'none' ? 'none' : 'good');
  v.style.display = 'block';
  $('verdictWrap').style.display = 'block';
  progressionCell();
}

function setStatus(text, logLines) {
  $('statusWrap').style.display = 'block';
  $('statusText').textContent = text + (nb.approach ? ` · approach: ${nb.approach}` : '');
  $('logTail').textContent = (logLines ?? []).slice(-6).join('\n');
}

function hideStatus() { $('statusWrap').style.display = 'none'; }

async function pullTrace() {
  const tr = await api(`/api/trace/${encodeURIComponent(nb.run)}?after=${nb.total}`);
  if (tr.spec && $('statementWrap').style.display === 'none') showStatement(tr.spec);
  let last = null;
  for (const s of tr.steps) {
    const cell = appendStep(s);
    nb.total = Math.max(nb.total, s.step);
    if (s.tool === 'finish' && s.args?.summary) nb.finishSummary = s.args.summary;
    last = cell;
  }
  if (last && nearBottom()) last.scrollIntoView({ block: 'end', behavior: 'smooth' });
  if (tr.done && !nb.done) {
    nb.done = true;
    if (nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
    hideStatus();
    showVerdict(tr, nb.finishSummary);
  }
  return tr;
}

async function openRun(run) {
  resetNotebook();
  nb.run = run;
  history.replaceState(null, '', `?run=${encodeURIComponent(run)}`);
  try {
    await pullTrace();
  } catch (e) {
    setStatus(`could not open ${run}: ${e.message}`);
    return;
  }
  if (!nb.done) {
    setStatus('agent is thinking… (following the live trace)');
    $('statusGut').textContent = '⋯';
    nb.tracePoll = setInterval(() => pullTrace().catch(() => {}), 1400);
  }
}

// ------------------------------------------------------ comments & branches --
function openComment(target) {
  if (!nb.run) return;
  nb.commentTarget = target;
  $('commentTarget').textContent = JSON.stringify(target);
  $('commentText').value = '';
  $('commentMsg').textContent = '';
  $('commentPopover').style.display = 'block';
  $('commentText').focus();
}

function closeComment() {
  nb.commentTarget = null;
  const popover = $('commentPopover');
  if (popover) popover.style.display = 'none';
}

async function sendComment() {
  if (!nb.run || !nb.commentTarget) return;
  const text = $('commentText').value.trim();
  if (!text) { $('commentMsg').textContent = 'type a comment first'; return; }
  $('commentSend').disabled = true;
  try {
    await api(`/api/agent/${encodeURIComponent(nb.run)}/comment`, {
      text,
      target: nb.commentTarget,
    });
    $('commentMsg').textContent = 'queued for the next pi turn';
    setTimeout(closeComment, 500);
  } catch (e) {
    $('commentMsg').textContent = `${e.message}. For a settled run, branch with this comment instead.`;
  } finally {
    $('commentSend').disabled = false;
  }
}

async function branchFromTarget(target = nb.commentTarget) {
  if (!nb.run || !target || target.step === undefined) return;
  const sameTarget = nb.commentTarget && JSON.stringify(nb.commentTarget) === JSON.stringify(target);
  const comment = sameTarget ? $('commentText').value.trim() : '';
  $('commentBranch').disabled = true;
  try {
    const source = nb.run;
    const result = await api(`/api/agent/${encodeURIComponent(source)}/branch`, {
      step: target.step,
      target,
      comment: comment || null,
    });
    closeComment();
    resetNotebook();
    nb.run = result.run; nb.job = true;
    history.replaceState(null, '', `?run=${encodeURIComponent(result.run)}`);
    $('runMsg').textContent = `branch: ${result.run}`;
    $('btnStop').disabled = false;
    $('btnRestart').disabled = false;
    setStatus(`branched from ${source} step ${target.step}`);
    startJobPolling(result.run);
    nb.tracePoll = setInterval(() => pullTrace().catch(() => {}), 900);
    await pullTrace().catch(() => {});
  } catch (e) {
    const message = `branch failed: ${e.message}`;
    $('commentMsg').textContent = message;
    $('runMsg').textContent = message;
  } finally {
    $('commentBranch').disabled = false;
  }
}

document.addEventListener('mouseup', () => {
  const selection = window.getSelection();
  const quote = selection?.toString().trim();
  if (!quote || !selection?.anchorNode) return;
  const parent = selection.anchorNode.nodeType === Node.ELEMENT_NODE
    ? selection.anchorNode : selection.anchorNode.parentElement;
  const selectable = parent?.closest?.('[data-comment-target]');
  if (!selectable) return;
  try {
    openComment({ ...JSON.parse(selectable.dataset.commentTarget), quote });
  } catch { /* stale DOM target */ }
});

// --------------------------------------------------------------- run agent --
const TERMINAL = ['done', 'failed', 'stopped'];

function startJobPolling(run) {
  nb.statusPoll = setInterval(async () => {
    try {
      const st = await api(`/api/agent/${encodeURIComponent(run)}/status`);
      if (!nb.done) {
        const label = { running: 'agent is thinking…',
                        stopping: 'stopping, letting the session wind down…',
                        stopped: 'session stopped (kernel results so far were kept)',
                        done: 'finalizing…',
                        failed: 'session failed' }[st.status] ?? st.status;
        setStatus(label, st.log);
      }
      if (st.status === 'failed') {
        stopPolling();
        setStatus(`session failed: ${st.error ?? 'unknown error'}. Check pi login/model configuration.`, st.log);
        $('statusGut').classList.remove('pulse');
      }
      if (TERMINAL.includes(st.status)) {
        clearInterval(nb.statusPoll); nb.statusPoll = null;
        $('btnStop').disabled = true;
        refreshRuns().catch(() => {});
        setTimeout(() => {
          if (!nb.done && nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
        }, 6000);
      }
    } catch { /* transient */ }
  }, 900);
}

async function runSession(body) {
  $('btnRun').disabled = true;
  $('runMsg').textContent = 'starting…';
  try {
    const { run } = await api('/api/agent/start', body);
    resetNotebook();
    nb.run = run; nb.job = true; nb.lastStartBody = body;
    history.replaceState(null, '', `?run=${encodeURIComponent(run)}`);
    $('runMsg').textContent = `session: ${run}`;
    $('btnStop').disabled = false;
    $('btnRestart').disabled = false;
    setStatus(body.conjecture ? 'formalizing your conjecture into a spec…' : 'pi agent session starting…');
    startJobPolling(run);
    nb.tracePoll = setInterval(() => pullTrace().catch(() => { /* trace not on disk yet */ }), 1400);
  } catch (e) {
    $('runMsg').textContent = e.status === 409 ? `busy: ${e.message}` : `error: ${e.message}`;
  } finally {
    $('btnRun').disabled = false;
  }
}

function startAgent() {
  const problemId = $('problemSel').value;
  const conjecture = $('conjText').value.trim();
  const body = {
    max_turns: parseInt($('maxTurns').value, 10) || 40,
    thinking_level: $('thinkingSel').value,
  };
  if ($('modelSel').value) {
    const selected = JSON.parse($('modelSel').value);
    body.provider = selected.provider;
    body.model = selected.id;
  }
  if (conjecture) body.conjecture = conjecture;
  else if (problemId) body.problem_id = problemId;
  else { $('runMsg').textContent = 'pick a problem or type a conjecture'; return; }
  runSession(body);
}

async function stopSession() {
  if (!nb.run || !nb.job) return;
  $('btnStop').disabled = true;
  try {
    await api(`/api/agent/${encodeURIComponent(nb.run)}/stop`, {});
    setStatus('stopping — letting the session wind down…');
  } catch (e) {
    $('runMsg').textContent = `stop: ${e.message}`;
    $('btnStop').disabled = false;
  }
}

async function restartSession() {
  const body = nb.lastStartBody;
  if (!body) { $('runMsg').textContent = 'nothing to restart — run a session first'; return; }
  $('btnRestart').disabled = true;
  try {
    // stop the current session (if ours and still going), wait for it to end
    if (nb.run && nb.job && !nb.done) {
      try { await api(`/api/agent/${encodeURIComponent(nb.run)}/stop`, {}); } catch { /* already terminal */ }
      setStatus('restarting — stopping the current session first…');
      const deadline = Date.now() + 120000;
      while (Date.now() < deadline) {
        try {
          const st = await api(`/api/agent/${encodeURIComponent(nb.run)}/status`);
          if (TERMINAL.includes(st.status)) break;
        } catch { break; }
        await new Promise((r) => setTimeout(r, 800));
      }
    }
    await runSession(body); // fresh notebook, fresh session, same problem
  } finally {
    $('btnRestart').disabled = false;
  }
}

// ------------------------------------------------------------ runs & init --
async function refreshRuns() {
  const runs = await api('/api/runs');
  const sel = $('runSel');
  const keep = sel.value;
  sel.length = 1;
  for (const r of runs) {
    const o = document.createElement('option');
    o.value = r.run;
    o.textContent = r.title ? `${r.run} — ${r.title}` : r.run;
    sel.appendChild(o);
  }
  if (runs.some((r) => r.run === keep)) sel.value = keep;
}

async function init() {
  const problems = await api('/api/problems').catch(() => []);
  const psel = $('problemSel');
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '— choose a bundled problem, or type below —';
  psel.appendChild(none);
  for (const p of problems) {
    const o = document.createElement('option');
    o.value = p.id;
    // Mark your own files, because their Lean stamp carries a review flag a
    // bundled problem does not.
    o.textContent = `${p.title} [${p.quantifier}]${p.source === 'file' ? '  (from problems/)' : ''}`;
    psel.appendChild(o);
  }
  const models = await api('/api/agent/models').catch(() => []);
  const modelSel = $('modelSel');
  for (const model of models.filter((candidate) => candidate.vision)) {
    const option = document.createElement('option');
    option.value = JSON.stringify({ provider: model.provider, id: model.id });
    option.textContent = `${model.provider}/${model.id}`;
    modelSel.appendChild(option);
  }
  await refreshRuns().catch(() => {});
  const params = new URLSearchParams(location.search);
  const wanted = params.get('run');
  if (wanted) {
    $('runSel').value = wanted;
    openRun(wanted).catch(() => {});
  }
  const problem = params.get('problem');
  if (problem) psel.value = problem;
  // Preset the run controls from the URL so one script can open a fully
  // configured notebook. A model that is not authenticated is left unset
  // rather than forced, so the run falls back to pi's own routing.
  const model = params.get('model');
  if (model) {
    const match = [...modelSel.options].find((o) => o.textContent === model);
    if (match) modelSel.value = match.value;
  }
  const thinking = params.get('thinking');
  if (thinking && [...$('thinkingSel').options].some((o) => o.value === thinking)) {
    $('thinkingSel').value = thinking;
  }
  const turns = params.get('turns');
  if (turns && Number(turns) > 0) $('maxTurns').value = turns;
}

$('btnRun').onclick = () => startAgent();
$('btnStop').onclick = () => stopSession();
$('btnRestart').onclick = () => restartSession();
$('btnRefresh').onclick = () => refreshRuns().catch(() => {});
$('runSel').onchange = () => { if ($('runSel').value) openRun($('runSel').value).catch(() => {}); };
$('conjText').addEventListener('input', () => { if ($('conjText').value.trim()) $('problemSel').value = ''; });
$('problemSel').addEventListener('change', () => { if ($('problemSel').value) $('conjText').value = ''; });
$('commentSend').onclick = () => sendComment();
$('commentBranch').onclick = () => branchFromTarget();
$('commentCancel').onclick = closeComment;

// ------------------------------------------------------------- 3D overlay --
// One lazy WebGL context; each open builds the clicked step's scene graph.
let ov = null; // { renderer, scene, camera, controls, group, open }

function ensureOverlay() {
  if (ov) return ov;
  const frame = $('ovFrame');
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  frame.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf7f8fa);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
  camera.position.set(3.2, 2.4, 3.2);
  camera.up.set(0, 0, 1); // math convention: z up
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  const grid = new THREE.GridHelper(6, 12, 0xc8cdd4, 0xe3e6ea);
  grid.rotation.x = Math.PI / 2; // xy-plane, z up
  scene.add(grid);
  const group = new THREE.Group();
  scene.add(group);
  const raycaster = new THREE.Raycaster();
  raycaster.params.Line.threshold = 0.08;
  ov = { renderer, scene, camera, controls, group, raycaster, open: false, step: null, pointerDown: null };
  renderer.domElement.addEventListener('pointerdown', (event) => {
    ov.pointerDown = { x: event.clientX, y: event.clientY };
  });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (!ov.open || !ov.step || !ov.pointerDown) return;
    const moved = Math.hypot(event.clientX - ov.pointerDown.x, event.clientY - ov.pointerDown.y);
    ov.pointerDown = null;
    if (moved > 5) return; // orbit drag, not a pick
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(group.children, true)
      .find((intersection) => intersection.object.userData.commentTarget);
    if (!hit) return;
    const primitive = hit.object.userData.commentTarget;
    $('ovCap').textContent = `picked ${primitive.label ?? primitive.type} · add a comment or branch`;
    openComment({ step: ov.step.step, kind: 'scene', primitive });
  });
  const loop = () => {
    if (!ov.open) return;
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  };
  ov.startLoop = loop;
  window.addEventListener('resize', sizeOverlay);
  return ov;
}

function sizeOverlay() {
  if (!ov || !ov.open) return;
  const frame = $('ovFrame');
  const w = frame.clientWidth, h = frame.clientHeight;
  ov.renderer.setSize(w, h);
  ov.camera.aspect = w / h;
  ov.camera.updateProjectionMatrix();
}

function clearOverlayGroup() {
  for (const child of ov.group.children) {
    child.geometry?.dispose();
    if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
    else child.material?.dispose();
  }
  ov.group.clear();
}

const XYZ = (p) => [p[0], p[1], p[2] ?? 0];
const V = (p) => new THREE.Vector3(...XYZ(p));

function primitiveTarget(prim, extra = {}) {
  return {
    type: prim.type,
    label: prim.name ?? prim.text ?? prim.type,
    ...extra,
  };
}

function buildOverlayScene(prims) {
  clearOverlayGroup();
  return addScenePrims(prims, ov.group);
}

// `tint` replaces every primitive's own colour, which the combined view needs:
// there, WHEN a state happened is the thing to read, and the semantic palette
// (blue holds, red fails) would say the same thing about all of them at once.
// The margin still carries that meaning, in the panel, as text.
function addScenePrims(prims, parent, tint = null, fade = 1) {
  const labels = [];
  const paint = (c) => (tint ?? c);
  for (const prim of prims) {
    if (prim.type === 'points') {
      prim.coords.forEach((p, index) => {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(prim.radius ?? 0.05, 18, 14),
          new THREE.MeshBasicMaterial({ color: paint(prim.color), transparent: fade < 1, opacity: fade }),
        );
        m.position.copy(V(p));
        m.userData.commentTarget = primitiveTarget(prim, { index, coords: XYZ(p) });
        parent.add(m);
      });
    } else if (prim.type === 'segments') {
      prim.pairs.forEach(([a, b], index) => {
        const g = new THREE.BufferGeometry().setFromPoints([V(a), V(b)]);
        const line = new THREE.Line(g, new THREE.LineBasicMaterial({
          color: paint(prim.color), transparent: fade < 1, opacity: fade,
        }));
        line.userData.commentTarget = primitiveTarget(prim, {
          index,
          coords: [XYZ(a), XYZ(b)],
        });
        parent.add(line);
      });
    } else if (prim.type === 'polygon' || prim.type === 'mesh') {
      const positions = [];
      if (prim.type === 'polygon') {
        const c = prim.coords;
        for (let i = 1; i + 1 < c.length; i++) positions.push(...XYZ(c[0]), ...XYZ(c[i]), ...XYZ(c[i + 1]));
      } else {
        for (const f of prim.faces) for (const idx of f) positions.push(...XYZ(prim.vertices[idx]));
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      g.computeVertexNormals();
      const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
        color: paint(prim.color), transparent: true, opacity: (prim.opacity ?? 0.3) * fade,
        side: THREE.DoubleSide, depthWrite: false,
      }));
      mesh.userData.commentTarget = primitiveTarget(prim, {
        coords: prim.type === 'polygon' ? prim.coords.map(XYZ) : undefined,
        vertices: prim.type === 'mesh' ? prim.vertices.map(XYZ) : undefined,
      });
      parent.add(mesh);
    } else if (prim.type === 'sphere') {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(prim.radius, 40, 24),
        new THREE.MeshBasicMaterial({
          color: paint(prim.color), transparent: true,
          opacity: Math.max(prim.opacity ?? 0.12, 0.06) * fade, depthWrite: false,
        }),
      );
      m.position.copy(V(prim.center));
      m.userData.commentTarget = primitiveTarget(prim, {
        center: XYZ(prim.center),
        radius: prim.radius,
      });
      parent.add(m);
    } else if (prim.type === 'label') {
      labels.push(prim.text);
    }
  }
  return labels;
}

function open3d(step) {
  try {
    ensureOverlay();
  } catch {
    return; // no WebGL — the PNG is already on the page
  }
  const labels = buildOverlayScene(step.scene ?? []);
  ov.step = step;
  $('ovCap').textContent =
    `step ${step.step} · ${step.tool ?? 'narrative'}` + (labels.length ? ` — ${labels.join(' · ')}` : '');
  $('overlay').style.display = 'block';
  ov.open = true;
  sizeOverlay();
  frameOverlay();
  ov.startLoop();
}

// Put the content back in the middle of the frame, keeping the direction you
// are looking from. Orbiting is cheap to undo; getting lost is not, and losing
// the object off-screen is the one way to get stuck in a 3D view.
function frameOverlay() {
  if (!ov) return;
  const box = new THREE.Box3().setFromObject(ov.group);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const span = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
  ov.controls.target.copy(center);
  const dir = ov.camera.position.clone().sub(center).normalize();
  if (!dir.lengthSq()) dir.set(1, 1, 1).normalize();
  ov.camera.position.copy(center.clone().add(dir.multiplyScalar(span * 1.15)));
  ov.controls.update();
}

function close3d() {
  if (!ov) return;
  ov.open = false;
  ov.step = null;
  $('overlay').style.display = 'none';
  $('ovLanes').style.display = 'none';
}

// ------------------------------------------------- the progression overlay --
// Every distinct configuration the run reached, in ONE scene. A per-step
// picture answers "what did it do"; only the overlay answers "where was it
// going", which is the question a reader actually has after forty cells.
//
// Colour carries TIME here, on a single violet ramp from pale (early) to deep
// (late). It deliberately avoids blue and red: those two mean holds and fails
// everywhere else in this tool, and a colour cannot honestly mean two things.
function laneColor(index, count) {
  const t = count < 2 ? 1 : index / (count - 1);
  const light = 76 - 46 * t;          // pale early, deep late
  const sat = 32 + 30 * t;
  return `hsl(276, ${sat}%, ${light}%)`;
}

function openProgression() {
  if (!nb.lanes.length) return;
  try {
    ensureOverlay();
  } catch {
    return; // no WebGL — the per-step PNGs are already on the page
  }
  clearOverlayGroup();
  const panel = $('ovLanes');
  panel.replaceChildren();
  const head = el('div', 'lanehead');
  head.appendChild(el('span', null, `${nb.lanes.length} states`));
  const all = el('button', 'mini', 'all');
  const none = el('button', 'mini', 'none');
  head.append(all, none);
  panel.appendChild(head);

  const groups = [];
  nb.lanes.forEach((lane, index) => {
    const color = laneColor(index, nb.lanes.length);
    const last = index === nb.lanes.length - 1;
    const group = new THREE.Group();
    // Earlier states step back so the latest one stays legible through them.
    addScenePrims(lane.scene, group, color, last ? 1 : 0.28 + 0.4 * (index / nb.lanes.length));
    ov.group.add(group);
    groups.push(group);

    const row = el('label', 'lanerow');
    const box = el('input');
    box.type = 'checkbox';
    box.checked = true;
    box.onchange = () => { group.visible = box.checked; };
    const swatch = el('span', 'laneswatch');
    swatch.style.background = color;
    row.append(box, swatch, el('span', 'lanename', `[${lane.step}] ${lane.tool ?? '—'}`));
    const m = lane.check?.margin;
    if (m !== null && m !== undefined) {
      row.appendChild(el('span', `lanemargin ${lane.check.holds ? 'good' : 'bad'}`,
        `${m >= 0 ? '+' : ''}${Number(m).toFixed(3)}`));
    }
    panel.appendChild(row);
  });
  const setAll = (on) => {
    groups.forEach((g) => { g.visible = on; });
    panel.querySelectorAll('input[type=checkbox]').forEach((b) => { b.checked = on; });
  };
  all.onclick = () => setAll(true);
  none.onclick = () => setAll(false);

  ov.step = null; // a combined view has no single step to comment on
  $('ovCap').textContent =
    'every state the run reached · pale = early, deep = late · toggle any state on the left';
  panel.style.display = 'block';
  $('overlay').style.display = 'block';
  ov.open = true;
  sizeOverlay();
  frameOverlay();
  ov.startLoop();
}

// The last cell: the whole run as one picture. It appears when the run is
// finished, because a progression is only complete once there is no next step.
function progressionCell() {
  if (nb.lanes.length < 2 || $('progressionWrap')) return;
  const cell = el('section', 'cell');
  cell.id = 'progressionWrap';
  cell.appendChild(el('div', 'gut out', 'Out [all]:'));
  const body = el('div', 'progbox');
  // The picture first, without a click: the combined view is the answer to
  // "where was it going", and hiding it behind a button hides the answer.
  const img = el('img', 'sceneimg');
  img.loading = 'lazy';
  img.alt = 'every state the run reached, in one scene';
  img.src = `/api/trace/${encodeURIComponent(nb.run)}/progression.png`;
  img.title = 'click to open the interactive version, with a switch per state';
  img.onclick = openProgression;
  img.onerror = () => img.remove();
  body.appendChild(img);
  const open = el('button', null, `⧉ open all ${nb.lanes.length} states, with per-state switches`);
  open.onclick = openProgression;
  body.appendChild(open);
  body.appendChild(el('div', 'note',
    'Each cell above shows one moment. This draws every configuration the run '
    + 'reached in a single 3D scene, pale for early and deep for late, with a '
    + 'switch per state so you can isolate any of them. Colour means time here, '
    + 'never holds or fails: the margin next to each state carries that.'));
  $('cells').after(cell);
}

$('ovCenter').onclick = frameOverlay;
$('ovClose').onclick = close3d;
$('overlay').addEventListener('click', (e) => { if (e.target === $('overlay')) close3d(); });
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('commentPopover').style.display !== 'none') closeComment();
  else if (e.key === 'Escape') close3d();
});

init().catch((e) => setStatus(`init failed: ${e.message}`));
