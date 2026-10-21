/** @vitest-environment jsdom */

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspaceProjects from './WorkspaceProjects';
import { apiRequest } from './api';
import { parseUploadRows } from './phase2Uploads';

vi.mock('./api', () => ({ apiRequest: vi.fn() }));
vi.mock('./DatasetStudio', () => ({ default: () => null }));
vi.mock('./phase2Uploads', () => ({ parseUploadRows: vi.fn() }));

const workspace = {
  id: 'workspace-1',
  name: 'Test workspace',
  slug: 'test-workspace',
  owner_id: 'user-1',
};

const rows = [{ input: 'hello', output: 'world' }];
const request = vi.mocked(apiRequest);

afterEach(cleanup);

function renderWorkspace() {
  return render(
    <WorkspaceProjects
      accessToken="test-access-token"
      userRole="owner"
      workspace={workspace}
    />,
  );
}

beforeEach(() => {
  request.mockReset();
  vi.mocked(parseUploadRows).mockResolvedValue(rows);
  request.mockImplementation((path, options = {}) => {
    const method = options.method ?? 'GET';
    if (path.endsWith('/entry-point-types'))
      return Promise.resolve([]) as never;
    if (path.endsWith('/projects') && method === 'GET') {
      return Promise.resolve([]) as never;
    }
    if (path.endsWith('/providers')) return Promise.resolve([]) as never;
    if (path.includes('/connectors') && method === 'GET') {
      return Promise.resolve([]) as never;
    }
    if (path.endsWith('/projects') && method === 'POST') {
      return Promise.resolve({
        id: 'project-1',
        name: 'Demo',
        description: '',
      }) as never;
    }
    if (path.endsWith('/test-call')) {
      return Promise.resolve({
        test_call_id: 'test-call-token',
        trace: { output: 'world' },
        raw_response: { output: 'world' },
        latency_ms: 1,
        detected_fields: ['output'],
        missing_fields: [],
        preview: rows,
      }) as never;
    }
    return Promise.resolve({ ok: true }) as never;
  });
});

