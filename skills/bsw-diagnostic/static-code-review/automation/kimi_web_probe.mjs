import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright';

const CHROMIUM_LOCK_FILE_NAMES = new Set([
  'LOCK',
  'SingletonCookie',
  'SingletonLock',
  'SingletonSocket',
]);

function getArgValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index === process.argv.length - 1) {
    return null;
  }
  return process.argv[index + 1];
}

async function removeKnownLockFiles(profileDir) {
  const candidateDirs = [profileDir, path.join(profileDir, 'Default')];

  for (const dirPath of candidateDirs) {
    for (const fileName of CHROMIUM_LOCK_FILE_NAMES) {
      await fs.rm(path.join(dirPath, fileName), { force: true }).catch(() => {});
    }
  }
}

async function cloneProfileForRetry(sourceDir) {
  const tempProfileDir = await fs.mkdtemp(path.join(os.tmpdir(), 'kimi-edge-profile-probe-'));
  await fs.cp(sourceDir, tempProfileDir, {
    recursive: true,
    force: true,
    filter: (entryPath) => {
      const entryName = path.basename(entryPath);
      if (CHROMIUM_LOCK_FILE_NAMES.has(entryName)) {
        return false;
      }
      if (entryName === 'Crashpad') {
        return false;
      }
      return true;
    },
  });
  await removeKnownLockFiles(tempProfileDir);
  return tempProfileDir;
}

async function launchBrowserContext(profileDir) {
  await removeKnownLockFiles(profileDir);
  return chromium.launchPersistentContext(profileDir, {
    channel: 'msedge',
    headless: false,
  });
}

async function main() {
  const url = getArgValue('--url') || 'https://www.kimi.com/';
  const userDataDir = process.env.LOCALAPPDATA + '\\KimiReview\\msedge-profile';

  let runtimeUserDataDir = userDataDir;
  let usingClonedProfile = false;
  let browser;

  try {
    browser = await launchBrowserContext(runtimeUserDataDir);
  } catch (directLaunchError) {
    runtimeUserDataDir = await cloneProfileForRetry(userDataDir);
    usingClonedProfile = true;

    try {
      browser = await launchBrowserContext(runtimeUserDataDir);
    } catch (retryLaunchError) {
      await fs.rm(runtimeUserDataDir, { recursive: true, force: true }).catch(() => {});
      throw new Error(
        'Failed to launch probe browser directly and via cloned retry profile. '
        + `Direct error: ${directLaunchError.message}. Retry error: ${retryLaunchError.message}`
      );
    }
  }

  try {
    const page = browser.pages()[0] || await browser.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(5000);

    const snapshot = await page.evaluate(() => {
      const pick = (nodes, mapper) => Array.from(nodes).slice(0, 40).map(mapper);
      return {
        title: document.title,
        url: location.href,
        buttons: pick(document.querySelectorAll('button'), (element) => ({
          text: (element.innerText || '').trim(),
          aria: element.getAttribute('aria-label'),
          testid: element.getAttribute('data-testid'),
          cls: element.className,
        })),
        inputs: pick(document.querySelectorAll('input, textarea'), (element) => ({
          tag: element.tagName,
          type: element.getAttribute('type'),
          placeholder: element.getAttribute('placeholder'),
          accept: element.getAttribute('accept'),
          aria: element.getAttribute('aria-label'),
          testid: element.getAttribute('data-testid'),
          cls: element.className,
        })),
        editable: pick(document.querySelectorAll('[contenteditable="true"], [role="textbox"]'), (element) => ({
          tag: element.tagName,
          role: element.getAttribute('role'),
          placeholder: element.getAttribute('placeholder'),
          aria: element.getAttribute('aria-label'),
          testid: element.getAttribute('data-testid'),
          text: (element.innerText || '').slice(0, 80),
          cls: element.className,
        })),
        links: pick(document.querySelectorAll('a'), (element) => ({
          text: (element.innerText || '').trim(),
          href: element.href,
          aria: element.getAttribute('aria-label'),
        })),
      };
    });

    console.log(JSON.stringify({
      profileMode: usingClonedProfile ? 'cloned-retry-profile' : 'primary-profile',
      snapshot,
    }, null, 2));
  } finally {
    await browser.close();
    if (usingClonedProfile) {
      await fs.rm(runtimeUserDataDir, { recursive: true, force: true }).catch(() => {});
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});