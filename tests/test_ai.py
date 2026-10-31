import glob
import http.server
import io
import json
import os
import threading
import unittest

from sutra import Interpreter, ModelError, MockModel, SutraRuntimeError
from sutra.models import AnthropicModel, make_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(source, model="mock"):
    out = io.StringIO()
    interp = Interpreter(out=out, model=model)
    interp.run(source)
    return out.getvalue(), interp


class AskTests(unittest.TestCase):
    def test_plain_ask_echoes_with_mock(self):
        out, _ = run('print(ask "hello {1 + 1}")')
        self.assertEqual(out, "[mock reply to: hello 2]\n")

    def test_prompt_template_renders_messages(self):
        src = """
        prompt p(topic, n = 2) {
          system: "Be brief."
          user: "Example?"
          assistant: "Example."
          user: "Give {n} facts about {topic}."
        }
        let v = p("tea")
        print(v.system)
        print(len(v.messages), v.messages[2].content)
        """
        out, _ = run(src)
        self.assertEqual(out, "Be brief.\n3 Give 2 facts about tea.\n")

    def test_prompt_sends_system_and_history(self):
        m = MockModel(["ok"])
        interp = Interpreter(out=io.StringIO(), model=m)
        interp.run('prompt p(x) { system: "S"\n user: "U {x}" }\nask p(1)')
        call = m.calls[0]
        self.assertEqual(call["system"], "S")
        self.assertEqual(call["messages"], [{"role": "user", "content": "U 1"}])

    def test_typed_ask_with_placeholder_mock(self):
        src = """
        type T = {label: "a" | "b", score: num, tags: [str], ok: bool, note?: str}
        let r = ask "x" as T
        print(r)
        """
        out, _ = run(src)
        self.assertEqual(json.loads(out), {"label": "a", "score": 0, "tags": ["example"], "ok": False, "note": "example"})

    def test_typed_ask_retries_until_valid(self):
        src = """
        let m = mock(["not json", {score: "high"}, "```json\\n\\{\\"score\\": 4\\}\\n```"])
        let r = ask "rate it" using m as {score: num}
        print(r.score)
        """
        out, interp = run(src)
        self.assertEqual(out, "4\n")

    def test_typed_ask_gives_up(self):
        with self.assertRaises(ModelError) as ctx:
            run('ask "x" using mock(["a", "b", "c"]) as {n: num}')
        self.assertIn("after 3 attempts", str(ctx.exception))

    def test_schema_and_retry_feedback_sent_to_model(self):
        m = MockModel(['{"n": "x"}', '{"n": 1}'])
        Interpreter(out=io.StringIO(), model=m).run('ask "q" as {n: num}')
        first = m.calls[0]["messages"][0]["content"]
        self.assertIn('"type": "number"', first)
        self.assertEqual(m.calls[0]["schema"]["required"], ["n"])
        feedback = m.calls[1]["messages"][-1]["content"]
        self.assertIn("value.n should be a number", feedback)

    def test_enum_accepts_bare_text(self):
        out, _ = run('print(ask "x" using mock(["  Positive\\n"]) as "positive" | "negative")')
        self.assertEqual(out, "positive\n")

    def test_ask_as_str_returns_text(self):
        out, _ = run('print(ask "x" using mock(["plain"]) as str)')
        self.assertEqual(out, "plain\n")

    def test_use_sets_default_model(self):
        out, _ = run('use mock(["from default"])\nprint(ask "x")')
        self.assertEqual(out, "from default\n")

    def test_unknown_type(self):
        with self.assertRaises(SutraRuntimeError):
            run('ask "x" as Missing')


