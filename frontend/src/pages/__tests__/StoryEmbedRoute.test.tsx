import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { appRoutes } from '@/App';

const EMBED_PATH = '/stories/:id/embed';

function findErrorElement(node: unknown): ReactNode | undefined {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findErrorElement(child);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (!isValidElement(node)) return undefined;
  const props = (node as ReactElement<{ path?: string; errorElement?: ReactNode; children?: unknown }>).props;
  if (props.path === EMBED_PATH) return props.errorElement;
  return findErrorElement(props.children);
}

function Broken(): ReactNode {
  throw new Error('render failed');
}

it("keeps a failure on the embed page inside the frame, offering only the story in a new tab", async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const router = createMemoryRouter(
    [{ path: EMBED_PATH, element: <Broken />, errorElement: findErrorElement(appRoutes) }],
    { initialEntries: ['/stories/story-1/embed'] },
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  expect(await screen.findByRole('heading', { name: "This story couldn't be shown" })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /home|back/i })).not.toBeInTheDocument();
  expect(screen.queryByText('render failed')).not.toBeInTheDocument();
  const links = screen.getAllByRole('link');
  expect(links).toHaveLength(1);
  expect(links[0]).toHaveAccessibleName('Open the story in a new tab');
  expect(links[0]).toHaveAttribute('href', '/stories/story-1');
  expect(links[0]).toHaveAttribute('target', '_blank');
  expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer');
});
