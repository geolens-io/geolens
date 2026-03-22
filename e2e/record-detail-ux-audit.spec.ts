import fs from 'node:fs';
import path from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

type RecordType = 'vector_dataset' | 'raster_dataset' | 'vrt_dataset' | 'collection';
type ViewportName = 'desktop' | 'mobile';

interface AuditTarget {
  id: string;
  path?: string;
  title: string;
  notes?: string;
}

interface TargetManifest {
  baseUrl?: string;
  targets: Record<RecordType, AuditTarget | null>;
}

interface FailureEntry {
  kind: 'response' | 'requestfailed';
  message: string;
  url: string;
}

interface FocusState {
  tag: string;
  text: string;
  focusVisible: boolean;
}

const targetsPath = path.resolve(
  process.env.E2E_QA_TARGETS_PATH ??
    path.join(
      process.cwd(),
      '.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/qa-targets.json',
    ),
);
const outputDir = path.resolve(
  process.env.QA_OUTPUT_DIR ??
    path.join(
      process.cwd(),
      '.planning/quick/260321-perform-a-second-deeper-ui-ux-qa-pass-ov',
    ),
);

const manifest = JSON.parse(fs.readFileSync(targetsPath, 'utf8')) as TargetManifest;

function ensureDir(dirPath: string) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeLines(filePath: string, lines: string[]) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${lines.join('\n')}${lines.length > 0 ? '\n' : ''}`, 'utf8');
}

function appendLines(filePath: string, lines: string[]) {
  ensureDir(path.dirname(filePath));
  fs.appendFileSync(filePath, `${lines.join('\n')}${lines.length > 0 ? '\n' : ''}`, 'utf8');
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatViolations(violations: any[]): string {
  return violations
    .map(
      (violation) =>
        `[${violation.id}] ${violation.description} (${violation.impact})\n` +
        violation.nodes.map((node: { html: string }) => `  - ${node.html}`).join('\n'),
    )
    .join('\n\n');
}

function routeFor(recordType: RecordType, target: AuditTarget): string {
  if (target.path) return target.path;
  return recordType === 'collection'
    ? `/collections/${target.id}`
    : `/datasets/${target.id}`;
}

function buildUrl(recordType: RecordType, target: AuditTarget): string {
  const baseUrl = manifest.baseUrl ?? 'http://localhost:8080';
  const route = routeFor(recordType, target);
  if (recordType === 'collection') return `${baseUrl}${route}`;
  return `${baseUrl}${route}#overview`;
}

async function countVisibleH1(page: Page): Promise<number> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('h1')).filter((node) => {
      if (!(node instanceof HTMLElement)) return false;
      return node.offsetWidth > 0 || node.offsetHeight > 0 || node.getClientRects().length > 0;
    }).length,
  );
}

async function isVisible(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((query) => {
    const node = document.querySelector(query);
    if (!(node instanceof HTMLElement)) return false;
    return node.offsetWidth > 0 || node.offsetHeight > 0 || node.getClientRects().length > 0;
  }, selector);
}

async function captureFocusState(page: Page): Promise<FocusState> {
  return page.evaluate(() => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) {
      return { tag: 'UNKNOWN', text: '', focusVisible: false };
    }

    const text = active.textContent?.trim().replace(/\s+/g, ' ').slice(0, 80) ?? '';
    return {
      tag: active.tagName,
      text,
      focusVisible: active.matches(':focus-visible'),
    };
  });
}

