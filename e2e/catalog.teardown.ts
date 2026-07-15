import { test as teardown, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { deleteDataset, type SeededDataset } from './helpers/catalog';

const catalogFixtureFile = path.join(__dirname, '../playwright/.auth/catalog-fixture.json');

teardown('remove shared catalog fixture', async () => {
  if (!fs.existsSync(catalogFixtureFile)) return;

  const fixture = JSON.parse(
    fs.readFileSync(catalogFixtureFile, 'utf-8'),
  ) as SeededDataset;
  const deleted = await deleteDataset(fixture.id, fixture.title);
  expect(deleted).toBe(true);
  fs.rmSync(catalogFixtureFile);
});
