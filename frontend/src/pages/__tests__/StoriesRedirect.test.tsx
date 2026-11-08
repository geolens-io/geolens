import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, createRoutesFromElements, RouterProvider } from 'react-router';
import { appRoutes } from '@/App';

it('sends /stories to the Stories tab of the Maps page', async () => {
  const router = createMemoryRouter(createRoutesFromElements(appRoutes), { initialEntries: ['/stories'] });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/maps'));
  expect(router.state.location.search).toBe('?type=stories');
});
