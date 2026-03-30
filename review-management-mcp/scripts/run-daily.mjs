#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import dotenv from 'dotenv';

dotenv.config();

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const logsDir = path.join(root, 'logs');
fs.mkdirSync(logsDir, { recursive: true });

const now = new Date().toISOString().replaceAll(':', '-');
const runLog = path.join(logsDir, `run-${now}.log`);

function run(command, args = []) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    env: process.env,
  });

  fs.appendFileSync(
    runLog,
    `\n$ ${command} ${args.join(' ')}\n${result.stdout ?? ''}${result.stderr ?? ''}`,
    'utf8'
  );

  if (result.status !== 0) {
    throw new Error(`Command failed: ${command} ${args.join(' ')}`);
  }
}

function main() {
  const dryRun = process.env.DRY_RUN === 'true';
  fs.appendFileSync(runLog, `Start: ${new Date().toISOString()} | DRY_RUN=${dryRun}\n`, 'utf8');

  // Step 1-4: scan, classify, draft, (optional) autopost through baseline runner.
  run('python3', ['scripts/review_management_runner.py']);

  // Step 5: notify manager queue.
  run('node', ['scripts/notify-pending.mjs']);

  fs.appendFileSync(runLog, `Done: ${new Date().toISOString()}\n`, 'utf8');
  console.log(`run-daily completed. log=${runLog}`);
}

try {
  main();
} catch (error) {
  fs.appendFileSync(runLog, `ERROR: ${(error).message}\n`, 'utf8');
  console.error((error).message);
  process.exit(1);
}
