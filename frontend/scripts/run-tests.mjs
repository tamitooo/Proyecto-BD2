// Discover test files explicitly: Windows cmd.exe does not expand **/*.test.ts.
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(frontend, 'src');

function findTests(directory) {
  const matches = [];
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, item.name);
    if (item.isDirectory()) {
      matches.push(...findTests(path));
    } else if (item.isFile() && /\.(?:test|spec)\.[cm]?[jt]sx?$/.test(item.name)) {
      matches.push(path);
    }
  }
  return matches;
}

const tests = findTests(source).sort();
if (tests.length === 0) {
  console.error('No frontend test files were found under frontend/src.');
  process.exit(1);
}
console.log(`Running ${tests.length} frontend test files...`);
const result = spawnSync(process.execPath, ['--import', 'tsx', '--test', ...tests], {
  cwd: frontend,
  stdio: 'inherit',
  windowsHide: true,
});
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
