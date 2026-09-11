import React, { useId } from 'react';
import { cn } from '../../utils/cn';

export interface TooltipProps {
  content: string;
  children: React.ReactNode;
  className?: string;
}

export const Tooltip: React.FC<TooltipProps> = ({ content, children, className }) => {
  const tooltipId = useId();
  const child = React.Children.only(children);
  const describedChild = React.isValidElement(child)
    ? React.cloneElement(child as React.ReactElement<{ 'aria-describedby'?: string }>, {
        'aria-describedby': [
          (child.props as { 'aria-describedby'?: string })['aria-describedby'],
          tooltipId,
        ].filter(Boolean).join(' '),
      })
    : child;

  return (
    <div className={cn('relative group inline-flex', className)}>
      {describedChild}
      <div
        id={tooltipId}
        role="tooltip"
        className="absolute top-[calc(100%+8px)] left-1/2 -translate-x-1/2 z-40 w-max max-w-[260px] px-2 py-1.5 border border-border-subtle rounded bg-bg-surface text-text-primary text-[11px] font-medium leading-normal text-left shadow-md opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 pointer-events-none transition-all duration-150 transform -translate-y-1 group-hover:translate-y-0 group-focus-within:translate-y-0 whitespace-normal"
      >
        {content}
      </div>
    </div>
  );
};

export default Tooltip;
