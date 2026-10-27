"""Test connectors against fake app cases."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.connectors import ConnectorError, HttpConnector


class FastHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"answer": "fast response"}).encode())

    def log_message(self, *args):
        pass


class SlowHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        time.sleep(30)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"answer": "slow"}).encode())

    def log_message(self, *args):
        pass


class WrongKeyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"response": "wrong key"}).encode())

    def log_message(self, *args):
        pass


class NotFoundHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "not found"}).encode())

    def log_message(self, *args):
        pass


class ForbiddenHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        self.send_response(403)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "forbidden"}).encode())

    def log_message(self, *args):
        pass


class InvalidJSONHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b"not json")

    def log_message(self, *args):
        pass


def test_fast_app():
    server = HTTPServer(("localhost", 0), FastHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace = connector.render_and_send(
            url=f"http://localhost:{port}/test",
            body_template='{"question": {{input}}}',
            input_text="test",
            timeout_seconds=5,
        )
        assert trace.output == "fast response"
    finally:
        server.shutdown()


def test_slow_app_30s():
    server = HTTPServer(("localhost", 0), SlowHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        with pytest.raises(ConnectorError) as exc:
            connector.render_and_send(
                url=f"http://localhost:{port}/test",
                body_template='{"question": {{input}}}',
                input_text="test",
                timeout_seconds=1,
            )
        assert exc.value.code == "timeout"
    finally:
        server.shutdown()


def test_wrong_answer_key():
    server = HTTPServer(("localhost", 0), WrongKeyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace = connector.render_and_send(
            url=f"http://localhost:{port}/test",
            body_template='{"question": {{input}}}',
            input_text="test",
            timeout_seconds=5,
        )
        # Should auto-detect 'response' key
        assert trace.output == "wrong key"
    finally:
        server.shutdown()


def test_404():
    server = HTTPServer(("localhost", 0), NotFoundHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        with pytest.raises(ConnectorError) as exc:
            connector.render_and_send(
                url=f"http://localhost:{port}/test",
                body_template='{"question": {{input}}}',
                input_text="test",
                timeout_seconds=5,
            )
        assert exc.value.code == "not_found"
    finally:
        server.shutdown()


def test_403_wrong_key():
    server = HTTPServer(("localhost", 0), ForbiddenHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        with pytest.raises(ConnectorError) as exc:
            connector.render_and_send(
                url=f"http://localhost:{port}/test",
                body_template='{"question": {{input}}}',
                input_text="test",
                timeout_seconds=5,
            )
        assert exc.value.code == "auth_error"
    finally:
        server.shutdown()


def test_invalid_json():
    server = HTTPServer(("localhost", 0), InvalidJSONHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        with pytest.raises(ConnectorError) as exc:
            connector.render_and_send(
                url=f"http://localhost:{port}/test",
                body_template='{"question": {{input}}}',
                input_text="test",
                timeout_seconds=5,
            )
        assert exc.value.code == "invalid_json"
    finally:
        server.shutdown()


def test_timeout():
    server = HTTPServer(("localhost", 0), SlowHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        with pytest.raises(ConnectorError) as exc:
            connector.render_and_send(
                url=f"http://localhost:{port}/test",
                body_template='{"question": {{input}}}',
                input_text="test",
                timeout_seconds=1,
            )
        assert "increase the timeout" in str(exc.value).lower() or exc.value.code == "timeout"
    finally:
        server.shutdown()


def test_private_target_blocked():
    from app.utils.request_client import BlockedPrivateURLError

    connector = HttpConnector(allow_private=False)
    with pytest.raises((ConnectorError, BlockedPrivateURLError, Exception)):
        connector.render_and_send(
            url="http://192.168.1.1/test",
            body_template='{"question": {{input}}}',
            input_text="test",
            timeout_seconds=5,
        )


class QuestionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if "question" in data:
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"answer": "ok1"}).encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


class InputHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if "input" in data:
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"answer": "ok2"}).encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


class QueryHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if "query" in data:
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"answer": "ok3"}).encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


class OpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if "messages" in data:
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok4"}}]}).encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


def test_autodetect_question():
    server = HTTPServer(("localhost", 0), QuestionHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace, template, _ans_path, _ctx_path = connector.auto_detect(
            url=f"http://localhost:{port}/test", input_text="hi", timeout_seconds=5
        )
        assert trace.output == "ok1"
        assert '"question"' in template
    finally:
        server.shutdown()


def test_autodetect_input():
    server = HTTPServer(("localhost", 0), InputHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace, _template, _ans_path, _ctx_path = connector.auto_detect(
            url=f"http://localhost:{port}/test", input_text="hi", timeout_seconds=5
        )
        assert trace.output == "ok2"
    finally:
        server.shutdown()


def test_autodetect_query():
    server = HTTPServer(("localhost", 0), QueryHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace, _template, _ans_path, _ctx_path = connector.auto_detect(
            url=f"http://localhost:{port}/test", input_text="hi", timeout_seconds=5
        )
        assert trace.output == "ok3"
    finally:
        server.shutdown()


def test_autodetect_openai_shape():
    server = HTTPServer(("localhost", 0), OpenAIHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace, _template, ans_path, _ctx_path = connector.auto_detect(
            url=f"http://localhost:{port}/test", input_text="hi", timeout_seconds=5
        )
        assert trace.output == "ok4"
        assert ans_path == "choices.0.message.content"
    finally:
        server.shutdown()


def test_prompt_app_with_fake_gateway():
    from app.services.connectors import PromptAppConnector

    class Fake:
        def chat(self, messages, model, params=None):
            return {"content": "hello from fake", "tokens_in": 1, "tokens_out": 1}

    connector = PromptAppConnector(llm_gateway=Fake())
    trace = connector.render_and_send(prompt="Say {{input}}", input_text="hi")
    assert trace.output == "hello from fake"
    assert isinstance(trace.to_dict(), dict)


def test_upload_outputs_csv_missing_optional_columns():
    from app.services.connectors import UploadOutputsConnector

    # Only input + output: optional columns (context, latency, tokens) are absent.
    csv_content = "question,output\nhello world,greeting received\n"
    connector = UploadOutputsConnector()
    trace = connector.render_and_send(csv_content=csv_content)
    assert trace.output == "greeting received"
    assert trace.retrieved_context == "not instrumented"
    assert trace.tokens_in is None
    assert trace.tokens_out is None
