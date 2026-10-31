"""Recursive-descent parser: tokens in, list of statements out."""

from . import ast
from .errors import GbnSyntaxError
from .lexer import tokenize
from .values import Bits

RULES = {"majority", "plurality", "unanimous", "quorum", "threshold"}
RULES_WITH_ARG = {"quorum", "threshold"}
COALITION_FIELDS = {"members", "rule", "veto", "tie", "key", "learn", "weights", "min_votes"}

BOND_FIELDS = {"human", "ai", "keep", "key"}

COMPARE = {"==", "!=", "<", "<=", ">", ">="}


def parse(src):
    return Parser(tokenize(src)).program()


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    # ---- helpers ----

    @property
    def tok(self):
        return self.toks[self.pos]

    def peek(self, k=1):
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def advance(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def error(self, msg, tok=None):
        tok = tok or self.tok
        found = "end of file" if tok.kind == "EOF" else repr(tok.value)
        raise GbnSyntaxError(f"{msg} (found {found})", tok.line)

    def expect_op(self, op):
        if not self.tok.is_op(op):
            self.error(f"expected '{op}'")
        return self.advance()

    def expect_kw(self, kw):
        if not self.tok.is_kw(kw):
            self.error(f"expected '{kw}'")
        return self.advance()

    def expect_ident(self, what="a name"):
        if self.tok.kind != "IDENT":
            self.error(f"expected {what}")
        return self.advance().value

    def accept_op(self, op):
        if self.tok.is_op(op):
            self.advance()
            return True
        return False

    # ---- statements ----

    def program(self):
        stmts = []
        while self.tok.kind != "EOF":
            s = self.statement()
            if s is not None:
                stmts.append(s)
        return stmts

    def block(self):
        self.expect_op("{")
        stmts = []
        while not self.tok.is_op("}"):
            if self.tok.kind == "EOF":
                self.error("expected '}' to close the block")
            s = self.statement()
            if s is not None:
                stmts.append(s)
        self.advance()
        return stmts

    def params(self):
        self.expect_op("(")
        names = []
        if not self.tok.is_op(")"):
            while True:
                names.append(self.expect_ident("a parameter name"))
                if not self.accept_op(","):
                    break
        self.expect_op(")")
        if len(set(names)) != len(names):
            self.error("duplicate parameter name")
        return names

    def statement(self):
        t = self.tok
        line = t.line
        if t.is_op(";"):
            self.advance()
            return None
        if t.is_kw("let"):
            self.advance()
            name = self.expect_ident()
            self.expect_op("=")
            return ast.Let(line, name, self.expression())
        if t.is_kw("fn") and self.peek().kind == "IDENT":
            self.advance()
            name = self.advance().value
            return ast.FnDecl(line, name, self.params(), self.block())
        if t.is_kw("member"):
            self.advance()
            name = self.expect_ident("a member name")
            params = self.params()
            trust = None
            if self.tok.kind == "IDENT" and self.tok.value == "trust":
                self.advance()
                trust = self.expression()
            return ast.MemberDecl(line, name, params, trust, self.block())
        if t.is_kw("coalition"):
            return self.coalition()
        if t.is_kw("bond"):
            return self.bond()
        if t.is_kw("vow"):
            self.advance()
            bond = self.expect_ident("a bond name")
            self.expect_op(".")
            vname = self.expect_ident("a vow name")
            self.expect_op("=")
            return ast.VowStmt(line, bond, ast.VowDef(line, vname, self.expression()))
        if t.is_kw("remember", "amend"):
            self.advance()
            bond = self.expect_ident("a bond name")
            amends = self.expression() if t.value == "amend" else None
            text = self.expression()
            by = None
            if self.tok.is_kw("by"):
                self.advance()
                by = self.expect_ident("'human' or 'ai'")
                if by not in ("human", "ai"):
                    self.error("expected 'human' or 'ai' after 'by'", self.toks[self.pos - 1])
            return ast.Remember(line, bond, text, by, self.feeling(), amends)
        if t.is_kw("return"):
            self.advance()
            value = None
            if not (self.tok.is_op("}") or self.tok.kind == "EOF" or self.tok.is_kw("with")):
                value = self.expression()
            return ast.Return(line, value, self.feeling())
        if t.is_kw("abstain"):
            self.advance()
            reason = self.expression() if self.tok.kind == "STRING" else None
            return ast.Abstain(line, reason)
        if t.is_kw("if"):
            return self.if_stmt()
        if t.is_kw("while"):
            self.advance()
            return ast.While(line, self.expression(), self.block())
        if t.is_kw("for"):
            self.advance()
            var = self.expect_ident("a loop variable")
            self.expect_kw("in")
            return ast.For(line, var, self.expression(), self.block())
        if t.is_kw("break"):
            self.advance()
            return ast.Break(line)
        if t.is_kw("continue"):
            self.advance()
            return ast.Continue(line)
        if t.is_kw("match"):
            return self.match_stmt()
        expr = self.expression()
        if self.tok.is_op("="):
            if not isinstance(expr, (ast.Name, ast.Index, ast.Field)):
                self.error("can only assign to a name, an index or a field")
            self.advance()
            return ast.Assign(line, expr, self.expression())
        return ast.ExprStmt(line, expr)

    def if_stmt(self):
        line = self.expect_kw("if").line
        cond = self.expression()
        then = self.block()
        otherwise = None
        if self.tok.is_kw("else"):
            self.advance()
            otherwise = [self.if_stmt()] if self.tok.is_kw("if") else self.block()
        return ast.If(line, cond, then, otherwise)

    def match_stmt(self):
        line = self.expect_kw("match").line
        subject = self.expression()
        self.expect_op("{")
        arms = {}
        while not self.tok.is_op("}"):
            t = self.tok
            if t.kind != "IDENT" or t.value not in ("agreed", "split"):
                self.error("expected an 'agreed' or 'split' arm")
            if t.value in arms:
                self.error(f"duplicate '{t.value}' arm")
            self.advance()
            name = self.advance().value if self.tok.kind == "IDENT" else None
            arms[t.value] = (name, self.block())
        self.advance()
        if not arms:
            self.error("a match needs at least one arm")
        a_name, a_body = arms.get("agreed", (None, None))
        s_name, s_body = arms.get("split", (None, None))
        return ast.Match(line, subject, a_name, a_body, s_name, s_body)

    def feeling(self):
        """Parse an optional ``with feeling <expr>`` suffix."""
        if not self.tok.is_kw("with"):
            return None
        self.advance()
        if not (self.tok.kind == "IDENT" and self.tok.value == "feeling"):
            self.error("expected 'feeling' after 'with'")
        self.advance()
        return self.expression()

    def bond(self):
        line = self.expect_kw("bond").line
        name = self.expect_ident("a bond name")
        self.expect_op("{")
        fields, vows = {}, []
        while not self.tok.is_op("}"):
            ftok = self.tok
            if ftok.is_kw("vow"):
                self.advance()
                vname = self.expect_ident("a vow name")
                self.expect_op(":")
                if any(v.name == vname for v in vows):
                    self.error(f"vow '{vname}' made twice", ftok)
                vows.append(ast.VowDef(ftok.line, vname, self.expression()))
            elif ftok.kind == "IDENT" and ftok.value in BOND_FIELDS:
                if ftok.value in fields:
                    self.error(f"field '{ftok.value}' given twice")
                self.advance()
                self.expect_op(":")
                fields[ftok.value] = self.expression()
            else:
                self.error("expected a bond field (human, ai, keep, key) or a vow")
            self.accept_op(",") or self.accept_op(";")
        self.advance()
        for need in ("human", "ai"):
            if need not in fields:
                raise GbnSyntaxError(f"bond '{name}' needs a '{need}' partner", line)
        return ast.BondDecl(line, name, vows=vows, **fields)

    def coalition(self):
        line = self.expect_kw("coalition").line
        name = self.expect_ident("a coalition name")
        params = self.params()
        self.expect_op("{")
        fields = {}
        while not self.tok.is_op("}"):
            ftok = self.tok
            if ftok.kind != "IDENT" or ftok.value not in COALITION_FIELDS:
                self.error("expected a coalition field (" + ", ".join(sorted(COALITION_FIELDS)) + ")")
            if ftok.value in fields:
                self.error(f"field '{ftok.value}' given twice")
            self.advance()
            self.expect_op(":")
            fname = ftok.value
            if fname in ("members", "veto"):
                items = [self.expression()]
                while self.accept_op(","):
                    items.append(self.expression())
                fields[fname] = items
            elif fname == "rule":
                rtok = self.tok
                if rtok.kind != "IDENT" or rtok.value not in RULES:
                    self.error("expected a rule (" + ", ".join(sorted(RULES)) + ")")
                self.advance()
                arg = self.expression() if rtok.value in RULES_WITH_ARG else None
                fields["rule"] = ast.Rule(rtok.line, rtok.value, arg)
            else:
                fields[fname] = self.expression()
            self.accept_op(",") or self.accept_op(";")
        self.advance()
        if "members" not in fields:
            raise GbnSyntaxError(f"coalition '{name}' has no members", line)
        rule = fields.pop("rule", None) or ast.Rule(line, "majority")
        members = fields.pop("members")
        return ast.CoalitionDecl(line, name, params, members, rule, **fields)

    # ---- expressions ----

    def expression(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        while self.tok.is_kw("or"):
            line = self.advance().line
            left = ast.Binary(line, "or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.tok.is_kw("and"):
            line = self.advance().line
            left = ast.Binary(line, "and", left, self.not_expr())
        return left

    def not_expr(self):
        if self.tok.is_kw("not"):
            line = self.advance().line
            return ast.Unary(line, "not", self.not_expr())
        return self.comparison()

    def comparison(self):
        left = self.bit_or()
        while (self.tok.kind == "OP" and self.tok.value in COMPARE) or self.tok.is_kw("in"):
            t = self.advance()
            left = ast.Binary(t.line, t.value, left, self.bit_or())
        return left

    def _binary_level(self, ops, next_level):
        left = next_level()
        while self.tok.kind == "OP" and self.tok.value in ops:
            t = self.advance()
            left = ast.Binary(t.line, t.value, left, next_level())
        return left

    def bit_or(self):
        return self._binary_level(("|",), self.bit_xor)

    def bit_xor(self):
        return self._binary_level(("^",), self.bit_and)

    def bit_and(self):
        return self._binary_level(("&",), self.shift)

    def shift(self):
        return self._binary_level(("<<", ">>"), self.additive)

    def additive(self):
        left = self.term()
        while self.tok.is_op("+", "-"):
            t = self.advance()
            left = ast.Binary(t.line, t.value, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.tok.is_op("*", "/", "%"):
            t = self.advance()
            left = ast.Binary(t.line, t.value, left, self.unary())
        return left

    def unary(self):
        if self.tok.is_op("-", "~"):
            t = self.advance()
            return ast.Unary(t.line, t.value, self.unary())
        return self.postfix()

    def postfix(self):
        expr = self.primary()
        while True:
            t = self.tok
            if t.is_op("("):
                self.advance()
                args = []
                if not self.tok.is_op(")"):
                    while True:
                        args.append(self.expression())
                        if not self.accept_op(","):
                            break
                self.expect_op(")")
                expr = ast.Call(t.line, expr, args)
            elif t.is_op("["):
                self.advance()
                idx = self.expression()
                self.expect_op("]")
                expr = ast.Index(t.line, expr, idx)
            elif t.is_op("."):
                self.advance()
                if self.tok.kind not in ("IDENT", "KEYWORD"):
                    self.error("expected a field name after '.'")
                expr = ast.Field(t.line, expr, self.advance().value)
            else:
                return expr

    def primary(self):
        t = self.tok
        if t.kind == "NUMBER":
            self.advance()
            return ast.Literal(t.line, t.value)
        if t.kind == "BITS":
            self.advance()
            return ast.Literal(t.line, Bits(*t.value))
        if t.kind == "STRING":
            self.advance()
            return self.template(t.value, t.line)
        if t.is_kw("true", "false", "none"):
            self.advance()
            return ast.Literal(t.line, {"true": True, "false": False, "none": None}[t.value])
        if t.kind == "IDENT":
            self.advance()
            return ast.Name(t.line, t.value)
        if t.is_op("("):
            self.advance()
            e = self.expression()
            self.expect_op(")")
            return e
        if t.is_op("["):
            self.advance()
            items = []
            while not self.tok.is_op("]"):
                items.append(self.expression())
                if not self.accept_op(","):
                    break
            self.expect_op("]")
            return ast.ListLit(t.line, items)
        if t.is_op("{"):
            self.advance()
            entries = []
            while not self.tok.is_op("}"):
                k = self.tok
                if k.kind in ("IDENT", "KEYWORD", "STRING"):
                    self.advance()
                else:
                    self.error("expected a map key")
                self.expect_op(":")
                entries.append((k.value, self.expression()))
                if not self.accept_op(","):
                    break
            self.expect_op("}")
            return ast.MapLit(t.line, entries)
        if t.is_kw("fn"):
            self.advance()
            return ast.FnLit(t.line, self.params(), self.block())
        self.error("expected an expression")

    def template(self, raw, line):
        """Split a string into literal text and {expression} parts."""
        parts, buf, i = [], [], 0
        while i < len(raw):
            c = raw[i]
            if c == "{":
                depth, j = 1, i + 1
                while j < len(raw) and depth:
                    if raw[j] == "{":
                        depth += 1
                    elif raw[j] == "}":
                        depth -= 1
                    j += 1
                if depth:
                    raise GbnSyntaxError("unclosed '{' in string (write \\{ for a literal brace)", line)
                inner = raw[i + 1:j - 1]
                if not inner.strip():
                    raise GbnSyntaxError("empty {} in string", line)
                if buf:
                    parts.append(_unescape("".join(buf)))
                    buf = []
                sub = Parser(tokenize(inner, line))
                expr = sub.expression()
                if sub.tok.kind != "EOF":
                    sub.error("unexpected text inside {...}")
                parts.append(expr)
                i = j
            elif c == "}":
                raise GbnSyntaxError("unmatched '}' in string (write \\} for a literal brace)", line)
            else:
                buf.append(c)
                i += 1
        if buf:
            parts.append(_unescape("".join(buf)))
        if all(isinstance(p, str) for p in parts):
            return ast.Literal(line, "".join(parts))
        return ast.Template(line, parts)


def _unescape(s):
    return s.replace("\x00", "{").replace("\x01", "}")
