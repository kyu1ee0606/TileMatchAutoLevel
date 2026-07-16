import axios from 'axios';

// API base URL: use environment variable in production, proxy in development
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 second timeout
});

// [원격 연산 라우팅] 무거운 컴퓨트 엔드포인트만 원격(Cloud Run 등)으로 오프로드.
// localStorage 'remote_compute_url' 있으면 그 URL로, 없으면 로컬(현행). 런타임 토글.
// 저장/조회(템플릿·배치·컨셉·패턴)는 항상 로컬 → 원격 휘발성에 의한 데이터 소실 방지.
export const REMOTE_COMPUTE_KEY = 'remote_compute_url';
const REMOTE_COMPUTE_PREFIXES = ['/generate', '/rl-sim', '/analyze/autoplay', '/analyze/solvability'];
export const getRemoteComputeUrl = (): string => {
  try { return (localStorage.getItem(REMOTE_COMPUTE_KEY) || '').trim().replace(/\/$/, ''); } catch { return ''; }
};

// Request interceptor for logging (suppress high-frequency generation endpoints)
const LOG_SUPPRESSED_URLS = ['/generate', '/generate/validated'];

apiClient.interceptors.request.use(
  (config) => {
    // 무거운 컴퓨트 → 원격(설정 시). 저장/조회는 로컬 유지.
    const remote = getRemoteComputeUrl();
    if (remote && REMOTE_COMPUTE_PREFIXES.some(p => config.url?.startsWith(p))) {
      config.baseURL = `${remote}/api`;
    }
    if (!LOG_SUPPRESSED_URLS.some(u => config.url?.startsWith(u))) {
      console.log(`[API] ${config.method?.toUpperCase()} ${config.url}${config.baseURL !== API_BASE_URL ? ' →원격' : ''}`);
    }
    return config;
  },
  (error) => {
    console.error('[API] Request error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response) {
      // Server responded with error
      console.error('[API] Response error:', error.response.status, error.response.data);
    } else if (error.request) {
      // Request made but no response
      console.error('[API] No response received:', error.request);
    } else {
      // Request setup error
      console.error('[API] Request setup error:', error.message);
    }
    return Promise.reject(error);
  }
);

export default apiClient;