async function runAudit(
  page: Page,
  recordType: RecordType,
  viewportName: ViewportName,
  target: AuditTarget,
) {
  const consoleLines: string[] = [];
  const networkLines: string[] = [];
  const previewFailures: FailureEntry[] = [];
  const notes: string[] = [];
  const failures: string[] = [];
  const start = Date.now();

  const screenshotPath = path.join(outputDir, 'evidence', `${recordType}-${viewportName}.png`);
  const consoleLogPath = path.join(outputDir, 'logs', `console-${recordType}-${viewportName}.log`);
  const sharedConsoleLogPath = path.join(outputDir, 'logs', `console-${recordType}.log`);
  const networkLogPath = path.join(outputDir, 'logs', `network-${recordType}-${viewportName}.log`);
  const sharedNetworkLogPath = path.join(outputDir, 'logs', `network-${recordType}.log`);
  const axeLogPath = path.join(outputDir, 'logs', `axe-${recordType}-${viewportName}.log`);
  const notesLogPath = path.join(outputDir, 'logs', `notes-${recordType}-${viewportName}.log`);

  const recordFailure = (message: string) => failures.push(message);
  const recordNote = (message: string) => notes.push(message);

  const onConsole = (message: { type(): string; text(): string }) => {
    const elapsedMs = Date.now() - start;
    consoleLines.push(`[${elapsedMs}ms] [${message.type().toUpperCase()}] ${message.text()}`);
  };

  const onResponse = (response: { status(): number; url(): string }) => {
    if (response.status() < 400) return;
    const elapsedMs = Date.now() - start;
    const url = response.url();
    const message = `[${elapsedMs}ms] [${response.status()}] ${url}`;
    networkLines.push(message);
    if (
      url.includes('/raster-tiles/') ||
      url.includes('/quicklook') ||
      url.includes('/preview')
    ) {
      previewFailures.push({ kind: 'response', message, url });
    }
  };

  const onRequestFailed = (request: {
    url(): string;
    failure(): { errorText?: string } | null;
  }) => {
    const elapsedMs = Date.now() - start;
    const url = request.url();
    const reason = request.failure()?.errorText ?? 'request failed';
    const message = `[${elapsedMs}ms] [FAILED] ${reason} :: ${url}`;
    networkLines.push(message);
    if (
      url.includes('/raster-tiles/') ||
      url.includes('/quicklook') ||
      url.includes('/preview')
    ) {
      previewFailures.push({ kind: 'requestfailed', message, url });
    }
  };

  page.on('console', onConsole);
  page.on('response', onResponse);
  page.on('requestfailed', onRequestFailed);

  try {
    const url = buildUrl(recordType, target);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined);

    if (page.url().includes('/login')) {
      recordFailure(`unexpected auth redirect for ${recordType} ${viewportName}: ${page.url()}`);
    }

    const heading = page.getByRole('heading', { level: 1 });
    const headingHandle = heading.first();
    let headingVisible = false;
    try {
      await expect(headingHandle).toBeVisible({ timeout: 20_000 });
      headingVisible = true;
    } catch (error) {
      recordFailure(
        `canonical H1 is not visible within 20s for ${recordType} ${viewportName}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }

    if (headingVisible) {
      const headingText = (await headingHandle.textContent())?.trim() ?? '';
      recordNote(`H1 text: ${headingText}`);
    }

    const visibleH1Count = await countVisibleH1(page);
    if (visibleH1Count !== 1) {
      recordFailure(`expected exactly 1 visible H1, found ${visibleH1Count}`);
    }

    if (recordType === 'collection') {
      try {
        await expect(page.getByRole('heading', { level: 2, name: /datasets/i })).toBeVisible({
          timeout: 15_000,
        });
      } catch (error) {
        recordFailure(
          `collection dataset section did not render: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }

      const listFilter = page.getByPlaceholder(/filter datasets by name/i);
      try {
        await expect(listFilter).toBeVisible({ timeout: 10_000 });
      } catch (error) {
        recordFailure(
          `collection filter control did not render: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
    } else {
      try {
        await expect(page.getByRole('tablist')).toBeVisible({ timeout: 15_000 });
      } catch (error) {
        recordFailure(
          `dataset tablist did not render: ${error instanceof Error ? error.message : String(error)}`,
        );
      }

      try {
        await expect(page.getByRole('tabpanel', { name: /overview/i })).toBeVisible({
          timeout: 15_000,
        });
      } catch (error) {
        recordFailure(
          `overview tabpanel did not render: ${error instanceof Error ? error.message : String(error)}`,
        );
      }

      if (!(await isVisible(page, '[data-testid="dataset-map-shell"]'))) {
        recordFailure('dataset map shell is missing or not visible');
      }

      if (!(await isVisible(page, '[data-testid="dataset-header-overflow-trigger"]'))) {
        recordFailure('dataset header overflow trigger is missing, so actions are not collapsing predictably');
      }
    }

    if (viewportName === 'mobile' && headingVisible) {
      const headingBox = await headingHandle.boundingBox();
      const overflowBox =
        recordType === 'collection'
          ? null
          : await page.getByTestId('dataset-header-overflow-trigger').boundingBox().catch(() => null);
      const lineEstimate = await headingHandle.evaluate((node) => {
        if (!(node instanceof HTMLElement)) return 0;
        const style = window.getComputedStyle(node);
        const fontSize = Number.parseFloat(style.fontSize || '0');
        const lineHeight = Number.parseFloat(style.lineHeight || `${fontSize * 1.2}`);
        return lineHeight > 0 ? Math.round(node.getBoundingClientRect().height / lineHeight) : 0;
      });

      recordNote(
        `mobile heading width=${Math.round(headingBox?.width ?? 0)}px lines=${lineEstimate} overflowLeft=${Math.round(overflowBox?.x ?? 0)}px`,
      );

      if (!headingBox || headingBox.width <= 100) {
        recordFailure(
          `mobile H1 is visually too narrow (${headingBox?.width ?? 0}px), matching the truncated-header regression`,
        );
      }
      if (lineEstimate >= 5) {
        recordFailure(`mobile H1 wraps to ${lineEstimate} lines, which makes the header feel crowded`);
      }
      if (overflowBox && headingBox && headingBox.x + headingBox.width > overflowBox.x - 8) {
        recordFailure('mobile H1 and action area overlap horizontally, so the header has no safe title lane');
      }
    }

    await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
    await page.keyboard.press('Tab');
    const firstFocus = await captureFocusState(page);
    recordNote(`focus step 1: ${firstFocus.tag} "${firstFocus.text}" focusVisible=${firstFocus.focusVisible}`);
    if (firstFocus.tag === 'BODY') {
      recordFailure('keyboard tab order did not land on a focusable control');
    }
    if (!firstFocus.focusVisible) {
      recordFailure('focused element is missing a focus-visible state after keyboard navigation');
    }

    await page.keyboard.press('Tab');
    const secondFocus = await captureFocusState(page);
    recordNote(`focus step 2: ${secondFocus.tag} "${secondFocus.text}" focusVisible=${secondFocus.focusVisible}`);

    await page.waitForTimeout(recordType === 'vrt_dataset' ? 12_000 : 4_000);

    try {
      const axeResults = await new AxeBuilder({ page })
        .withTags(wcagTags)
        .exclude('.maplibregl-map')
        .analyze();

      if (axeResults.violations.length > 0) {
        const formatted = formatViolations(axeResults.violations);
        writeLines(axeLogPath, formatted.split('\n'));
        recordFailure(`axe violations detected for ${recordType} ${viewportName}:\n${formatted}`);
      } else {
        writeLines(axeLogPath, []);
      }
    } catch (error) {
      recordFailure(`axe scan crashed for ${recordType} ${viewportName}: ${error instanceof Error ? error.message : String(error)}`);
    }

    const repeatedPreviewFailures = previewFailures.filter(
      (entry) => entry.url.includes('/raster-tiles/') || entry.url.includes('/quicklook'),
    );
    if (repeatedPreviewFailures.length > 10) {
      recordFailure(
        `detected ${repeatedPreviewFailures.length} preview/tile failures for ${recordType} ${viewportName}; see ${path.relative(process.cwd(), networkLogPath)}`,
      );
    }
  } finally {
    ensureDir(path.dirname(screenshotPath));
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => undefined);

    page.off('console', onConsole);
    page.off('response', onResponse);
    page.off('requestfailed', onRequestFailed);

    writeLines(consoleLogPath, consoleLines);
    writeLines(networkLogPath, networkLines);
    writeLines(notesLogPath, notes);

    const sectionHeader = [`# ${recordType} ${viewportName}`];
    appendLines(sharedConsoleLogPath, [...sectionHeader, ...consoleLines, '']);
    appendLines(sharedNetworkLogPath, [...sectionHeader, ...networkLines, '']);
  }

  expect(failures, failures.join('\n\n')).toEqual([]);
}

test.describe('Record Detail UX Audit', () => {
  test.describe('desktop', () => {
    test.use({ viewport: { width: 1280, height: 800 } });

    (Object.entries(manifest.targets) as Array<[RecordType, AuditTarget | null]>).forEach(
      ([recordType, target]) => {
        test(`${recordType} desktop audit`, async ({ page }) => {
          test.skip(!target, `Missing QA target for ${recordType}`);
          await runAudit(page, recordType, 'desktop', target!);
        });
      },
    );
  });

  test.describe('mobile', () => {
    test.use({ viewport: { width: 375, height: 812 } });

    (Object.entries(manifest.targets) as Array<[RecordType, AuditTarget | null]>).forEach(
      ([recordType, target]) => {
        test(`${recordType} mobile audit`, async ({ page }) => {
          test.skip(!target, `Missing QA target for ${recordType}`);
          await runAudit(page, recordType, 'mobile', target!);
        });
      },
    );
  });
});
