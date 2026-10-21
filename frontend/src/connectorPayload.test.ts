import { describe, expect, it } from 'vitest';
import { buildConnectorPayload } from './connectorPayload';

describe('buildConnectorPayload', () => {
  it('builds an upload payload without provider or model fields', () => {
    const payload = buildConnectorPayload('UPLOAD_OUTPUTS', {
      settings: {
        rows: [{ input: 'hello', output: 'world' }],
        input_field: 'input',
        output_field: 'output',
        provider_id: 'not-a-setting',
        model: 'not-a-setting',
        extra: true,
      },
      input: 'hello',
      provider_id: 'provider-1',
      model: 'model-1',
      credentials: { api_key: 'secret' },
    });

    expect(payload).toEqual({
      entry_point_type: 'UPLOAD_OUTPUTS',
      settings: {
        rows: [{ input: 'hello', output: 'world' }],
        input_field: 'input',
        output_field: 'output',
      },
      input: 'hello',
    });
  });

  it('builds an HTTP payload with credentials but no provider or model', () => {
    const payload = buildConnectorPayload('HTTP_ENDPOINT', {
      settings: {
        url: 'https://app.example.com/run',
        method: 'POST',
        request_body_template: '{"input": {{input}}}',
        output_field: 'data.answer',
        timeout_seconds: 15,
        provider_id: 'not-a-setting',
      },
      credentials: { api_key: 'secret' },
      provider_id: 'provider-1',
      model: 'model-1',
      input: 'hello',
    });

    expect(payload).toEqual({
      entry_point_type: 'HTTP_ENDPOINT',
      settings: {
        url: 'https://app.example.com/run',
        method: 'POST',
        request_body_template: '{"input": {{input}}}',
        output_field: 'data.answer',
        timeout_seconds: 15,
      },
      credentials: { api_key: 'secret' },
      input: 'hello',
    });
  });

  it('builds a prompt payload with provider and model only at top level', () => {
    const payload = buildConnectorPayload('PROMPT_APP', {
      settings: {
        system_prompt: 'Answer clearly.',
        temperature: 0,
        provider_id: 'not-a-setting',
        model: 'not-a-setting',
      },
      provider_id: 'provider-1',
      model: 'model-1',
      input: 'hello',
    });

    expect(payload).toEqual({
      entry_point_type: 'PROMPT_APP',
      settings: { system_prompt: 'Answer clearly.', temperature: 0 },
      provider_id: 'provider-1',
      model: 'model-1',
      input: 'hello',
    });
  });
});
