import { useState, useEffect, useRef } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import clsx from 'clsx';

interface LayerSelectorProps {
  className?: string;
}

export function LayerSelector({ className }: LayerSelectorProps) {
  const { level, selectedLayer, setSelectedLayer } = useLevelStore();
  const [isAnimating, setIsAnimating] = useState(false);
  const [animationDirection, setAnimationDirection] = useState<'up' | 'down' | null>(null);
  const prevLayerRef = useRef(selectedLayer);

  const layers = Array.from({ length: level.layer }, (_, i) => i);

  // Track layer changes for animation direction
  useEffect(() => {
    if (prevLayerRef.current !== selectedLayer) {
      setAnimationDirection(selectedLayer > prevLayerRef.current ? 'up' : 'down');
      setIsAnimating(true);
      prevLayerRef.current = selectedLayer;

      const timer = setTimeout(() => {
        setIsAnimating(false);
        setAnimationDirection(null);
      }, 300);

      return () => clearTimeout(timer);
    }
  }, [selectedLayer]);

  const handleLayerChange = (layerIdx: number) => {
    if (layerIdx !== selectedLayer) {
      setSelectedLayer(layerIdx);
    }
  };

  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-gray-300">레이어 선택</label>
        {isAnimating && (
          <span className={clsx(
            'text-xs px-1.5 py-0.5 rounded animate-pulse',
            animationDirection === 'up' ? 'bg-green-900 text-green-300' : 'bg-blue-900 text-blue-300'
          )}>
            {animationDirection === 'up' ? '▲' : '▼'}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {layers.map((layerIdx) => {
          const layerKey = `layer_${layerIdx}` as `layer_${number}`;
          const layerData = level[layerKey];
          const tileCount = layerData?.tiles ? Object.keys(layerData.tiles).length : 0;
          const hasContent = tileCount > 0;
          const isSelected = selectedLayer === layerIdx;

          return (
            <button
              key={layerIdx}
              onClick={() => handleLayerChange(layerIdx)}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-md transition-all duration-200',
                isSelected
                  ? 'bg-primary-600 text-white scale-105 shadow-lg shadow-primary-600/30'
                  : hasContent
                  ? 'bg-primary-900 text-primary-200 hover:bg-primary-800 hover:scale-102'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:scale-102'
              )}
            >
              L{layerIdx}
              {hasContent && (
                <span className="ml-1 text-xs opacity-75">({tileCount})</span>
              )}
            </button>
          );
        })}
      </div>
      <div className={clsx(
        'text-xs text-gray-400 transition-all duration-200',
        isAnimating && 'text-primary-400'
      )}>
        현재: Layer {selectedLayer} ({level[`layer_${selectedLayer}` as `layer_${number}`]?.col || 0} x{' '}
        {level[`layer_${selectedLayer}` as `layer_${number}`]?.row || 0})
      </div>
    </div>
  );
}
