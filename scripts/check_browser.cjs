// Optional development-only browser checks. Python runtime stays dependency-free.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(path.resolve('.ci-browser/node_modules/playwright'));

async function main() {
  const output = path.resolve('runs/browser');
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [{ width: 1200, height: 900 }, { width: 390, height: 844 }]) {
      for (const name of ['normal', 'deviations', 'blocked', 'sensor-failure']) {
        const report = JSON.parse(await fs.readFile('runs/' + name + '.json', 'utf8'));
        const context = await browser.newContext({ viewport, acceptDownloads: true, offline: true });
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [], externalRequests = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => {
          if (/^https?:/.test(request.url())) externalRequests.push(request.url());
        });
        try {
          await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') });
          await page.goto(pathToFileURL(path.resolve('runs/' + name + '.html')).href);
          await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'));
          assert.equal(await page.locator('#status').textContent(), report.status);
          assert.equal(await page.locator('#stations li').count(), 3);
          const stationText = await page.locator('#stations').textContent();
          if (name === 'deviations') {
            assert.match(stationText, /prepared_extra_box/);
            assert.match(stationText, /prepared_missing_item/);
          }
          if (!report.returned_home) assert.match(stationText, /не посещена/);
          assert.match(await page.locator('footer').textContent(), /компьютерное зрение не выполнялось/);

          // Use real keyboard input to exercise the range control's input event.
          const slider = page.locator('#scrub');
          await slider.focus();
          await slider.press('End');
          const last = report.trace[report.trace.length - 1];
          assert.equal(await slider.inputValue(), String(report.trace.length - 1));
          assert.equal(await page.locator('#state').textContent(), last.state);
          const robot = page.locator('#arena circle').last();
          assert.ok(Math.abs(Number(await robot.getAttribute('cx')) - (32 + last.x * 180)) < .001);
          assert.ok(Math.abs(Number(await robot.getAttribute('cy')) -
            (32 + (report.world.height - last.y) * 180)) < .001);

          // Playback restarts from the end; pausing must freeze the trace.
          await page.locator('#play').click();
          await page.clock.runFor(80);
          assert.ok(Number(await slider.inputValue()) > 0, 'playback did not advance');
          assert.equal(await page.locator('#play').textContent(), 'Пауза');
          await page.locator('#play').click();
          const paused = await slider.inputValue();
          await page.clock.runFor(200);
          assert.equal(await slider.inputValue(), paused, 'pause did not freeze playback');
          await slider.focus();
          await slider.press('End');

          const layout = await page.evaluate(() => {
            const arena = document.getElementById('arena').getBoundingClientRect();
            const sections = Array.from(document.querySelectorAll('main > section'))
              .map(element => {
                const r = element.getBoundingClientRect();
                return { x: r.x, y: r.y, right: r.right, bottom: r.bottom };
              });
            return {
              scrollWidth: document.documentElement.scrollWidth,
              viewportWidth: window.innerWidth,
              arenaWidth: arena.width, arenaHeight: arena.height,
              sections
            };
          });
          assert.ok(layout.scrollWidth <= layout.viewportWidth, 'horizontal overflow');
          assert.ok(layout.arenaWidth > 200 && layout.arenaHeight > 100, 'map is not visible');
          const [a, b] = layout.sections;
          if (viewport.width < 730) assert.ok(b.y >= a.bottom - 1, 'mobile panels overlap');
          else assert.ok(b.x >= a.right - 1, 'desktop panels overlap');

          const prefix = name + '-' + viewport.width;
          await page.screenshot({ path: path.join(output, prefix + '.png'), fullPage: true });
          const downloadEvent = page.waitForEvent('download');
          await page.locator('#download').click();
          const download = await downloadEvent;
          const downloadPath = path.join(output, prefix + '-download.json');
          await download.saveAs(downloadPath);
          assert.deepEqual(JSON.parse(await fs.readFile(downloadPath, 'utf8')), report);
          assert.deepEqual(errors, [], 'browser JavaScript errors');
          assert.deepEqual(externalRequests, [], 'offline report requested external resources');
          results.push({ scenario: name, viewport, status: 'passed', layout });
          console.log('PASS browser: ' + prefix + ', playback, pause, slider, JSON, layout, offline');
        } finally {
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
    await fs.writeFile(path.join(output, 'checks.json'), JSON.stringify(results, null, 2) + '\n');
  }
  console.log('All eight offline browser scenarios passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
