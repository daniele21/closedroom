import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { cn } from '../utils/cn';
import { useTranslation } from '../i18n/i18n';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastMessage {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const { lang } = useTranslation();

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev.filter((toast) => toast.message !== message || toast.type !== type), { id, message, type }]);

    // Auto-remove toast after 4 seconds
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  // Expose to window for backward compatibility with non-React legacy scripts if needed
  useEffect(() => {
    (window as any).Toast = {
      show: (msg: string, t?: ToastType) => showToast(msg, t || 'info'),
    };
    return () => {
      delete (window as any).Toast;
    };
  }, [showToast]);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-4 left-4 right-4 z-50 flex max-h-[40vh] flex-col gap-2 overflow-y-auto overscroll-contain pointer-events-none sm:left-auto sm:w-96" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.type === 'error' ? 'alert' : 'status'}
            onClick={() => removeToast(toast.id)}
            className={cn(
              'p-4 rounded-xl shadow-lg border text-sm font-medium flex items-center justify-between gap-3 pointer-events-auto cursor-pointer animate-in fade-in slide-in-from-top-4 duration-200',
              {
                'bg-bg-elevated border-success text-success': toast.type === 'success',
                'bg-bg-elevated border-danger text-danger': toast.type === 'error',
                'bg-bg-elevated border-warning text-warning': toast.type === 'warning',
                'bg-bg-elevated border-info text-info': toast.type === 'info',
              }
            )}
          >
            <span>{toast.message}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                removeToast(toast.id);
              }}
              type="button"
              aria-label={lang === 'it' ? 'Chiudi notifica' : 'Dismiss notification'}
              className="shrink-0 rounded-md px-2 py-1 text-text-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus transition-colors cursor-pointer"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
