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

  it('shows connector save errors and ends the saving state', async () => {
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
        return Promise.reject(new Error('Connector save failed.')) as never;
      }
      return Promise.resolve([]) as never;
    });
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await screen.findByRole('heading', { name: 'Connect and test your app' });

    const entryPoint = screen.getByRole('option', { name: /Upload outputs/ });
    await user.click(entryPoint);
    expect(entryPoint.getAttribute('aria-selected')).toBe('true');
    await screen.findByText('Upload outputs file *');
    const fileInput = screen
      .getByText('Upload outputs file *')
      .closest('label')
      ?.querySelector('input[type="file"]');
    if (!(fileInput instanceof HTMLInputElement)) {
      throw new Error('Upload file input was not rendered.');
    }
    await user.upload(
      fileInput,
      new File(['input,output\nhello,world'], 'outputs_good.csv', {
        type: 'text/csv',
      }),
    );
    await screen.findByText('Preview · first 1 rows');
    await user.type(screen.getByLabelText('Sample input'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Test call' }));
    await screen.findByText('Test succeeded');
    await user.click(screen.getByRole('button', { name: 'Save connector' }));

    expect(await screen.findByText('Connector save failed.')).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: 'Save connector' })
        .hasAttribute('disabled'),
    ).toBe(false);
  });

  it('shows all entry points and supports arrow and Enter selection', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    const listbox = await screen.findByRole('listbox', {
      name: 'Entry-point type',
    });
    const options = within(listbox).getAllByRole('option');
    expect(options).toHaveLength(13);
    expect(
      within(listbox).getByText(
        'Upload inputs and outputs you already generated',
      ),
    ).toBeTruthy();
    expect(
      (
        within(listbox).getByRole('option', {
          name: /Python function/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);

    listbox.focus();
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(
      within(listbox)
        .getByRole('option', { name: /Prompt App/ })
        .getAttribute('aria-selected'),
    ).toBe('true');
  });

  it('exposes private endpoint approval as an explicit boolean setting', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.type(await screen.findByLabelText('Project name *'), 'Demo');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await user.click(
      await screen.findByRole('option', { name: /HTTP endpoint/ }),
    );

    const approval = await screen.findByRole('checkbox', {
      name: /Allow private targets/,
    });
    expect((approval as HTMLInputElement).checked).toBe(false);
    await user.click(approval);
    expect((approval as HTMLInputElement).checked).toBe(true);
    expect(
      screen.getByText(/Only workspace owners or admins may authorize it/),
    ).toBeTruthy();
  });

  it('sends an optional provider outside UPLOAD_OUTPUTS settings for test and save', async () => {
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
      await screen.findByRole('option', { name: /Upload outputs/ }),
    );
    const fileInput = screen
      .getByText('Upload outputs file *')
      .closest('label')
      ?.querySelector('input[type="file"]');
    if (!(fileInput instanceof HTMLInputElement)) {
      throw new Error('Upload file input was not rendered.');
    }
    await user.upload(
      fileInput,
      new File(['input,output\nhello,world'], 'outputs_good.csv', {
        type: 'text/csv',
      }),
    );
    await screen.findByText('Preview · first 1 rows');
    await user.type(screen.getByLabelText('Sample input'), 'hello');
    await user.selectOptions(
      screen.getByLabelText('Provider (optional)'),
      provider.id,
    );
    await user.click(screen.getByRole('button', { name: 'Test call' }));
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
      settings: Record<string, unknown>;
    };
    const savePayload = JSON.parse(String(saveCall?.[1]?.body)) as {
      provider_id?: string;
      settings: Record<string, unknown>;
    };
    expect(testPayload.provider_id).toBe(provider.id);
    expect(testPayload.settings.provider_id).toBeUndefined();
    expect(savePayload.provider_id).toBe(provider.id);
    expect(savePayload.settings.provider_id).toBeUndefined();
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
    await user.click(await screen.findByRole('option', { name: /Prompt App/ }));
    await user.type(screen.getByLabelText(/System prompt/), 'Answer clearly.');
    const providerSelect = screen.getAllByLabelText('Provider *').pop();
    if (!providerSelect) throw new Error('Provider selection is missing.');
    await user.selectOptions(providerSelect, provider.id);
    await user.type(screen.getByLabelText('Sample input'), 'What is GreenLit?');
    await user.click(screen.getByRole('button', { name: 'Test call' }));
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

  it('labels the optional provider choice as not required', async () => {
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
      await screen.findByRole('option', { name: /Upload outputs/ }),
    );

    expect(
      screen.getByRole('option', { name: 'None (not required)' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('combobox', { name: 'Provider (optional)' }),
    ).toBeTruthy();
  });
});