class AgentTests(unittest.TestCase):
    def test_agent_calls_tools_and_finishes(self):
        src = """
        let log = []
        tool add(a: num, b: num) "Add two numbers" {
          push(log, "add")
          return a + b
        }
        agent bot {
          model: mock([{tool: "add", args: {a: 2, b: "3"}}, "The answer is 5."])
          system: "Use tools."
          tools: [add]
        }
        print(bot("2 + 3?"), log)
        """
        out, _ = run(src)
        self.assertEqual(out, 'The answer is 5. ["add"]\n')

    def test_agent_sends_tool_specs_and_results(self):
        m = MockModel([{"tool": "echo", "args": {"text": "hi"}}, {"tool": "nope"}, "done"])
        interp = Interpreter(out=io.StringIO(), model=m)
        interp.run(
            'tool echo(text: str, times: num = 1) "Echo text" { return text * times }\n'
            "agent a { tools: [echo] }\n"
            'a("go")'
        )
        spec = m.calls[0]["tools"][0]
        self.assertEqual(spec["name"], "echo")
        self.assertEqual(spec["input_schema"]["required"], ["text"])
        self.assertEqual(spec["input_schema"]["properties"]["times"], {"type": "number"})
        result = m.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(result["content"], "hi")
        unknown = m.calls[2]["messages"][-1]["content"][0]
        self.assertTrue(unknown["is_error"])

    def test_tool_errors_are_reported_to_model(self):
        m = MockModel([{"tool": "fail", "args": {}}, "recovered"])
        interp = Interpreter(out=io.StringIO(), model=m)
        interp.run('tool fail() { throw "broken" }\nagent a { tools: [fail] }\nprint(a("x"))')
        block = m.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(block["content"], "error: broken")
        self.assertTrue(block["is_error"])

    def test_agent_step_limit(self):
        src = 'tool t() { return 1 }\nagent a { model: mock([{tool: "t"}, {tool: "t"}]), tools: [t], max_steps: 2 }\na("x")'
        with self.assertRaises(ModelError):
            run(src)

    def test_tools_are_callable_directly_and_typed(self):
        out, _ = run('tool sq(x: num) { return x * x }\nprint(sq("4"))')
        self.assertEqual(out, "16\n")
        with self.assertRaises(SutraRuntimeError):
            run('tool sq(x: num) { return x * x }\nsq("abc")')


class _FakeAnthropic(http.server.BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _FakeAnthropic.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if body.get("tools") and len(body["messages"]) == 1:
            content = [{"type": "tool_use", "id": "tu_1", "name": "shout", "input": {"text": "hey"}}]
        else:
            content = [{"type": "text", "text": "final answer"}]
        payload = json.dumps({"content": content}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class AnthropicBackendTests(unittest.TestCase):
    def setUp(self):
        _FakeAnthropic.requests = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _FakeAnthropic)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.old_env = dict(os.environ)
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ["NO_PROXY"] = "127.0.0.1"
        os.environ["no_proxy"] = "127.0.0.1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_make_model_specs(self):
        self.assertIsInstance(make_model("anthropic:claude-opus-5-5"), AnthropicModel)
        self.assertEqual(make_model("claude-haiku-5-5").model, "claude-haiku-5-5")
        with self.assertRaises(ModelError):
            make_model("unknown:thing")

    def test_agent_round_trip_over_http(self):
        src = """
        tool shout(text: str) "Uppercase text" { return upper(text) }
        agent a { model: model("anthropic:claude-sonnet-5-5", {max_tokens: 50}), system: "Sys", tools: [shout] }
        print(a("go"))
        """
        out, _ = run(src, model=None)
        self.assertEqual(out, "final answer\n")
        first, second = _FakeAnthropic.requests
        self.assertEqual(first["headers"]["x-api-key"], "test-key")
        self.assertEqual(first["body"]["model"], "claude-sonnet-5-5")
        self.assertEqual(first["body"]["max_tokens"], 50)
        self.assertEqual(first["body"]["system"], "Sys")
        self.assertEqual(first["body"]["tools"][0]["name"], "shout")
        tool_result = second["body"]["messages"][-1]["content"][0]
        self.assertEqual(tool_result, {"type": "tool_result", "tool_use_id": "tu_1", "content": "HEY"})

    def test_missing_key(self):
        del os.environ["ANTHROPIC_API_KEY"]
        with self.assertRaises(ModelError) as ctx:
            run('ask "x" using "anthropic"')
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


class ExampleTests(unittest.TestCase):
    def test_examples_run_offline(self):
        files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.sutra")))
        self.assertTrue(files)
        for path in files:
            with self.subTest(example=os.path.basename(path)), open(path, encoding="utf-8") as fh:
                out = io.StringIO()
                Interpreter(out=out, model="mock").run(fh.read())
                self.assertTrue(out.getvalue())


if __name__ == "__main__":
    unittest.main()
