import clsx from 'clsx';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
  animation?: 'pulse' | 'wave' | 'none';
}

export function Skeleton({
  className,
  variant = 'text',
  width,
  height,
  animation = 'pulse',
}: SkeletonProps) {
  const baseClasses = 'bg-gray-700';

  const variantClasses = {
    text: 'rounded',
    circular: 'rounded-full',
    rectangular: 'rounded-md',
  };

  const animationClasses = {
    pulse: 'animate-pulse',
    wave: 'animate-shimmer',
    none: '',
  };

  const style: React.CSSProperties = {};
  if (width) style.width = typeof width === 'number' ? `${width}px` : width;
  if (height) style.height = typeof height === 'number' ? `${height}px` : height;

  return (
    <div
      className={clsx(
        baseClasses,
        variantClasses[variant],
        animationClasses[animation],
        className
      )}
      style={style}
    />
  );
}

// Pre-built skeleton components for common use cases
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={clsx('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          variant="text"
          height={16}
          className={i === lines - 1 ? 'w-3/4' : 'w-full'}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={clsx('bg-gray-800 rounded-lg p-4 space-y-4', className)}>
      <Skeleton variant="rectangular" height={120} className="w-full" />
      <Skeleton variant="text" height={20} className="w-3/4" />
      <Skeleton variant="text" height={16} className="w-1/2" />
    </div>
  );
}

export function SkeletonGrid({ rows = 7, cols = 7, className }: { rows?: number; cols?: number; className?: string }) {
  return (
    <div className={clsx('grid gap-1', className)} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {Array.from({ length: rows * cols }).map((_, i) => (
        <Skeleton
          key={i}
          variant="rectangular"
          className="aspect-square"
        />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 4, className }: { rows?: number; cols?: number; className?: string }) {
  return (
    <div className={clsx('space-y-2', className)}>
      {/* Header */}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} variant="text" height={20} />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {Array.from({ length: cols }).map((_, colIndex) => (
            <Skeleton key={colIndex} variant="text" height={16} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonButton({ className }: { className?: string }) {
  return (
    <Skeleton variant="rectangular" height={36} className={clsx('w-24', className)} />
  );
}

// Level Browser Skeleton
export function SkeletonLevelBrowser({ itemCount = 5 }: { itemCount?: number }) {
  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Skeleton variant="text" width={100} height={20} />
        <Skeleton variant="rectangular" width={80} height={32} />
      </div>
      {/* Level items */}
      {Array.from({ length: itemCount }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 p-2 bg-gray-800 rounded-lg">
          <Skeleton variant="rectangular" width={48} height={48} />
          <div className="flex-1 space-y-2">
            <Skeleton variant="text" height={16} className="w-2/3" />
            <Skeleton variant="text" height={12} className="w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

// Difficulty Panel Skeleton
export function SkeletonDifficultyPanel() {
  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Skeleton variant="text" width={120} height={24} />
        <Skeleton variant="rectangular" width={100} height={32} />
      </div>
      {/* Score Display */}
      <div className="flex items-center justify-center gap-4">
        <Skeleton variant="circular" width={80} height={80} />
        <div className="space-y-2">
          <Skeleton variant="text" width={60} height={24} />
          <Skeleton variant="text" width={100} height={16} />
        </div>
      </div>
      {/* Metrics */}
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton variant="text" height={14} className="w-1/2" />
            <Skeleton variant="text" height={20} className="w-3/4" />
          </div>
        ))}
      </div>
    </div>
  );
}
