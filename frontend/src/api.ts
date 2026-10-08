const apiBaseUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export interface User {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  owner_id: string;
}

interface ApiError {
  detail?: string;
  error?: {
    message?: string;
  };
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  accessToken?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

  const response = await fetch(`${apiBaseUrl}/api/v1${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ApiError;
      message = body.detail ?? body.error?.message ?? message;
    } catch {
      // Preserve the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}
