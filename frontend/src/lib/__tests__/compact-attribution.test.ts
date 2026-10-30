import { keepCompactAttributionFolded } from '../compact-attribution';

function mapRoot(width: number) {
  const root = document.createElement('div');
  Object.defineProperty(root, 'clientWidth', { value: width });
  document.body.append(root);
  return root;
}

function attribution(classes: string) {
  const el = document.createElement('details');
  el.className = classes;
  el.setAttribute('open', '');
  return el;
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve));

afterEach(() => {
  document.body.innerHTML = '';
});

it('folds a compact attribution added open on a narrow map', async () => {
  const root = mapRoot(390);
  const stop = keepCompactAttributionFolded(root);
  const el = attribution('maplibregl-ctrl-attrib maplibregl-compact maplibregl-compact-show');
  root.append(el);
  await flush();
  expect(el).not.toHaveAttribute('open');
  expect(el).not.toHaveClass('maplibregl-compact-show');
  stop();
});

it('folds an attribution that turns compact once its credits arrive', async () => {
  const root = mapRoot(390);
  const el = attribution('maplibregl-ctrl-attrib maplibregl-attrib-empty');
  root.append(el);
  const stop = keepCompactAttributionFolded(root);
  el.classList.remove('maplibregl-attrib-empty');
  el.classList.add('maplibregl-compact', 'maplibregl-compact-show');
  await flush();
  expect(el).not.toHaveClass('maplibregl-compact-show');
  stop();
});

it('leaves the attribution open once the reader expands it', async () => {
  const root = mapRoot(390);
  const el = attribution('maplibregl-ctrl-attrib maplibregl-compact');
  el.removeAttribute('open');
  root.append(el);
  const stop = keepCompactAttributionFolded(root);
  el.classList.add('maplibregl-compact-show');
  el.setAttribute('open', '');
  await flush();
  expect(el).toHaveAttribute('open');
  expect(el).toHaveClass('maplibregl-compact-show');
  stop();
});

it('leaves the attribution open on a wide map', async () => {
  const root = mapRoot(1200);
  const stop = keepCompactAttributionFolded(root);
  const el = attribution('maplibregl-ctrl-attrib maplibregl-compact maplibregl-compact-show');
  root.append(el);
  await flush();
  expect(el).toHaveAttribute('open');
  expect(el).toHaveClass('maplibregl-compact-show');
  stop();
});