describe('WorkspaceProjects', () => {
  it('ignores a double-click while creating a project', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');

    await user.dblClick(screen.getByRole('button', { name: 'Create project' }));

    await waitFor(() => {
      expect(
        request.mock.calls.filter(
          ([path, options]) =>
            path.endsWith('/projects') && options?.method === 'POST',
        ),
      ).toHaveLength(1);
    });
  });

  it('shows save errors and clears the saving state', async () => {
    const user = userEvent.setup();
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/providers')) return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.reject(
          new Error('A project with this name already exists.'),
        ) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect(
      await screen.findByText('A project with this name already exists.'),
    ).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: 'Create project' })
        .hasAttribute('disabled'),
    ).toBe(false);
  });

  it('explains duplicate connector names and ends the saving state', async () => {
    const user = userEvent.setup();
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/providers')) return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.resolve({
          id: 'project-1',
          name: 'Demo',
          description: '',
        }) as never;
      }
      if (path.endsWith('/connectors') && options.method === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/test-call')) {
        return Promise.resolve({
          test_call_id: 'test-call-token',
          trace: { output: 'world' },
          raw_response: { output: 'world' },
          latency_ms: 1,
          detected_fields: ['output'],
          missing_fields: [],
          preview: rows,
        }) as never;
      }
      if (path.endsWith('/connectors') && options.method === 'POST') {
        return Promise.reject(
          new Error(
            'A connector with this name already exists in this project.',
          ),
        ) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await screen.findByRole('heading', { name: 'Connect and test your app' });

    await user.click(
      screen.getByRole('button', {
        name: /I have my app's answers in a file/,
      }),
    );
    const fileInput = await screen.findByLabelText(/Outputs file/);
    await user.upload(
      fileInput,
      new File(['input,output\nhello,world'], 'outputs_good.csv', {
        type: 'text/csv',
      }),
    );
    await screen.findByText('Preview · first 1 rows');
    await user.type(screen.getByLabelText(/Sample input/), 'hello');
    await user.click(
      screen.getByRole('button', { name: 'Test with sample input' }),
    );
    await screen.findByText('Test succeeded');
    await user.click(screen.getByRole('button', { name: 'Save connector' }));

    expect(
      await screen.findByText(/That connector name is already in use/),
    ).toBeTruthy();
    expect(screen.getByText(/Choose a different connector name/)).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: 'Save connector' })
        .hasAttribute('disabled'),
    ).toBe(false);
  });

  it('shows three primary choices and keeps additional entry points collapsed', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect(
      screen.getByRole('heading', {
        name: 'How can GreenLit reach your application?',
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', {
        name: /I have my app's answers in a file/,
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', { name: /My app runs at a URL/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', {
        name: /I only have a prompt and a model/,
      }),
    ).toBeTruthy();
    const summary = screen.getByText('More ways (coming soon)');
    expect(summary.closest('details')?.open).toBe(false);
    await user.click(summary);
    const ragCard = screen.getByRole('button', { name: /Built-in RAG app/ });
    const agentCard = screen.getByRole('button', { name: /Built-in agent/ });
    const dockerCard = screen.getByRole('button', { name: /Docker image/ });
    expect((ragCard as HTMLButtonElement).disabled).toBe(false);
    expect((agentCard as HTMLButtonElement).disabled).toBe(false);
    expect((dockerCard as HTMLButtonElement).disabled).toBe(true);
  });

  it('exposes private endpoint approval as an explicit boolean setting', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await user.click(
      await screen.findByRole('button', { name: /My app runs at a URL/ }),
    );
    await user.click(screen.getByText('Advanced'));

    const approval = await screen.findByRole('checkbox', {
      name: /Allow private targets/,
    });
    expect((approval as HTMLInputElement).checked).toBe(false);
    await user.click(approval);
    expect((approval as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/workspace owner\/admin only/)).toBeTruthy();
  });

  it('does not send a provider for UPLOAD_OUTPUTS', async () => {
    const user = userEvent.setup();
    const provider = {
      id: 'provider-1',
      name: 'Local Ollama',
      provider_type: 'ollama',
      base_url: 'http://host.docker.internal:11434/v1',
      default_model: 'hermes3:8b',
      test_model: 'hermes3:8b',
      has_api_key: false,
    };
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.resolve({
          id: 'project-1',
          name: 'Demo',
          description: '',
        }) as never;
      }
      if (path.endsWith('/providers'))
        return Promise.resolve([provider]) as never;
      if (path.includes('/connectors') && options.method === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/test-call')) {
        return Promise.resolve({
          test_call_id: 'test-call-token',
          trace: { output: 'world' },
          raw_response: { output: 'world' },
          latency_ms: 1,
          detected_fields: ['output'],
          missing_fields: [],
          preview: rows,
        }) as never;
      }
      if (path.endsWith('/connectors') && options.method === 'POST') {
        return Promise.resolve({
          id: 'connector-1',
          name: 'Upload outputs',
          entry_point_type: 'UPLOAD_OUTPUTS',
        }) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    await user.click(
      await screen.findByRole('button', {
        name: /I have my app's answers in a file/,
      }),
    );
    const fileInput = await screen.findByLabelText(/Outputs file/);
    await user.upload(
      fileInput,
      new File(['input,output\nhello,world'], 'outputs_good.csv', {
        type: 'text/csv',
      }),
    );
    await screen.findByText('Preview · first 1 rows');
    await user.type(screen.getByLabelText(/Sample input/), 'hello');
    await user.click(
      screen.getByRole('button', { name: 'Test with sample input' }),
    );
    await screen.findByText('Test succeeded');
    await user.click(screen.getByRole('button', { name: 'Save connector' }));
    await screen.findByText('Connector saved.');

    const testCall = request.mock.calls.find(([path]) =>
      path.endsWith('/test-call'),
    );
    const saveCall = request.mock.calls.find(
      ([path, options]) =>
        path.endsWith('/connectors') && options?.method === 'POST',
    );
    const testPayload = JSON.parse(String(testCall?.[1]?.body)) as {
      provider_id?: string;
      model?: string;
      settings: Record<string, unknown>;
      credentials?: Record<string, string>;
    };
    const savePayload = JSON.parse(String(saveCall?.[1]?.body)) as {
      provider_id?: string;
      model?: string;
      settings: Record<string, unknown>;
      credentials?: Record<string, string>;
    };
    expect(testPayload.provider_id).toBeUndefined();
    expect(testPayload.model).toBeUndefined();
    expect(testPayload.settings.provider_id).toBeUndefined();
    expect(testPayload.credentials).toBeUndefined();
    expect(savePayload.provider_id).toBeUndefined();
    expect(savePayload.model).toBeUndefined();
    expect(savePayload.settings.provider_id).toBeUndefined();
    expect(savePayload.credentials).toBeUndefined();
  });

  it('keeps built-in provider and model out of entry-point settings', async () => {
    const user = userEvent.setup();
    const provider = {
      id: 'provider-1',
      name: 'Workspace default',
      provider_type: 'ollama',
      default_model: 'hermes3:8b',
      test_model: 'hermes3:8b',
      has_api_key: false,
    };
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.resolve({
          id: 'project-1',
          name: 'Demo',
          description: '',
        }) as never;
      }
      if (path.endsWith('/providers'))
        return Promise.resolve([provider]) as never;
      if (path.includes('/connectors') && options.method === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/test-call')) {
        return Promise.resolve({
          test_call_id: 'test-call-token',
          trace: { output: 'world' },
          raw_response: { output: 'world' },
          latency_ms: 1,
          detected_fields: ['output'],
          missing_fields: [],
        }) as never;
      }
      if (path.endsWith('/connectors') && options.method === 'POST') {
        return Promise.resolve({
          id: 'connector-1',
          name: 'Prompt App',
          entry_point_type: 'PROMPT_APP',
        }) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await user.click(
      await screen.findByRole('button', {
        name: /I only have a prompt and a model/,
      }),
    );
    await user.type(screen.getByLabelText(/System prompt/), 'Answer clearly.');
    await user.type(screen.getByLabelText('Sample input'), 'What is GreenLit?');
    await user.click(
      screen.getByRole('button', { name: 'Test with sample input' }),
    );
    await screen.findByText('Test succeeded');
    await user.click(screen.getByRole('button', { name: 'Save connector' }));
    await screen.findByText('Connector saved.');

    const testCall = request.mock.calls.find(([path]) =>
      path.endsWith('/test-call'),
    );
    const saveCall = request.mock.calls.find(
      ([path, options]) =>
        path.endsWith('/connectors') && options?.method === 'POST',
    );
    for (const call of [testCall, saveCall]) {
      const payload = JSON.parse(String(call?.[1]?.body)) as {
        provider_id?: string;
        model?: string;
        settings: Record<string, unknown>;
      };
      expect(payload.provider_id).toBe(provider.id);
      expect(payload.model).toBe('hermes3:8b');
      expect(payload.settings.provider_id).toBeUndefined();
      expect(payload.settings.model).toBeUndefined();
    }
  });

  it('sends an HTTP sample with an allow-listed payload and displays its response', async () => {
    const user = userEvent.setup();
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.resolve({
          id: 'project-1',
          name: 'Demo',
          description: '',
        }) as never;
      }
      if (path.endsWith('/providers')) return Promise.resolve([]) as never;
      if (path.includes('/connectors') && options.method === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/test-call')) {
        return Promise.resolve({
          test_call_id: 'test-call-token',
          trace: { output: 'hello back' },
          raw_response: { data: { answer: 'hello back' } },
          latency_ms: 42,
          detected_fields: ['output'],
          missing_fields: [],
        }) as never;
      }
      if (path.endsWith('/connectors') && options.method === 'POST') {
        return Promise.resolve({
          id: 'connector-http',
          name: 'My app',
          entry_point_type: 'HTTP_ENDPOINT',
        }) as never;
      }
      return Promise.resolve([]) as never;
    });

    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await user.click(
      await screen.findByRole('button', { name: /My app runs at a URL/ }),
    );
    await user.clear(screen.getByLabelText('Connector name *'));
    await user.type(screen.getByLabelText('Connector name *'), 'My app');
    await user.type(
      screen.getByLabelText('App URL *'),
      'https://app.example.com/run',
    );
    await user.type(screen.getByLabelText('Sample input'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send sample input' }));

    expect(await screen.findByText('Test succeeded')).toBeTruthy();
    expect(screen.getByText('hello back')).toBeTruthy();
    expect(screen.getByText('42 ms')).toBeTruthy();
    expect(screen.getByText('Raw response')).toBeTruthy();

    const testCall = request.mock.calls.find(([path]) =>
      path.endsWith('/test-call'),
    );
    const payload = JSON.parse(String(testCall?.[1]?.body)) as {
      provider_id?: string;
      model?: string;
      settings: Record<string, unknown>;
    };
    expect(payload.provider_id).toBeUndefined();
    expect(payload.model).toBeUndefined();
    expect(payload.settings.output_field).toBe('output');
    expect(payload.settings.allow_private_targets).toBe(false);
  });

  it('does not display provider selection for uploaded outputs', async () => {
    const user = userEvent.setup();
    request.mockImplementation((path, options = {}) => {
      if (path.endsWith('/entry-point-types'))
        return Promise.resolve([]) as never;
      if (path.endsWith('/projects') && (options.method ?? 'GET') === 'GET') {
        return Promise.resolve([]) as never;
      }
      if (path.endsWith('/projects') && options.method === 'POST') {
        return Promise.resolve({
          id: 'project-1',
          name: 'Demo',
          description: '',
        }) as never;
      }
      if (path.endsWith('/providers')) {
        return Promise.resolve([
          {
            id: 'provider-1',
            name: 'Local Ollama',
            provider_type: 'ollama',
            has_api_key: false,
          },
        ]) as never;
      }
      if (path.includes('/connectors') && options.method === 'GET') {
        return Promise.resolve([]) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await user.click(
      await screen.findByRole('button', {
        name: /I have my app's answers in a file/,
      }),
    );

    const connectorSection = screen
      .getByRole('heading', {
        name: 'How can GreenLit reach your application?',
      })
      .closest('section');
    if (!connectorSection) throw new Error('Connector section was not found.');
    expect(within(connectorSection).queryByLabelText(/Provider/)).toBeNull();
  });
});
