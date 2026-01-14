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

// Request interceptor for logging
apiClient.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
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
