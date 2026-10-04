import { render, screen } from '@testing-library/react';
import { Tabs, TabsList, TabsTrigger } from '../tabs';

describe('TabsList', () => {
  it('applies wrapperClassName to the scroll wrapper, a direct child of the Tabs root', () => {
    render(
      <Tabs defaultValue="a">
        <TabsList wrapperClassName="sticky top-14">
          <TabsTrigger value="a">A</TabsTrigger>
        </TabsList>
      </Tabs>,
    );
    const wrapper = screen.getByRole('tablist').parentElement as HTMLElement;
    expect(wrapper).toHaveClass('sticky', 'top-14');
    expect(wrapper.parentElement).toHaveAttribute('data-slot', 'tabs');
  });
});
