"""Test that shared connector function honours timeout and body template."""

from __future__ import annotations

from unittest.mock import patch

from app.services.connectors import HttpConnector


def test_shared_function_honours_timeout_and_template():
    connector = HttpConnector(allow_private=True)

    with patch.object(connector.client, "request") as mock_request:

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"answer": "hello"}

        mock_request.return_value = FakeResponse()

        trace = connector.render_and_send(
            url="http://example.com/test",
            body_template='{"question": {{input}}}',
            input_text="Hi",
            timeout_seconds=42,
        )

        # Verify timeout was passed
        call_kwargs = mock_request.call_args
        assert call_kwargs[1].get("timeout") == 42 or call_kwargs.kwargs.get("timeout") == 42
        # Verify body template was used correctly
        assert call_kwargs[1].get("json") == {"question": "Hi"}
        assert trace.output == "hello"
