import { Component, lazy, Suspense, type ComponentType, type ReactNode } from 'react';

/**
 * lazy 탭 로더 + 오류 경계. 청크 로드 실패(네트워크 단절·배포로 청크 소실) 시 앱 전체가 내려가지 않고
 * 해당 탭만 "다시 불러오기" 버튼을 보여준다. React.lazy 는 거부된 Promise 를 캐시하므로
 * 재시도 때 lazy 컴포넌트를 새로 만든다.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyTab<T extends ComponentType<any>>(factory: () => Promise<{ default: T }>): T {
  let Inner = lazy(factory);
  const fallback: ReactNode = <div className="text-center text-gray-500 py-10">패널 로딩 중…</div>;

  class Boundary extends Component<{ forward: object }, { failed: boolean }> {
    state = { failed: false };
    static getDerivedStateFromError() { return { failed: true }; }
    componentDidCatch(err: unknown) { console.error('[lazyTab] 패널 로드 실패:', err); }
    retry = () => { Inner = lazy(factory); this.setState({ failed: false }); };
    render() {
      if (this.state.failed) {
        return (
          <div className="text-center text-gray-400 py-10">
            <div className="mb-3">패널을 불러오지 못했습니다 (네트워크 또는 새 배포).</div>
            <button className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded" onClick={this.retry}>다시 불러오기</button>
          </div>
        );
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const C = Inner as unknown as ComponentType<any>;
      return <Suspense fallback={fallback}><C {...this.props.forward} /></Suspense>;
    }
  }
  const Wrapper = (props: object) => <Boundary forward={props} />;
  return Wrapper as unknown as T;
}
