import fs from 'node:fs';
import path from 'node:path';
import dotenv from 'dotenv';

dotenv.config();

const projectRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const pendingPath = path.join(projectRoot, 'logs', 'pending-reviews.md');

function escapeHtml(value = '') {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildEmailHtml(items) {
  const rows = items
    .map((item) => `<li><strong>${escapeHtml(item.id)}</strong> - ${escapeHtml(item.text)}</li>`)
    .join('');

  return `<h3>Pending Reviews</h3><ul>${rows}</ul>`;
}

function parsePendingLines(raw) {
  return raw
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [, id = '', text = ''] = line.split('|').map((x) => x.trim());
      return { id, text };
    });
}

if (!fs.existsSync(pendingPath)) {
  console.log('No pending file found.');
  process.exit(0);
}

const lines = fs.readFileSync(pendingPath, 'utf8');
const items = parsePendingLines(lines);

const html = buildEmailHtml(items);
console.log('Email preview length:', html.length);
