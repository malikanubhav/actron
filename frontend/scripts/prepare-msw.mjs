// Copies MSW's service worker into public/ only for fixture builds (NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1) and removes
// it otherwise, so production builds ship no mock code.
import { copyFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const target = join(root, 'public', 'mockServiceWorker.js')
const source = join(root, 'node_modules', 'msw', 'lib', 'mockServiceWorker.js')

if (process.env.NEXT_PUBLIC_ACTRON_DEV_FIXTURES === '1') {
  copyFileSync(source, target)
  console.log('dev fixtures: MSW worker copied to public/')
} else if (existsSync(target)) {
  rmSync(target)
  console.log('dev fixtures off: MSW worker removed from public/')
}
