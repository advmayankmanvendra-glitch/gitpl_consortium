"""Tree-walking interpreter for Gatbandhan."""

import copy
import json
import os
import sys

from . import ast
from .coalition import Ballot, Settings, decide, learn
from .errors import GatbandhanError, GbnRuntimeError
from .journal import Journal, utc_now
from .models import Human, Models
from .parser import parse
from .values import (Bits, Bond, Builtin, Callable, Coalition, Function, Member,
                     SealedError, Verdict, freeze, seal, show, type_name, unseal)


class BondError(GbnRuntimeError):
    """An attempt to overwrite something a bond protects. It is never caught."""


class ReturnSignal(Exception):
    def __init__(self, value, feeling=None):
        self.value = value
        self.feeling = feeling


class AbstainSignal(Exception):
    def __init__(self, reason):
        self.reason = reason


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class Env:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def lookup(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env
            env = env.parent
        return None


MAX_DEPTH = 200


class Interpreter:
    def __init__(self, out=None, stdin=None, clock=utc_now, base_dir=None):
        self.out = out or sys.stdout
        self.models = Models()
        self.human = Human(stdin=stdin, stdout=self.out)
        self.clock = clock
        self.base_dir = base_dir or os.getcwd()
        self.globals = Env()
        self.bonds = {}  # name -> Bond; these names are sealed everywhere
        self.depth = 0
        from .builtins import install
        install(self)

    # ---- running ----

    def run(self, src):
        program = parse(src)
        try:
            self.exec_block(program, self.globals)
        except ReturnSignal:
            raise GbnRuntimeError("'return' outside a function")
        except AbstainSignal:
            raise GbnRuntimeError("'abstain' outside a member")
        except (BreakSignal, ContinueSignal):
            raise GbnRuntimeError("'break' or 'continue' outside a loop")

    def print(self, text):
        self.out.write(text + "\n")

    # ---- the bond's protections ----

    def refuse(self, bond, what, line):
        """Record a refused overwrite in the bond's memory, then stop the program."""
        bond.journal.append("refused", by="program", text=what, line=line)
        raise BondError(f"refused: {what}. The bond '{bond.name}' cannot be overwritten", line)

    def guard_name(self, name, line, action="rebind"):
        if name in self.bonds:
            self.refuse(self.bonds[name], f"{action} '{name}'", line)

    def sealed_change(self, container, line, key=None):
        bond = self.bonds.get(getattr(container, "owner", None))
        if bond is None:
            raise GbnRuntimeError("this value is sealed and cannot be changed", line)
        what = f" at {show(key, True)}" if key is not None else ""
        self.refuse(bond, f"change a sealed {type_name(container)}{what} that belongs to bond '{bond.name}'", line)

    # ---- statements ----

    def exec_block(self, stmts, env):
        for s in stmts:
            self.exec(s, env)

    def exec(self, s, env):
        t = type(s)
        if t is ast.ExprStmt:
            self.eval(s.expr, env)
        elif t is ast.Let:
            self.guard_name(s.name, s.line, "rebind")
            env.vars[s.name] = self.eval(s.value, env)
        elif t is ast.Assign:
            self.assign(s, env)
        elif t is ast.FnDecl:
            self.guard_name(s.name, s.line, "redefine")
            env.vars[s.name] = Function(s.name, s.params, s.body, env)
        elif t is ast.MemberDecl:
            self.guard_name(s.name, s.line, "redefine")
            trust = 1.0
            if s.trust is not None:
                trust = self.eval(s.trust, env)
                if not _is_num(trust) or trust < 0:
                    raise GbnRuntimeError("a member's trust must be a number of 0 or more", s.line)
            env.vars[s.name] = Member(s.name, s.params, s.body, env, trust)
        elif t is ast.CoalitionDecl:
            self.guard_name(s.name, s.line, "redefine")
            env.vars[s.name] = Coalition(s.name, s, env)
        elif t is ast.BondDecl:
            self.declare_bond(s, env)
        elif t is ast.VowStmt:
            self.make_vow(self.bond_named(s.bond, s.line), s.vow, env)
        elif t is ast.Remember:
            self.remember(s, env)
        elif t is ast.If:
            if truthy(self.eval(s.cond, env)):
                self.exec_block(s.then, Env(env))
            elif s.otherwise is not None:
                self.exec_block(s.otherwise, Env(env))
        elif t is ast.While:
            while truthy(self.eval(s.cond, env)):
                try:
                    self.exec_block(s.body, Env(env))
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif t is ast.For:
            self.guard_name(s.var, s.line, "rebind")
            seq = self.eval(s.iterable, env)
            if isinstance(seq, dict):
                items = list(seq.keys())
            elif isinstance(seq, (list, str, Bits)):
                items = list(seq)
            else:
                raise GbnRuntimeError(f"cannot loop over a {type_name(seq)}", s.line)
            for item in items:
                inner = Env(env)
                inner.vars[s.var] = item
                try:
                    self.exec_block(s.body, inner)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif t is ast.Return:
            value = None if s.value is None else self.eval(s.value, env)
            feeling = None if s.feeling is None else self.eval(s.feeling, env)
            raise ReturnSignal(value, feeling)
        elif t is ast.Abstain:
            reason = None if s.reason is None else self.eval(s.reason, env)
            raise AbstainSignal(reason if reason is not None else "abstained")
        elif t is ast.Break:
            raise BreakSignal()
        elif t is ast.Continue:
            raise ContinueSignal()
        elif t is ast.Match:
            self.exec_match(s, env)
        else:  # pragma: no cover
            raise GbnRuntimeError(f"unknown statement {t.__name__}", s.line)

    def assign(self, s, env):
        target = s.target
        if isinstance(target, ast.Name):
            self.guard_name(target.name, s.line, "overwrite")
            scope = env.lookup(target.name)
            if scope is None:
                raise GbnRuntimeError(f"'{target.name}' is not defined (use 'let' to create it)", s.line)
            scope.vars[target.name] = self.eval(s.value, env)
            return
        obj = self.eval(target.target, env)
        if isinstance(obj, Bond):
            what = target.name if isinstance(target, ast.Field) else "an entry"
            self.refuse(obj, f"overwrite {what} of bond '{obj.name}'", s.line)
        value = self.eval(s.value, env)
        key = target.name if isinstance(target, ast.Field) else self.eval(target.index, env)
        try:
            if isinstance(obj, list):
                if not _is_int(key):
                    raise GbnRuntimeError("list index must be a whole number", s.line)
                if not -len(obj) <= key < len(obj):
                    raise GbnRuntimeError(f"index {key} is out of range", s.line)
                obj[int(key)] = value
            elif isinstance(obj, dict):
                obj[key] = value
            else:
                raise GbnRuntimeError(f"cannot set a field or index on a {type_name(obj)}", s.line)
        except SealedError as e:
            self.sealed_change(e.container, s.line, key)

    def exec_match(self, s, env):
        v = self.eval(s.subject, env)
        if not isinstance(v, Verdict):
            raise GbnRuntimeError(f"match needs a verdict, got a {type_name(v)}", s.line)
        inner = Env(env)
        if v.agreed and s.agreed_body is not None:
            if s.agreed_name:
                self.guard_name(s.agreed_name, s.line, "rebind")
                inner.vars[s.agreed_name] = v.decision
            self.exec_block(s.agreed_body, inner)
        elif not v.agreed and s.split_body is not None:
            if s.split_name:
                self.guard_name(s.split_name, s.line, "rebind")
                inner.vars[s.split_name] = v.reason
            self.exec_block(s.split_body, inner)

    # ---- bonds ----

    def bond_named(self, name, line):
        if name not in self.bonds:
            raise GbnRuntimeError(f"no bond named '{name}'", line)
        return self.bonds[name]

    def declare_bond(self, s, env):
        if s.name in self.bonds:
            self.refuse(self.bonds[s.name], f"declare the bond '{s.name}' a second time", s.line)
        if env.lookup(s.name) is not None:
            raise GbnRuntimeError(f"'{s.name}' is already defined; a bond needs a name of its own", s.line)
        human = self.eval(s.human, env)
        if not isinstance(human, str) or not human.strip():
            raise GbnRuntimeError("a bond's human partner must be a name (a string)", s.line)
        ai = self.eval(s.ai, env)
        if isinstance(ai, str):
            ai_name = ai
        elif isinstance(ai, (Member, Function)):
            ai_name = ai.name
        else:
            raise GbnRuntimeError("a bond's ai partner must be a member, a function or a model name", s.line)
        key = self.eval(s.key, env) if s.key is not None else None
        path = None
        if s.keep is not None:
            path = self.eval(s.keep, env)
            if not isinstance(path, str):
                raise GbnRuntimeError("'keep' must be a file path", s.line)
            path = os.path.join(self.base_dir, path)
        journal = Journal(path, clock=self.clock)
        bond = Bond(s.name, human, ai, ai_name, key, journal=journal)

        formed = journal.find("bond")
        if formed:
            first = formed[0]
            if (first.get("name"), first.get("human"), first.get("ai")) != (s.name, human, ai_name):
                raise BondError(
                    f"refused: this journal holds the bond '{first.get('name')}' between "
                    f"{first.get('human')} and {first.get('ai')}; it cannot be given to someone else", s.line)
            for e in journal.find("vow"):
                bond.vows[e["vow"]] = seal(e.get("value"), s.name)
                bond.vow_lines[e["vow"]] = e["n"]
        else:
            journal.append("bond", by="both", name=s.name, human=human, ai=ai_name,
                           text=f"{human} and {ai_name} formed the bond '{s.name}'")
        self.bonds[s.name] = bond
        env.vars[s.name] = bond
        for vow in s.vows:
            self.make_vow(bond, vow, env)

    def make_vow(self, bond, vow, env):
        value = self.eval(vow.value, env)
        if vow.name in bond.vows:
            if freeze(bond.vows[vow.name]) == freeze(value):
                return  # the same vow, made again: nothing changes
            self.refuse(bond, f"overwrite the vow '{vow.name}' (made in entry {bond.vow_lines[vow.name]})", vow.line)
        entry = bond.journal.append("vow", by="both", vow=vow.name, value=unseal(value),
                                    text=show(value))
        bond.vows[vow.name] = seal(value, bond.name)
        bond.vow_lines[vow.name] = entry["n"]

    def remember(self, s, env):
        bond = self.bond_named(s.bond, s.line)
        text = self.eval(s.text, env)
        feeling = None if s.feeling is None else self.eval(s.feeling, env)
        by = {"human": bond.human_name, "ai": bond.ai_name}.get(s.by, "both")
        if s.amends is None:
            bond.journal.append("memory", by=by, text=show(text), feeling=_feeling(feeling))
            return
        n = self.eval(s.amends, env)
        if not _is_int(n) or not 1 <= n <= len(bond.journal.entries):
            raise GbnRuntimeError(f"bond '{bond.name}' has no memory entry {show(n)} to amend", s.line)
        bond.journal.append("amend", by=by, amends=int(n), text=show(text), feeling=_feeling(feeling))

    def consult_partner(self, bond, question, line):
        """Ask the AI partner. Returns (answer, feeling) or (None, reason) on abstain."""
        ai = bond.ai
        if isinstance(ai, (Member, Function)):
            kind, a, b = self.run_member(ai, [question], line)
            return (a, b) if kind == "vote" else (None, a)
        vows = "; ".join(f"{k}: {show(v)}" for k, v in bond.vows.items()) or "none yet"
        system = (f"You are {bond.ai_name}, the AI partner in a bond named '{bond.name}' with "
                  f"{bond.human_name}. Your shared vows: {vows}. Answer the question honestly. "
                  'Reply only with JSON: {"answer": <short answer>, "feeling": <one word or phrase>}.')
        reply = self.models.consult(ai, question, system=system, line=line)
        if isinstance(reply, dict):
            return reply.get("answer"), reply.get("feeling")
        try:
            data = json.loads(reply)
            if isinstance(data, dict) and "answer" in data:
                return data.get("answer"), data.get("feeling")
        except (TypeError, ValueError):
            pass
        return reply, None

    def call_bond(self, bond, args, line):
        if len(args) != 1:
            raise GbnRuntimeError(f"a bond is asked one question at a time, got {len(args)} arguments", line)
        question = show(args[0])
        ballots, abstained, feelings = [], {}, {}

        h_answer, h_feeling = self.human.answer(bond.human_name, question)
        ai_answer, ai_extra = self.consult_partner(bond, question, line)

        for who, answer, extra in ((bond.human_name, h_answer, h_feeling),
                                   (bond.ai_name, ai_answer, ai_extra)):
            if answer is None:
                abstained[who] = extra if isinstance(extra, str) and extra else "did not answer"
                continue
            if extra is not None:
                feelings[who] = _feeling(extra)
            if isinstance(answer, str):
                answer = answer.strip()
            ballots.append(Ballot(who, answer, self.bucket(bond.key, answer, line, default_fold=True), 1.0))

        if abstained:
            silent = " and ".join(abstained)
            verdict = decide(bond.name, ballots, abstained, Settings(rule="unanimous", min_votes=2), line)
            verdict.reason = f"no consent: {silent} did not answer"
        else:
            verdict = decide(bond.name, ballots, abstained, Settings(rule="unanimous", min_votes=2), line)
            verdict.reason = "both agree" if verdict.agreed else "the partners disagree"
        verdict.feelings = feelings
        verdict.question = question
        verdict.rule = "and"
        verdict.partners = (bond.human_name, bond.ai_name)
        bond.journal.append("decision", by="both", question=question, text=f"{question} ({verdict.reason})",
                            agreed=verdict.agreed, decision=verdict.decision, votes=verdict.votes,
                            gate=verdict.gate(),
                            feelings=feelings or None, abstained=abstained or None)
        return verdict

    # ---- members and coalitions ----

    def run_member(self, fn, args, line):
        """Run a function as a voter: ('vote', answer, feeling) or ('abstain', reason, None)."""
        try:
            if isinstance(fn, Member):
                value, feeling = self.call_function(fn, unseal(copy.deepcopy(args)), line, want_feeling=True)
            elif isinstance(fn, (Coalition, Bond)):
                v = self.call(fn, unseal(copy.deepcopy(args)), line)
                if not v.agreed:
                    return "abstain", f"{fn.name} split: {v.reason}", None
                return "vote", v.decision, None
            else:
                value, feeling = self.call(fn, unseal(copy.deepcopy(args)), line), None
        except AbstainSignal as a:
            return "abstain", show(a.reason), None
        except BondError:
            raise
        except GbnRuntimeError as e:
            return "abstain", f"error: {e.message}", None
        if value is None:
            return "abstain", "returned none", None
        return "vote", value, feeling

    def bucket(self, key, answer, line, default_fold=False):
        if key is not None:
            return freeze(self.call(key, [answer], line))
        if default_fold and isinstance(answer, str):
            return freeze(answer.strip().lower())
        return freeze(answer)

    def call_coalition(self, c, args, line):
        d = c.decl
        if len(args) != len(d.params):
            raise GbnRuntimeError(f"coalition '{c.name}' takes {len(d.params)} arguments, got {len(args)}", line)
        env = Env(c.closure)
        env.vars.update(zip(d.params, args))

        members = [self.eval(m, env) for m in d.members]
        names = []
        for i, m in enumerate(members):
            if not isinstance(m, (Callable, Bond)):
                raise GbnRuntimeError(f"coalition '{c.name}': member {i + 1} is a {type_name(m)}, not something that can vote", line)
            nm = getattr(m, "name", None)
            if not nm or (isinstance(m, Function) and nm == "fn"):
                nm = f"member{i + 1}"
            if nm in names:
                nm = f"{nm}#{i + 1}"
            names.append(nm)

        weights = self.eval(d.weights, env) if d.weights is not None else {}
        if not isinstance(weights, dict):
            raise GbnRuntimeError("'weights' must be a map of member name to weight", line)
        key = self.eval(d.key, env) if d.key is not None else None
        rate = self.eval(d.learn, env) if d.learn is not None else None
        if rate is not None and not (_is_num(rate) and 0 < rate < 1):
            raise GbnRuntimeError("'learn' must be a number between 0 and 1", line)
        settings = Settings(rule=d.rule.kind)
        if d.rule.arg is not None:
            settings.rule_arg = self.eval(d.rule.arg, env)
            if not _is_num(settings.rule_arg) or settings.rule_arg <= 0:
                raise GbnRuntimeError(f"rule '{d.rule.kind}' needs a positive number", line)
            if d.rule.kind == "threshold" and settings.rule_arg > 1:
                raise GbnRuntimeError("a threshold is a share of the weight, between 0 and 1", line)
        if d.min_votes is not None:
            settings.min_votes = self.eval(d.min_votes, env)
        veto_names = []
        for v in d.veto:
            vm = self.eval(v, env)
            if vm not in members:
                raise GbnRuntimeError(f"coalition '{c.name}': veto must name one of its members", line)
            veto_names.append(names[members.index(vm)])
        settings.veto = tuple(veto_names)
        if d.tie is not None:
            settings.has_tie = True
            settings.tie = self.eval(d.tie, env)
            settings.tie_bucket = self.bucket(key, settings.tie, line)

        ballots, abstained, feelings = [], {}, {}
        for m, nm in zip(members, names):
            kind, answer, feeling = self.run_member(m, args, line)
            if kind == "abstain":
                abstained[nm] = answer
                continue
            if feeling is not None:
                feelings[nm] = _feeling(feeling)
            w = c.learned.get(nm, weights.get(nm, getattr(m, "trust", 1.0)))
            if not _is_num(w) or w < 0:
                raise GbnRuntimeError(f"weight of '{nm}' must be a number of 0 or more", line)
            ballots.append(Ballot(nm, answer, self.bucket(key, answer, line), float(w)))

        verdict = decide(c.name, ballots, abstained, settings, line)
        verdict.feelings = feelings
        if rate is not None:
            learn(c.learned, ballots, verdict, rate)
        c.history.append(verdict)
        return verdict

    # ---- calls ----

    def call(self, fn, args, line):
        if isinstance(fn, Builtin):
            try:
                return fn.fn(self, args, line) if fn.pass_interp else fn.fn(*args)
            except SealedError as e:
                self.sealed_change(e.container, line)
            except GatbandhanError as e:
                if e.line is None:
                    e.line = line
                    e.args = (f"line {line}: {e.message}",)
                raise
            except TypeError as e:
                raise GbnRuntimeError(f"{fn.name}: {e}", line)
        if isinstance(fn, Coalition):
            return self.call_coalition(fn, args, line)
        if isinstance(fn, Bond):
            return self.call_bond(fn, args, line)
        if isinstance(fn, (Function, Member)):
            try:
                value, _ = self.call_function(fn, args, line)
            except AbstainSignal:
                return None  # a member called directly that abstains gives none
            return value
        raise GbnRuntimeError(f"a {type_name(fn)} cannot be called", line)

    def call_function(self, fn, args, line, want_feeling=False):
        if len(args) != len(fn.params):
            raise GbnRuntimeError(f"'{fn.name}' takes {len(fn.params)} arguments, got {len(args)}", line)
        if self.depth >= MAX_DEPTH:
            raise GbnRuntimeError("too much recursion", line)
        env = Env(fn.closure)
        for p, a in zip(fn.params, args):
            self.guard_name(p, line, "rebind")
            env.vars[p] = a
        self.depth += 1
        try:
            self.exec_block(fn.body, env)
        except ReturnSignal as r:
            return r.value, r.feeling
        except (BreakSignal, ContinueSignal):
            raise GbnRuntimeError("'break' or 'continue' outside a loop", line)
        finally:
            self.depth -= 1
        return None, None

    # ---- expressions ----

    def eval(self, e, env):
        t = type(e)
        if t is ast.Literal:
            return e.value
        if t is ast.Name:
            scope = env.lookup(e.name)
            if scope is None:
                raise GbnRuntimeError(f"'{e.name}' is not defined", e.line)
            return scope.vars[e.name]
        if t is ast.Template:
            return "".join(p if isinstance(p, str) else show(self.eval(p, env)) for p in e.parts)
        if t is ast.ListLit:
            return [self.eval(x, env) for x in e.items]
        if t is ast.MapLit:
            return {k: self.eval(v, env) for k, v in e.entries}
        if t is ast.FnLit:
            return Function("fn", e.params, e.body, env)
        if t is ast.Unary:
            v = self.eval(e.operand, env)
            if e.op == "not":
                return not truthy(v)
            if e.op == "~":
                if isinstance(v, Bits):
                    return Bits(~v.value & v.mask, v.width)
                if not _is_int(v):
                    raise GbnRuntimeError(f"'~' needs a whole number, got a {type_name(v)}", e.line)
                return ~int(v)
            if not _is_num(v):
                raise GbnRuntimeError(f"cannot negate a {type_name(v)}", e.line)
            return -v
        if t is ast.Binary:
            return self.binary(e, env)
        if t is ast.Call:
            fn = self.eval(e.callee, env)
            args = [self.eval(a, env) for a in e.args]
            return self.call(fn, args, e.line)
        if t is ast.Index:
            return self.index(self.eval(e.target, env), self.eval(e.index, env), e.line)
        if t is ast.Field:
            return self.field(self.eval(e.target, env), e.name, e.line)
        raise GbnRuntimeError(f"unknown expression {t.__name__}", e.line)  # pragma: no cover

    def binary(self, e, env):
        op = e.op
        if op == "and":
            left = self.eval(e.left, env)
            return self.eval(e.right, env) if truthy(left) else left
        if op == "or":
            left = self.eval(e.left, env)
            return left if truthy(left) else self.eval(e.right, env)
        a = self.eval(e.left, env)
        b = self.eval(e.right, env)
        if op == "==":
            return freeze(a) == freeze(b)
        if op == "!=":
            return freeze(a) != freeze(b)
        if op == "in":
            if isinstance(b, str) and isinstance(a, str):
                return a in b
            if isinstance(b, list):
                return any(freeze(a) == freeze(x) for x in b)
            if isinstance(b, dict):
                return a in b
            raise GbnRuntimeError(f"cannot look inside a {type_name(b)} with 'in'", e.line)
        if op == "+":
            if _is_num(a) and _is_num(b):
                return a + b
            if isinstance(a, str) and isinstance(b, str):
                return a + b
            if isinstance(a, list) and isinstance(b, list):
                return list(a) + list(b)
            if isinstance(a, Bits) and isinstance(b, Bits):
                return Bits((a.value << b.width) | b.value, a.width + b.width)  # join side by side
            raise GbnRuntimeError(f"cannot add a {type_name(a)} and a {type_name(b)}", e.line)
        if op in ("<", "<=", ">", ">="):
            if not ((_is_num(a) and _is_num(b)) or (isinstance(a, str) and isinstance(b, str))):
                raise GbnRuntimeError(f"cannot compare a {type_name(a)} and a {type_name(b)}", e.line)
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if op in ("&", "|", "^", "<<", ">>") and isinstance(a, Bits):
            return self.bit_op(op, a, b, e.line)
        if op in ("&", "|", "^", "<<", ">>"):
            if isinstance(b, Bits):
                raise GbnRuntimeError(f"cannot combine a number and bits with '{op}'; "
                                      "turn the number into bits with bits(n, width)", e.line)
            if not (_is_int(a) and _is_int(b)):
                raise GbnRuntimeError(f"'{op}' needs whole numbers, got a {type_name(a)} and a {type_name(b)}", e.line)
            a, b = int(a), int(b)
            if op in ("<<", ">>") and b < 0:
                raise GbnRuntimeError("cannot shift by a negative number of bits", e.line)
            if op == "<<" and b > 4096:
                raise GbnRuntimeError("shift is too large", e.line)
            if op == "&":
                return a & b
            if op == "|":
                return a | b
            if op == "^":
                return a ^ b
            return a << b if op == "<<" else a >> b
        if not (_is_num(a) and _is_num(b)):
            raise GbnRuntimeError(f"'{op}' needs numbers, got a {type_name(a)} and a {type_name(b)}", e.line)
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise GbnRuntimeError("division by zero", e.line)
        if op == "/":
            r = a / b
            return int(r) if isinstance(a, int) and isinstance(b, int) and r.is_integer() else r
        return a % b

    def bit_op(self, op, a, b, line):
        if op in ("<<", ">>"):
            if not _is_int(b) or b < 0:
                raise GbnRuntimeError("bits shift by a whole number of 0 or more", line)
            n = min(int(b), a.width)
            v = (a.value << n) & a.mask if op == "<<" else a.value >> n
            return Bits(v, a.width)
        if not isinstance(b, Bits):
            raise GbnRuntimeError(f"cannot combine bits and a {type_name(b)} with '{op}'; "
                                  "turn the number into bits with bits(n, width)", line)
        w = max(a.width, b.width)
        v = {"&": a.value & b.value, "|": a.value | b.value, "^": a.value ^ b.value}[op]
        return Bits(v, w)

    def index(self, obj, key, line):
        if isinstance(obj, (list, str, Bits)):
            if not _is_int(key):
                raise GbnRuntimeError("index must be a whole number", line)
            if not -len(obj) <= key < len(obj):
                raise GbnRuntimeError(f"index {key} is out of range", line)
            return obj[int(key)]
        if isinstance(obj, dict):
            return obj.get(key)
        raise GbnRuntimeError(f"cannot index a {type_name(obj)}", line)

    def field(self, obj, name, line):
        if isinstance(obj, dict):
            return obj.get(name)
        if isinstance(obj, (Verdict, Bond)):
            if name not in obj.FIELDS:
                raise GbnRuntimeError(f"a {type_name(obj)} has no field '{name}'", line)
            return obj.get(name)
        if isinstance(obj, (Member, Coalition, Function)) and name == "name":
            return obj.name
        if isinstance(obj, Member) and name == "trust":
            return obj.trust
        raise GbnRuntimeError(f"a {type_name(obj)} has no field '{name}'", line)


def truthy(v):
    if v is None or v is False:
        return False
    if _is_num(v):
        return v != 0
    if isinstance(v, Bits):
        return v.value != 0
    if isinstance(v, (str, list, dict)):
        return len(v) > 0
    return True


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    return _is_num(v) and float(v).is_integer()


def _feeling(v):
    return None if v is None else show(v)
