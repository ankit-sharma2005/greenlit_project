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

const authExpiredMessage = 'Session expired, please log in again';

async function fetchWithAuthRefresh(
  path: string,
  options: RequestInit,
  headers: Headers,
  accessToken?: string,
): Promise<Response> {
  const send = () =>
    fetch(`${apiBaseUrl}/api/v1${path}`, {
      ...options,
      headers,
      credentials: 'include',
    });
  let response = await send();
  if (response.status !== 401 || !accessToken || path === '/auth/refresh') {
    return response;
  }

  let nextToken = '';
  try {
    const refreshed = await fetch(`${apiBaseUrl}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    if (refreshed.ok) {
      const result = (await refreshed.json()) as { access_token?: unknown };
      if (typeof result.access_token === 'string') {
        nextToken = result.access_token;
      }
    }
  } catch {
    nextToken = '';
  }
  if (!nextToken) {
    window.dispatchEvent(new CustomEvent('greenlit:auth-expired'));
    throw new Error(authExpiredMessage);
  }

  headers.set('Authorization', `Bearer ${nextToken}`);
  window.dispatchEvent(
    new CustomEvent('greenlit:token-refreshed', {
      detail: { accessToken: nextToken },
    }),
  );
  response = await send();
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('greenlit:auth-expired'));
    throw new Error(authExpiredMessage);
  }
  return response;
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

  const response = await fetchWithAuthRefresh(
    path,
    options,
    headers,
    accessToken,
  );

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
          upstream_status_code?: unknown;
          upstream_body?: unknown;
        };
        if (typeof detail.message === 'string') {
          message = detail.message;
          if (typeof detail.upstream_status_code === 'number') {
            message = `Upstream HTTP ${detail.upstream_status_code}: ${message}`;
          }
          if (
            typeof detail.upstream_body === 'string' &&
            detail.upstream_body.length > 0 &&
            !message.includes(detail.upstream_body)
          ) {
            message += ` — ${detail.upstream_body}`;
          }
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

export async function downloadApiFile(
  path: string,
  accessToken?: string,
  fallbackFilename = 'greenlit-report',
): Promise<void> {
  const headers = new Headers();
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }
  const response = await fetchWithAuthRefresh(path, {}, headers, accessToken);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ApiError;
      if (typeof body.detail === 'string') message = body.detail;
      else if (body.error?.message) message = body.error.message;
    } catch {
      // Preserve the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }

  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1];
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename ?? fallbackFilename;
  document.body.append(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

export async function streamApiEvents<T>(
  path: string,
  accessToken: string,
  onEvent: (event: T) => void,
  signal: AbortSignal,
): Promise<void> {
  const headers = new Headers({ Authorization: `Bearer ${accessToken}` });
  const response = await fetchWithAuthRefresh(
    path,
    { signal },
    headers,
    accessToken,
  );
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
