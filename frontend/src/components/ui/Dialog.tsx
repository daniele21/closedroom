/**
 * Dialog.tsx
 * Generic modal dialog built on @radix-ui/react-dialog.
 *
 * Features:
 * - Overlay with backdrop-blur
 * - Scale + fade animation on desktop
 * - Slide-up bottom sheet on mobile (≤ 640px)
 * - 5 size presets: sm | md | lg | xl | full
 * - Exported sub-components: DialogContent, DialogHeader, DialogBody, DialogFooter
 * - Keyboard: ESC closes, focus trap via Radix
 * - a11y: aria-labelledby, aria-describedby via Radix
 */

import * as RadixDialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';
import { useTranslation } from '../../i18n/i18n';

const SIZE_CLASSES: Record<string, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  full: 'max-w-[calc(100vw-2rem)]',
};

function DialogOverlay() {
  return (
    <RadixDialog.Overlay
      className={cn(
        'fixed inset-0 z-[50] bg-bg-base/70 backdrop-blur-md',
        'data-[state=open]:animate-in data-[state=open]:fade-in-0',
        'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
        'duration-200',
      )}
    />
  );
}

export interface DialogContentProps {
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full';
  className?: string;
  hideClose?: boolean;
  dataTour?: string;
}

function DialogContent({
  children,
  size = 'md',
  className,
  hideClose = false,
  dataTour,
}: DialogContentProps) {
  const { lang } = useTranslation();

  return (
    <RadixDialog.Portal>
      <DialogOverlay />
      <RadixDialog.Content
        data-tour={dataTour}
        className={cn(
          'fixed left-1/2 top-1/2 z-[60] -translate-x-1/2 -translate-y-1/2',
          'w-[calc(100%-2rem)]',
          SIZE_CLASSES[size] ?? SIZE_CLASSES.md,
          'rounded-2xl border border-border-subtle ui-overlay-surface',
          'flex flex-col overflow-hidden',
          'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
          'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95',
          'duration-200',
          'max-sm:bottom-0 max-sm:left-0 max-sm:right-0 max-sm:top-auto max-sm:w-full max-sm:max-w-full',
          'max-sm:translate-x-0 max-sm:translate-y-0',
          'max-sm:rounded-b-none max-sm:rounded-t-2xl',
          'max-sm:data-[state=open]:slide-in-from-bottom-4',
          'max-sm:data-[state=closed]:slide-out-to-bottom-4',
          className,
        )}
      >
        {!hideClose && (
          <RadixDialog.Close
            className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center rounded-lg border border-border-subtle text-text-muted transition-colors hover:border-border-focus hover:bg-bg-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            aria-label={lang === 'it' ? 'Chiudi' : 'Close'}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </RadixDialog.Close>
        )}
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}

export interface DialogHeaderProps {
  title: string;
  description?: string;
  className?: string;
}

function DialogHeader({ title, description, className }: DialogHeaderProps) {
  return (
    <div className={cn('ui-overlay-bar border-b border-border-subtle px-5 py-4 pr-12', className)}>
      <RadixDialog.Title className="text-base font-semibold text-text-primary">
        {title}
      </RadixDialog.Title>
      {description && (
        <RadixDialog.Description className="mt-1 text-xs leading-relaxed text-text-muted">
          {description}
        </RadixDialog.Description>
      )}
    </div>
  );
}

export interface DialogBodyProps {
  children: ReactNode;
  className?: string;
  noScroll?: boolean;
}

function DialogBody({ children, className, noScroll = false }: DialogBodyProps) {
  return (
    <div
      className={cn(
        'p-5',
        !noScroll && 'overflow-y-auto max-h-[65vh]',
        className,
      )}
    >
      {children}
    </div>
  );
}

export interface DialogFooterProps {
  children: ReactNode;
  className?: string;
}

function DialogFooter({ children, className }: DialogFooterProps) {
  return (
    <div
      className={cn(
        'ui-overlay-bar flex items-center justify-end gap-2 border-t border-border-subtle px-5 py-3',
        className,
      )}
    >
      {children}
    </div>
  );
}

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;
export { DialogContent, DialogHeader, DialogBody, DialogFooter };
