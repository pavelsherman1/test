/**
 * Ethan's Mission Control — Birthday Task Tracker Server (v2 — multi-user sync)
 *
 * Endpoints:
 *   GET    /api/health
 *   GET    /api/version          → { revision, updatedAt }    (lightweight poll)
 *   GET    /api/tasks            → { tasks, revision, updatedAt }
 *   PUT    /api/tasks            → bulk replace (back-compat)
 *   POST   /api/tasks            → add one task,  body { task: {...} }
 *   PATCH  /api/tasks/:id        → update fields, body { field: value, ... }
 *   DELETE /api/tasks/:id        → remove one task
 *
 * Every write increments `revision` and bumps `updatedAt`, atomically via
 * temp-file rename. Node's single-threaded sync handlers serialise requests,
 * so concurrent writes don't race.
 */

const express = require('express');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const DATA_FILE = path.join(DATA_DIR, 'tasks.json');
const SEED_FILE = path.join(__dirname, 'data-seed', 'tasks.json');

const app = express();
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'public')));

function ensureData() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(DATA_FILE)) {
    if (fs.existsSync(SEED_FILE)) {
      fs.copyFileSync(SEED_FILE, DATA_FILE);
      console.log('[init] Seeded tasks.json from bundled seed.');
    } else {
      writeStateRaw([], 0);
    }
  }
}

function readState() {
  try {
    const raw = fs.readFileSync(DATA_FILE, 'utf-8');
    const j = JSON.parse(raw);
    return {
      tasks: Array.isArray(j) ? j : (j.tasks || []),
      updatedAt: j.updatedAt || new Date().toISOString(),
      revision: j.revision || 1
    };
  } catch (e) {
    console.error('[readState]', e.message);
    return { tasks: [], updatedAt: new Date().toISOString(), revision: 1 };
  }
}

function writeStateRaw(tasks, prevRevision) {
  const payload = {
    version: 1,
    revision: (prevRevision || 0) + 1,
    updatedAt: new Date().toISOString(),
    tasks
  };
  const tmp = DATA_FILE + '.tmp.' + process.pid;
  fs.writeFileSync(tmp, JSON.stringify(payload, null, 2));
  fs.renameSync(tmp, DATA_FILE);
  return payload;
}

// --- API ---
app.get('/api/health', (req, res) => res.json({ ok: true, time: new Date().toISOString() }));

app.get('/api/version', (req, res) => {
  const s = readState();
  res.json({ revision: s.revision, updatedAt: s.updatedAt });
});

app.get('/api/tasks', (req, res) => {
  const s = readState();
  res.json({ tasks: s.tasks, revision: s.revision, updatedAt: s.updatedAt });
});

// Bulk replace (kept for back-compat / "reset to seed" tooling)
app.put('/api/tasks', (req, res) => {
  const { tasks } = req.body || {};
  if (!Array.isArray(tasks)) return res.status(400).json({ error: 'tasks must be an array' });
  for (const t of tasks) {
    if (!t.id || !t.title) return res.status(400).json({ error: 'each task needs id + title' });
  }
  const s = readState();
  const written = writeStateRaw(tasks, s.revision);
  res.json({ ok: true, count: tasks.length, revision: written.revision, updatedAt: written.updatedAt });
});

// Add a single task
app.post('/api/tasks', (req, res) => {
  const { task } = req.body || {};
  if (!task || !task.id || !task.title) {
    return res.status(400).json({ error: 'task needs id + title' });
  }
  const s = readState();
  if (s.tasks.find(t => t.id === task.id)) {
    return res.status(409).json({ error: 'duplicate id' });
  }
  s.tasks.push(task);
  const written = writeStateRaw(s.tasks, s.revision);
  res.json({ ok: true, task, revision: written.revision, updatedAt: written.updatedAt });
});

// Update fields on a single task
app.patch('/api/tasks/:id', (req, res) => {
  const s = readState();
  const t = s.tasks.find(x => x.id === req.params.id);
  if (!t) return res.status(404).json({ error: 'not found' });
  const incoming = { ...(req.body || {}) };
  delete incoming.id;
  Object.assign(t, incoming);
  const written = writeStateRaw(s.tasks, s.revision);
  res.json({ ok: true, task: t, revision: written.revision, updatedAt: written.updatedAt });
});

// Delete one task
app.delete('/api/tasks/:id', (req, res) => {
  const s = readState();
  const idx = s.tasks.findIndex(x => x.id === req.params.id);
  if (idx === -1) return res.status(404).json({ error: 'not found' });
  s.tasks.splice(idx, 1);
  const written = writeStateRaw(s.tasks, s.revision);
  res.json({ ok: true, revision: written.revision, updatedAt: written.updatedAt });
});

// SPA fallback
app.get(/^\/(?!api).*/, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

ensureData();
app.listen(PORT, () => {
  console.log(`🚀 Ethan's Mission Control listening on :${PORT}`);
  console.log(`   Data file: ${DATA_FILE}`);
  console.log(`   Multi-user sync: ENABLED (4-second polling)`);
});
