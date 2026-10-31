"""Tree-walking interpreter for Sutra."""

import json
import os
import sys

from . import builtins as builtin_module
from .errors import ModelError, SutraError, SutraRuntimeError
from .models import Model, make_model
from .parser import parse
from .types import AnyType, SType, StrType, ValidationError, build_type

MAX_STRUCTURED_ATTEMPTS = 3
DEFAULT_AGENT_STEPS = 8


# ------------------------------------------------------------------ control flow
class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class ThrownError(SutraRuntimeError):
    """An error raised by a Sutra `throw` statement; carries the thrown value."""

    def __init__(self, value, line):
        self.value = value
        super().__init__(to_str(value), line)


# ------------------------------------------------------------------ environment
class Environment:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def define(self, name, value):
        self.vars[name] = value

    def lookup(self, name, line=None):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise SutraRuntimeError(f"'{name}' is not defined", line)

    def assign(self, name, value, line=None):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise SutraRuntimeError(f"'{name}' is not defined (use 'let {name} = ...' to create it)", line)


# ------------------------------------------------------------------ values
class Function:
    kind = "function"

    def __init__(self, name, params, body, closure):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure

    def __repr__(self):
        return f"<fn {self.name}>"


class Tool(Function):
    kind = "tool"

    def __init__(self, name, params, body, closure, description, param_types):
        super().__init__(name, params, body, closure)
        self.description = description
        self.param_types = param_types  # name -> SType

    def spec(self):
        return {
            "name": self.name,
            "description": self.description or f"The {self.name} tool.",
            "input_schema": {
                "type": "object",
                "properties": {p.name: self.param_types[p.name].schema() for p in self.params},
                "required": [p.name for p in self.params if p.default is None],
            },
        }

    def __repr__(self):
        return f"<tool {self.name}>"


class PromptTemplate:
    def __init__(self, name, params, messages, closure):
        self.name = name
        self.params = params
        self.messages = messages
        self.closure = closure

    def __repr__(self):
        return f"<prompt {self.name}>"


class PromptValue:
    """A rendered prompt: an optional system message plus chat messages."""

    def __init__(self, system, messages):
        self.system = system
        self.messages = messages

    @property
    def text(self):
        return "\n\n".join(m["content"] for m in self.messages if m["role"] == "user")

    def __repr__(self):
        return f"<prompt {self.text[:40]!r}>"


class Agent:
    def __init__(self, name, model, system, tools, max_steps, trace):
        self.name = name
        self.model = model
        self.system = system
        self.tools = tools
        self.max_steps = max_steps
        self.trace = trace

    def __repr__(self):
        return f"<agent {self.name}>"


class Builtin:
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn

    def __repr__(self):
        return f"<builtin {self.name}>"


# ------------------------------------------------------------------ formatting
def to_str(value):
    if isinstance(value, str):
        return value
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e16:
            return str(int(value))
        return repr(value)
    if isinstance(value, (list, dict)):
        return json.dumps(to_jsonable(value), ensure_ascii=False)
    if isinstance(value, PromptValue):
        return value.text
    return repr(value)


