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

function expandEnvVars(value) {
  return value.replace(/%([^%]+)%/g, (_, name) => process.env[name] || `%${name}%`);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
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
  const tempProfileDir = await fs.mkdtemp(path.join(os.tmpdir(), 'kimi-edge-profile-'));
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

async function launchBrowserContext(browserChannel, profileDir) {
  await removeKnownLockFiles(profileDir);
  return chromium.launchPersistentContext(profileDir, {
    channel: browserChannel,
    headless: false,
  });
}

function pickBrowserChannel(browserName) {
  if (browserName === 'chrome') {
    return 'chrome';
  }
  return 'msedge';
}

async function waitForAssistantReply(page, selector, timeoutMs, idlePollMs) {
  const start = Date.now();
  let lastText = '';
  let stableCount = 0;

  while (Date.now() - start < timeoutMs) {
    const messages = await page.locator(selector).allTextContents();
    const combined = messages.join('\n\n').trim();
    if (combined && combined === lastText) {
      stableCount += 1;
    } else {
      stableCount = 0;
      lastText = combined;
    }

    if (combined && stableCount >= 3) {
      return combined;
    }

    await page.waitForTimeout(idlePollMs);
  }

  throw new Error('Timed out waiting for Kimi response to stabilize.');
}

async function main() {
  const configPath = getArgValue('--config');
  const sourcePath = getArgValue('--source');
  const skillPackPath = getArgValue('--skill-pack');
  const responsePath = getArgValue('--response-output');

  if (!configPath || !sourcePath || !skillPackPath || !responsePath) {
    throw new Error('Missing required arguments: --config, --source, --skill-pack, --response-output.');
  }

  const config = await readJson(configPath);
  const automation = config.webAutomation || {};
  const pageReadyMs = automation.timeouts?.pageReadyMs ?? 30000;
  const responseReadyMs = automation.timeouts?.responseReadyMs ?? 300000;
  const idlePollMs = automation.timeouts?.idlePollMs ?? 1500;
  const selectors = automation.selectors || {};
  const browserChannel = pickBrowserChannel(automation.browser || 'msedge');
  const userDataDir = path.resolve(expandEnvVars(automation.userDataDir || path.join(process.cwd(), '.kimi-browser-profile')));
  const kimiUrl = automation.url || 'https://kimi.moonshot.cn/';

  await ensureDir(userDataDir);
  await ensureDir(path.dirname(responsePath));

  let runtimeUserDataDir = userDataDir;
  let usingClonedProfile = false;
  let browserContext;

  try {
    browserContext = await launchBrowserContext(browserChannel, runtimeUserDataDir);
  } catch (directLaunchError) {
    runtimeUserDataDir = await cloneProfileForRetry(userDataDir);
    usingClonedProfile = true;

    try {
      browserContext = await launchBrowserContext(browserChannel, runtimeUserDataDir);
    } catch (retryLaunchError) {
      await fs.rm(runtimeUserDataDir, { recursive: true, force: true }).catch(() => {});
      throw new Error(
        'Failed to launch Edge automation profile directly and via cloned retry profile. '
        + `Direct error: ${directLaunchError.message}. Retry error: ${retryLaunchError.message}`
      );
    }
  }

  try {
    const page = browserContext.pages()[0] || await browserContext.newPage();
    await page.goto(kimiUrl, { waitUntil: 'domcontentloaded', timeout: pageReadyMs });

    const inputLocator = page.locator(selectors.inputFile || "input[type='file']").first();
    await inputLocator.waitFor({ timeout: pageReadyMs });
    await inputLocator.setInputFiles([path.resolve(skillPackPath), path.resolve(sourcePath)]);

    const prompt = automation.promptTemplate || '请使用我上传的 skill pack 和源码文件完成代码审查。';
    await page.keyboard.type(prompt, { delay: 10 });

    const sendButton = page.locator(selectors.sendButton || "button:has-text('发送'), button:has-text('Send')").first();
    await sendButton.click({ timeout: pageReadyMs });

    const reply = await waitForAssistantReply(
      page,
      selectors.assistantMessage || '.markdown, [data-testid="assistant-message"], .message-assistant',
      responseReadyMs,
      idlePollMs,
    );

    await fs.writeFile(responsePath, reply + '\n', 'utf8');
    console.log(JSON.stringify({
      status: 'web_response_captured',
      responsePath: path.resolve(responsePath),
      skillPackPath: path.resolve(skillPackPath),
      sourcePath: path.resolve(sourcePath),
      profileMode: usingClonedProfile ? 'cloned-retry-profile' : 'primary-profile'
    }, null, 2));
  } finally {
    await browserContext.close();
    if (usingClonedProfile) {
      await fs.rm(runtimeUserDataDir, { recursive: true, force: true }).catch(() => {});
    }
  }
}

main().catch((error) => {
  console.error(JSON.stringify({
    status: 'web_run_failed',
    error: error.message
  }, null, 2));
  process.exit(1);
});