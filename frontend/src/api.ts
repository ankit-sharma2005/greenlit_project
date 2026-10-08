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
  detail?: unknown;
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
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
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
      if (typeof body.detail === 'string') {
        message = body.detail;
      } else if (body.detail && typeof body.detail === 'object') {
        const detail = body.detail as {
          message?: unknown;
          validation_errors?: unknown;
        };
        if (typeof detail.message === 'string') {
          message = detail.message;
          if (Array.isArray(detail.validation_errors)) {
            const errors = detail.validation_errors
              .map((error: unknown) => {
                if (!error || typeof error !== 'object') return '';
                const row = error as { row?: unknown; message?: unknown };
                if (typeof row.message !== 'string') return '';
                return `${row.row ? `Row ${String(row.row)}: ` : ''}${row.message}`;
              })
              .filter(Boolean);
            if (errors.length) message += ` — ${errors.join('; ')}`;
          }
        }
      }
      if (message.startsWith('Request failed') && body.error?.message) {
        message = body.error.message;
      }
    } catch {
      // Preserve the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function streamApiEvents<T>(
  path: string,
  accessToken: string,
  onEvent: (event: T) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: 'include',
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Event stream failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = '';
  while (true) {
    const { done, value } = await reader.read();
    buffered += decoder.decode(value, { stream: !done });
    const frames = buffered.split('\n\n');
    buffered = frames.pop() ?? '';
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (data) onEvent(JSON.parse(data) as T);
    }
    if (done) return;
  }
}