def to_jsonable(value):
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return int(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return to_str(value)


def type_name(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    if isinstance(value, Tool):
        return "tool"
    if isinstance(value, (Function, Builtin)):
        return "fn"
    if isinstance(value, PromptTemplate):
        return "prompt"
    if isinstance(value, PromptValue):
        return "prompt"
    if isinstance(value, Agent):
        return "agent"
    if isinstance(value, Model):
        return "model"
    if isinstance(value, SType):
        return "type"
    return "unknown"


def truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def parse_json_loose(text):
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(open_ch), cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("reply was not valid JSON")


# ------------------------------------------------------------------ interpreter
class Interpreter:
    def __init__(self, out=None, model=None):
        self.out = out or sys.stdout
        self.globals = Environment()
        self.default_model = None
        self.fallback_model = make_model(model) if model is not None else None
        for name, fn in builtin_module.BUILTINS.items():
            self.globals.define(name, Builtin(name, fn))

    # ---- entry points
    def run(self, source):
        program = parse(source)
        return self.execute_block(program.body, self.globals)

    def write(self, text):
        self.out.write(text + "\n")

    def resolve_model(self, value=None):
        if value is not None:
            return value if isinstance(value, Model) else make_model(value)
        if self.default_model is not None:
            return self.default_model
        if self.fallback_model is None:
            self.fallback_model = make_model(os.environ.get("SUTRA_MODEL", "mock"))
        return self.fallback_model

    # ---- statements
    def execute_block(self, statements, env):
        result = None
        for stmt in statements:
            result = self.execute(stmt, env)
        return result

    def execute(self, node, env):
        handler = getattr(self, f"exec_{node.kind}")
        try:
            return handler(node, env)
        except SutraError as exc:
            if exc.line is None:
                exc.line = node.line
            raise
        except (ReturnSignal, BreakSignal, ContinueSignal):
            raise
        except RecursionError:
            raise SutraRuntimeError("maximum recursion depth exceeded", node.line) from None

    def exec_ExprStmt(self, node, env):
        return self.evaluate(node.expr, env)

    def exec_Let(self, node, env):
        env.define(node.name, self.evaluate(node.value, env))

    def exec_Assign(self, node, env):
        value = self.evaluate(node.value, env)
        target = node.target
        if node.op != "=":
            current = self.evaluate(target, env)
            value = self.binary("+" if node.op == "+=" else "-", current, value, node.line)
        if target.kind == "Name":
            env.assign(target.name, value, node.line)
        elif target.kind == "Index":
            obj = self.evaluate(target.obj, env)
            index = self.evaluate(target.index, env)
            if isinstance(obj, list):
                self.check_list_index(obj, index, node.line)
                obj[int(index)] = value
            elif isinstance(obj, dict):
                obj[index] = value
            else:
                raise SutraRuntimeError(f"cannot assign into a {type_name(obj)}", node.line)
        else:
            obj = self.evaluate(target.obj, env)
            if not isinstance(obj, dict):
                raise SutraRuntimeError(f"cannot set field on a {type_name(obj)}", node.line)
            obj[target.name] = value

    def exec_FnDecl(self, node, env):
        env.define(node.name, Function(node.name, node.params, node.body, env))

    def exec_PromptDecl(self, node, env):
        env.define(node.name, PromptTemplate(node.name, node.params, node.messages, env))

    def exec_ToolDecl(self, node, env):
        description = to_str(self.evaluate(node.description, env)) if node.description else None
        lookup = lambda name: env.lookup(name, node.line)  # noqa: E731
        types = {p.name: build_type(p.type, lookup) if p.type else AnyType() for p in node.params}
        env.define(node.name, Tool(node.name, node.params, node.body, env, description, types))

    def exec_AgentDecl(self, node, env):
        config = {key: self.evaluate(value, env) for key, value in node.entries}
        unknown = set(config) - {"model", "system", "tools", "max_steps", "trace"}
        if unknown:
            raise SutraRuntimeError(f"unknown agent setting(s): {', '.join(sorted(unknown))}", node.line)
        tools = config.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(t, Tool) for t in tools):
            raise SutraRuntimeError("agent 'tools' must be a list of tools declared with 'tool'", node.line)
        model = config.get("model")
        agent = Agent(
            node.name,
            make_model(model) if model is not None and not isinstance(model, Model) else model,
            to_str(config["system"]) if config.get("system") is not None else None,
            tools,
            int(config.get("max_steps", DEFAULT_AGENT_STEPS)),
            truthy(config.get("trace", False)),
        )
        env.define(node.name, agent)

    def exec_TypeDecl(self, node, env):
        from .types import NamedType

        inner = build_type(node.type, lambda name: env.lookup(name, node.line))
        env.define(node.name, NamedType(node.name, inner))

    def exec_Use(self, node, env):
        self.default_model = self.resolve_model(self.evaluate(node.model, env))

    def exec_If(self, node, env):
        if truthy(self.evaluate(node.cond, env)):
            return self.execute_block(node.body, Environment(env))
        if node.orelse:
            return self.execute_block(node.orelse, Environment(env))
        return None

    def exec_While(self, node, env):
        while truthy(self.evaluate(node.cond, env)):
            try:
                self.execute_block(node.body, Environment(env))
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def exec_For(self, node, env):
        iterable = self.evaluate(node.iterable, env)
        if isinstance(iterable, dict):
            items = list(iterable.items()) if len(node.names) == 2 else list(iterable.keys())
        elif isinstance(iterable, (list, str)):
            items = list(enumerate(iterable)) if len(node.names) == 2 else list(iterable)
        else:
            raise SutraRuntimeError(f"cannot loop over a {type_name(iterable)}", node.line)
        for item in items:
            scope = Environment(env)
            if len(node.names) == 2:
                scope.define(node.names[0], item[0])
                scope.define(node.names[1], item[1])
            else:
                scope.define(node.names[0], item)
            try:
                self.execute_block(node.body, scope)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def exec_Return(self, node, env):
        raise ReturnSignal(self.evaluate(node.value, env) if node.value is not None else None)

    def exec_Break(self, node, env):
        raise BreakSignal()

    def exec_Continue(self, node, env):
        raise ContinueSignal()

    def exec_Throw(self, node, env):
        raise ThrownError(self.evaluate(node.value, env), node.line)

    def exec_Try(self, node, env):
        try:
            return self.execute_block(node.body, Environment(env))
        except SutraError as exc:
            scope = Environment(env)
            scope.define(node.name, exc.value if isinstance(exc, ThrownError) else exc.message)
            return self.execute_block(node.handler, scope)

    # ---- expressions
    def evaluate(self, node, env):
        return getattr(self, f"eval_{node.kind}")(node, env)

    def eval_Literal(self, node, env):
        return node.value

    def eval_Template(self, node, env):
        return "".join(p if isinstance(p, str) else to_str(self.evaluate(p, env)) for p in node.parts)

    def eval_Name(self, node, env):
        return env.lookup(node.name, node.line)

    def eval_List(self, node, env):
        return [self.evaluate(item, env) for item in node.items]

    def eval_Map(self, node, env):
        return {key: self.evaluate(value, env) for key, value in node.entries}

    def eval_Lambda(self, node, env):
        return Function("<lambda>", node.params, node.body, env)

    def eval_Unary(self, node, env):
        value = self.evaluate(node.operand, env)
        if node.op == "not":
            return not truthy(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SutraRuntimeError(f"cannot negate a {type_name(value)}", node.line)
        return -value

    def eval_Logical(self, node, env):
        left = self.evaluate(node.left, env)
        if node.op == "and":
            return self.evaluate(node.right, env) if truthy(left) else left
        return left if truthy(left) else self.evaluate(node.right, env)

    def eval_Binary(self, node, env):
        return self.binary(node.op, self.evaluate(node.left, env), self.evaluate(node.right, env), node.line)

    def binary(self, op, left, right, line):
        is_num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
        if op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return to_str(left) + to_str(right)
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            if isinstance(left, dict) and isinstance(right, dict):
                return {**left, **right}
            if is_num(left) and is_num(right):
                return left + right
        elif op in ("-", "*", "/", "%"):
            if op == "*" and isinstance(left, (str, list)) and isinstance(right, int) and not isinstance(right, bool):
                return left * right
            if is_num(left) and is_num(right):
                if op == "-":
                    return left - right
                if op == "*":
                    return left * right
                if right == 0:
                    raise SutraRuntimeError("division by zero", line)
                if op == "/":
                    result = left / right
                    return int(result) if result.is_integer() and isinstance(left, int) and isinstance(right, int) else result
                return left % right
        elif op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op in ("<", ">", "<=", ">="):
            if (is_num(left) and is_num(right)) or (isinstance(left, str) and isinstance(right, str)):
                return {"<": left < right, ">": left > right, "<=": left <= right, ">=": left >= right}[op]
        elif op in ("in", "not in"):
            if isinstance(right, (list, dict)) or (isinstance(right, str) and isinstance(left, str)):
                result = left in right
                return result if op == "in" else not result
        raise SutraRuntimeError(f"cannot apply '{op}' to {type_name(left)} and {type_name(right)}", line)

    @staticmethod
    def check_list_index(obj, index, line):
        if isinstance(index, bool) or not isinstance(index, int):
            raise SutraRuntimeError("list index must be a whole number", line)
        if not -len(obj) <= index < len(obj):
            raise SutraRuntimeError(f"index {index} is out of range for a list of length {len(obj)}", line)

    def eval_Index(self, node, env):
        obj = self.evaluate(node.obj, env)
        index = self.evaluate(node.index, env)
        if isinstance(obj, (list, str)):
            self.check_list_index(obj, index, node.line)
            return obj[index]
        if isinstance(obj, dict):
            if index not in obj:
                raise SutraRuntimeError(f"key {to_str(index)!r} not found", node.line)
            return obj[index]
        raise SutraRuntimeError(f"cannot index a {type_name(obj)}", node.line)

    def eval_Member(self, node, env):
        obj = self.evaluate(node.obj, env)
        if isinstance(obj, dict):
            if node.name not in obj:
                raise SutraRuntimeError(f"field '{node.name}' not found", node.line)
            return obj[node.name]
        if isinstance(obj, PromptValue):
            if node.name == "text":
                return obj.text
            if node.name == "system":
                return obj.system
            if node.name == "messages":
                return [dict(m) for m in obj.messages]
        if isinstance(obj, (Function, PromptTemplate, Agent)) and node.name == "name":
            return obj.name
        raise SutraRuntimeError(f"a {type_name(obj)} has no field '{node.name}'", node.line)

    def eval_Call(self, node, env):
        callee = self.evaluate(node.callee, env)
        args = [self.evaluate(a, env) for a in node.args]
        kwargs = {name: self.evaluate(value, env) for name, value in node.kwargs}
        return self.call(callee, args, kwargs, node.line)

    def eval_Ask(self, node, env):
        target = self.evaluate(node.prompt, env)
        model = self.resolve_model(self.evaluate(node.model, env) if node.model is not None else None)
        out_type = None
        if node.type is not None:
            out_type = build_type(node.type, lambda name: env.lookup(name, node.line))
        if isinstance(target, PromptValue):
            system, messages = target.system, [dict(m) for m in target.messages]
        else:
            system, messages = None, [{"role": "user", "content": to_str(target)}]
        return self.ask(model, system, messages, out_type, node.line)

    # ---- calling
    def bind(self, params, args, kwargs, closure, name, line, types=None):
        if len(args) > len(params):
            raise SutraRuntimeError(f"{name}() takes {len(params)} argument(s) but got {len(args)}", line)
        scope = Environment(closure)
        names = {p.name for p in params}
        for key in kwargs:
            if key not in names:
                raise SutraRuntimeError(f"{name}() has no parameter '{key}'", line)
        for i, param in enumerate(params):
            if i < len(args):
                if param.name in kwargs:
                    raise SutraRuntimeError(f"{name}() got '{param.name}' twice", line)
                value = args[i]
            elif param.name in kwargs:
                value = kwargs[param.name]
            elif param.default is not None:
                value = self.evaluate(param.default, scope)
            else:
                raise SutraRuntimeError(f"{name}() is missing argument '{param.name}'", line)
            if types is not None:
                try:
                    value = types[param.name].validate(value, param.name)
                except ValidationError as exc:
                    raise SutraRuntimeError(f"{name}(): {exc}", line) from None
            scope.define(param.name, value)
        return scope

    def call(self, callee, args, kwargs, line=None):
        if isinstance(callee, Builtin):
            try:
                return callee.fn(self, *args, **kwargs)
            except SutraError:
                raise
            except TypeError as exc:
                raise SutraRuntimeError(f"{callee.name}(): {exc}", line) from None
            except (ValueError, KeyError, IndexError, OSError) as exc:
                raise SutraRuntimeError(f"{callee.name}(): {exc}", line) from None
        if isinstance(callee, Function):
            types = callee.param_types if isinstance(callee, Tool) else None
            scope = self.bind(callee.params, args, kwargs, callee.closure, callee.name, line, types)
            try:
                self.execute_block(callee.body, scope)
            except ReturnSignal as signal:
                return signal.value
            return None
        if isinstance(callee, PromptTemplate):
            scope = self.bind(callee.params, args, kwargs, callee.closure, callee.name, line)
            system_parts = []
            messages = []
            for role, expr in callee.messages:
                text = to_str(self.evaluate(expr, scope))
                if role == "system":
                    system_parts.append(text)
                else:
                    messages.append({"role": role, "content": text})
            return PromptValue("\n\n".join(system_parts) or None, messages)
        if isinstance(callee, Agent):
            if kwargs or len(args) != 1:
                raise SutraRuntimeError(f"agent {callee.name} takes exactly one task argument", line)
            return self.run_agent(callee, args[0], line)
        raise SutraRuntimeError(f"a {type_name(callee)} is not callable", line)

    # ---- AI operations
    def ask(self, model, system, messages, out_type, line):
        if out_type is None or isinstance(out_type, StrType) or (
            hasattr(out_type, "inner") and isinstance(out_type.inner, StrType)
        ):
            return model.complete(system, messages).text
        schema = out_type.schema()
        instruction = (
            "Respond with only a JSON value that matches this JSON Schema, and no other text:\n"
            + json.dumps(schema)
        )
        messages = [dict(m) for m in messages]
        if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], str):
            messages[-1]["content"] = messages[-1]["content"] + "\n\n" + instruction
        else:
            messages.append({"role": "user", "content": instruction})
        last_error = None
        for _ in range(MAX_STRUCTURED_ATTEMPTS):
            reply = model.complete(system, messages, schema=schema).text
            try:
                try:
                    value = parse_json_loose(reply)
                except ValueError:
                    value = reply.strip()
                return out_type.validate(value)
            except ValidationError as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": reply or "(empty reply)"})
                messages.append(
                    {"role": "user", "content": f"That reply was invalid: {last_error}. Reply with only the corrected JSON."}
                )
        raise ModelError(
            f"model did not return a valid {out_type!r} after {MAX_STRUCTURED_ATTEMPTS} attempts ({last_error})", line
        )

    def run_agent(self, agent, task, line):
        model = self.resolve_model(agent.model)
        system = agent.system
        if isinstance(task, PromptValue):
            messages = [dict(m) for m in task.messages]
            if task.system:
                system = f"{system}\n\n{task.system}" if system else task.system
        else:
            messages = [{"role": "user", "content": to_str(task)}]
        tools = {t.name: t for t in agent.tools}
        specs = [t.spec() for t in agent.tools] or None
        for _ in range(agent.max_steps):
            response = model.complete(system, messages, tools=specs)
            messages.append({"role": "assistant", "content": response.content or [{"type": "text", "text": response.text}]})
            if not response.tool_calls:
                return response.text
            results = []
            for call in response.tool_calls:
                if agent.trace:
                    self.write(f"[{agent.name}] {call.name}({json.dumps(call.input, ensure_ascii=False)})")
                tool = tools.get(call.name)
                block = {"type": "tool_result", "tool_use_id": call.id}
                if tool is None:
                    block.update(content=f"unknown tool '{call.name}'", is_error=True)
                else:
                    try:
                        output = self.call(tool, [], dict(call.input), line)
                        block["content"] = to_str(output)
                    except SutraError as exc:
                        block.update(content=f"error: {exc.message}", is_error=True)
                if agent.trace:
                    self.write(f"[{agent.name}]   -> {block['content']}")
                results.append(block)
            messages.append({"role": "user", "content": results})
        raise ModelError(f"agent {agent.name} did not finish within {agent.max_steps} steps", line)


def run_source(source, out=None, model=None):
    """Convenience helper: run a program and return the interpreter."""
    interp = Interpreter(out=out, model=model)
    interp.run(source)
    return interp
