# automation

This folder contains the Node-based web automation subsystem for `RunWeb`.

Contents:

1. `package.json` and `package-lock.json` define the Playwright dependency boundary.
2. `kimi_web_automation.mjs` drives the Kimi web UI and captures the response.
3. `kimi_web_probe.mjs` is the related probe utility.

Usage:

1. Run `npm install` in this folder when Playwright is needed.
2. The PowerShell entrypoints under `../tools/` already use this folder as the npm working directory.
3. Do not move these files independently unless you also update the PowerShell and Python callers.