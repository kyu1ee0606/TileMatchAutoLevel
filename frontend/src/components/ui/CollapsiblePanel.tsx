import { useState, ReactNode } from 'react';
import clsx from 'clsx';

interface CollapsiblePanelProps {
  title: string;
  icon?: string;
  defaultCollapsed?: boolean;
  headerRight?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function CollapsiblePanel({
  title,
  icon,
  defaultCollapsed = false,
  headerRight,
  children,
  className,
}: CollapsiblePanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);

  return (
    <div
      className={clsx(
        'flex flex-col bg-gray-800 rounded-xl shadow-lg border border-gray-700',
        className
      )}
    >
      {/* Header - always visible */}
      <div className="flex items-center justify-between p-4 w-full rounded-t-xl">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex items-center gap-2 text-left hover:opacity-80 transition-opacity"
        >
          <span
            className={clsx(
              'text-gray-400 transition-transform duration-200',
              isCollapsed ? '-rotate-90' : 'rotate-0'
            )}
          >
            ▼
          </span>
          <h2 className="text-lg font-bold text-gray-100">
            {icon && <span className="mr-2">{icon}</span>}
            {title}
          </h2>
        </button>
        {headerRight && <div>{headerRight}</div>}
      </div>

      {/* Content - collapsible */}
      <div
        className={clsx(
          'overflow-hidden transition-all duration-200',
          isCollapsed ? 'max-h-0' : 'max-h-[2000px]'
        )}
      >
        <div className="p-4 pt-0">{children}</div>
      </div>
    </div>
  );
}
