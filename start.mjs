import { execFileSync } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';

try {
  execFileSync(npm, ['install', '--silent'], { cwd: __dirname, stdio: 'ignore' });
} catch {}

await import('./server.ts');
