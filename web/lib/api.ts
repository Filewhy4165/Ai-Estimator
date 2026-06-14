const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export interface ApiError {
  detail: string;
  status?: number;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  private getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('access_token');
  }

  private getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('refresh_token');
  }

  setTokens(access: string, refresh: string): void {
    if (typeof window === 'undefined') return;
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
  }

  clearTokens(): void {
    if (typeof window === 'undefined') return;
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
  }

  private async refreshAccessToken(): Promise<boolean> {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) return false;

    try {
      const res = await fetch(`${this.baseUrl}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      this.setTokens(data.access_token, data.refresh_token || refreshToken);
      return true;
    } catch {
      return false;
    }
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
    retry = true,
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    // Don't set Content-Type for FormData — browser sets boundary automatically
    if (!(options.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401 && retry) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        return this.request<T>(path, options, false);
      }
      this.clearTokens();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      throw new Error('Session expired. Please log in again.');
    }

    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch { /* ignore parse error */ }
      const err: ApiError = { detail, status: res.status };
      throw err;
    }

    if (res.status === 204) return undefined as T;

    // Handle blob responses
    const contentType = res.headers.get('content-type');
    if (contentType && (contentType.includes('application/zip') || contentType.includes('text/csv') || contentType.includes('application/octet-stream'))) {
      return res.blob() as unknown as T;
    }

    return res.json();
  }

  // ─── Auth ───────────────────────────────────────────────────────────

  async register(data: { email: string; password: string; full_name: string; company_name?: string }) {
    return this.request<{ access_token: string; refresh_token: string; token_type: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async login(email: string, password: string) {
    return this.request<{ access_token: string; refresh_token: string; token_type: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }

  async getMe() {
    return this.request<{ id: string; email: string; full_name: string; company_name: string | null; role: string; plan: string; created_at: string }>('/auth/me');
  }

  async updateMe(data: { full_name?: string; company_name?: string }) {
    return this.request('/auth/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async changePassword(data: { current_password: string; new_password: string }) {
    return this.request('/auth/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async listApiKeys() {
    return this.request<Array<{ id: string; name: string; prefix: string; created_at: string; last_used_at: string | null }>>('/auth/api-keys');
  }

  async createApiKey(name: string) {
    return this.request<{ id: string; name: string; key: string; created_at: string }>('/auth/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  // ─── Jobs ───────────────────────────────────────────────────────────

  async listJobs(limit = 50, offset = 0) {
    return this.request<{ jobs: Job[]; total: number }>(`/v1/jobs?limit=${limit}&offset=${offset}`);
  }

  async getJob(id: string) {
    return this.request<Job>(`/v1/jobs/${id}`);
  }

  async analyze(files: File[], options?: { trades?: string[]; notes?: string }) {
    const formData = new FormData();
    for (const f of files) {
      formData.append('files', f);
    }
    if (options?.trades?.length) {
      formData.append('trades', JSON.stringify(options.trades));
    }
    if (options?.notes) {
      formData.append('notes', options.notes);
    }
    return this.request<{ job_id: string; status: string }>('/v1/analyze', {
      method: 'POST',
      body: formData,
    });
  }

  async cancelJob(id: string) {
    return this.request<{ job_id: string; status: string; message: string }>(`/v1/jobs/${id}/cancel`, {
      method: 'POST',
    });
  }

  async deleteJob(id: string) {
    return this.request<{ job_id: string; deleted: boolean }>(`/v1/jobs/${id}`, {
      method: 'DELETE',
    });
  }

  // ─── Takeoff ────────────────────────────────────────────────────────

  async getTakeoff(jobId: string) {
    return this.request<TakeoffResult>(`/v1/jobs/${jobId}/takeoff`);
  }

  async getReport(jobId: string) {
    return this.request<string>(`/v1/jobs/${jobId}/report`);
  }

  async exportCsv(jobId: string) {
    return this.request<Blob>(`/v1/jobs/${jobId}/export`, {
      method: 'POST',
    });
  }

  // ─── Metrics ────────────────────────────────────────────────────────

  async getMetrics() {
    return this.request('/v1/jobs/metrics');
  }

  // ─── Health ─────────────────────────────────────────────────────────

  async healthCheck() {
    return this.request<{ status: string; version: string }>('/health');
  }
}

// ─── Types ─────────────────────────────────────────────────────────────

export interface Job {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  updated_at: string;
  file_count?: number;
  file_names?: string[];
  trades?: string[];
  notes?: string;
  error_message?: string;
}

export interface TakeoffResult {
  job_id: string;
  trades: TradeTakeoff[];
  totals: CostTotals;
  generated_at: string;
}

export interface TradeTakeoff {
  trade: string;
  items: LineItem[];
  subtotal: number;
}

export interface LineItem {
  description: string;
  quantity: number;
  unit: string;
  unit_cost: number;
  total_cost: number;
  csi_code?: string;
  notes?: string;
}

export interface CostTotals {
  subtotal: number;
  markup: number;
  total: number;
  by_trade: Record<string, number>;
}

export const api = new ApiClient();
export default api;
