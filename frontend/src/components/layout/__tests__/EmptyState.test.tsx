import { render, screen, waitFor } from '@/test/test-utils';
import { FolderOpen } from 'lucide-react';
import { EmptyState } from '../EmptyState';

describe('EmptyState', () => {
  it('renders icon and title', () => {
    render(<EmptyState icon={FolderOpen} title="No items found" />);
    expect(screen.getByText('No items found')).toBeInTheDocument();
  });

  it('renders description when provided', () => {
    render(
      <EmptyState icon={FolderOpen} title="No items found" description="Try a different search." />,
    );
    expect(screen.getByText('Try a different search.')).toBeInTheDocument();
  });

  it('does not render description when omitted', () => {
    const { container } = render(<EmptyState icon={FolderOpen} title="No items found" />);
    const paragraphs = container.querySelectorAll('p:not([role="status"])');
    // Only the title paragraph should exist
    expect(paragraphs).toHaveLength(1);
  });

  it('renders action when provided', () => {
    render(
      <EmptyState icon={FolderOpen} title="No items found" action={<button>Create</button>} />,
    );
    expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument();
  });

  it('merges custom className', () => {
    const { container } = render(
      <EmptyState icon={FolderOpen} title="No items found" className="py-8" />,
    );
    expect(container.firstChild).toHaveClass('py-8');
  });

  it('mounts an empty status region, then fills it so the empty result is announced', async () => {
    render(<EmptyState icon={FolderOpen} title="No items found" description="Try again." />);
    const status = screen.getByRole('status');
    expect(status).toBeEmptyDOMElement();
    await waitFor(() => expect(status).toHaveTextContent('No items found. Try again.'));
  });
});
