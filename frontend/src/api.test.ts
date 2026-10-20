/** @vitest-environment jsdom */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest, downloadApiFile } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('apiRequest authentication refresh', () => {
  it('refreshes once and retries a request after a 401', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'refreshed-token' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiRequest('/projects', {}, 'expired-token')).resolves.toEqual(
      {
        ok: true,
      },
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('signals expiry and reports a useful error when refresh fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);
    const expired = vi.fn();
    window.addEventListener('greenlit:auth-expired', expired);

    await expect(apiRequest('/projects', {}, 'expired-token')).rejects.toThrow(
      'Session expired, please log in again',
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(expired).toHaveBeenCalledTimes(1);

    window.removeEventListener('greenlit:auth-expired', expired);
  });
});

describe('downloadApiFile', () => {
  it('uses authenticated fetch and downloads the server-provided filename', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('report bytes', {
        status: 200,
        headers: {
          'Content-Disposition': 'attachment; filename="run-report.pdf"',
          'Content-Type': 'application/pdf',
        },
      }),
    );
    const createObjectURL = vi.fn(() => 'blob:report');
    const revokeObjectURL = vi.fn();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    await downloadApiFile('/runs/run-id/report?format=pdf', 'access-token');

    const request = fetchMock.mock.calls[0];
    const options = request[1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.get('Authorization')).toBe('Bearer access-token');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[download="run-report.pdf"]')).toBeNull();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report');
  });

  it('propagates a useful server error rather than downloading it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Evaluation run not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(downloadApiFile('/runs/missing/report')).rejects.toThrow(
      'Evaluation run not found',
    );
  });
});
