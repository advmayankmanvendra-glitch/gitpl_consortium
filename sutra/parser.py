"""Recursive-descent parser producing ``Node`` trees from tokens."""

from .ast import Node
from .errors import SutraSyntaxError
from .lexer import Interp, tokenize

COMPARISON_OPS = ("==", "!=", "<", ">", "<=", ">=")
ASSIGN_TARGETS = ("Name", "Index", "Member")


def parse(source):
    return Parser(tokenize(source)).parse_program()


def parse_expression_source(source, line):
    """Parse the source of a ``{...}`` interpolation into an expression node."""
    tokens = tokenize(source)
    for tok in tokens:
        tok.line += line - 1
    parser = Parser(tokens)
    expr = parser.parse_expr()
    if parser.peek().kind != "EOF":
        raise SutraSyntaxError(f"unexpected {parser.describe(parser.peek())} in interpolation", line)
    return expr


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ---------------------------------------------------------------- helpers
    def peek(self, offset=0):
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    @staticmethod
    def describe(tok):
        if tok.kind == "EOF":
            return "end of file"
        if tok.kind == "STRING":
            return "string"
        return f"'{tok.value}'"

    def error(self, message, tok=None):
        tok = tok or self.peek()
        return SutraSyntaxError(message, tok.line)

    def expect_op(self, op):
        tok = self.peek()
        if not tok.is_op(op):
            raise self.error(f"expected '{op}' but found {self.describe(tok)}")
        return self.advance()

    def expect_kw(self, kw):
        tok = self.peek()
        if not tok.is_kw(kw):
            raise self.error(f"expected '{kw}' but found {self.describe(tok)}")
        return self.advance()

    def expect_ident(self, what="a name"):
        tok = self.peek()
        if tok.kind != "IDENT":
            raise self.error(f"expected {what} but found {self.describe(tok)}")
        return self.advance()

    def match_op(self, *ops):
        if self.peek().is_op(*ops):
            return self.advance()
        return None

    def skip_separators(self):
        while self.match_op(";", ","):
            pass

    # ------------------------------------------------------------- statements
    def parse_program(self):
        body = []
        self.skip_separators()
        while self.peek().kind != "EOF":
            body.append(self.parse_statement())
            self.skip_separators()
        return Node("Program", 1, body=body)

    def parse_block(self):
        start = self.expect_op("{")
        body = []
        self.skip_separators()
        while not self.peek().is_op("}"):
            if self.peek().kind == "EOF":
                raise self.error("missing '}' to close block", start)
            body.append(self.parse_statement())
            self.skip_separators()
        self.advance()
        return body

    def parse_statement(self):
        tok = self.peek()
        if tok.kind == "KEYWORD":
            handler = getattr(self, f"stmt_{tok.value}", None)
            if handler is not None:
                return handler()
        expr = self.parse_expr()
        assign = self.match_op("=", "+=", "-=")
        if assign:
            if expr.kind not in ASSIGN_TARGETS:
                raise self.error("can only assign to a name, index or field", assign)
            value = self.parse_expr()
            return Node("Assign", assign.line, target=expr, op=assign.value, value=value)
        return Node("ExprStmt", tok.line, expr=expr)

    def stmt_let(self):
        tok = self.advance()
        name = self.expect_ident("a variable name").value
        self.expect_op("=")
        return Node("Let", tok.line, name=name, value=self.parse_expr())

    def stmt_fn(self):
        # `fn name(...)` is a declaration; a bare `fn(...)` is a lambda expression.
        if self.peek(1).kind != "IDENT":
            return Node("ExprStmt", self.peek().line, expr=self.parse_expr())
        tok = self.advance()
        name = self.expect_ident("a function name").value
        params = self.parse_params()
        body = self.parse_block()
        return Node("FnDecl", tok.line, name=name, params=params, body=body)

    def stmt_prompt(self):
        tok = self.advance()
        name = self.expect_ident("a prompt name").value
        params = self.parse_params() if self.peek().is_op("(") else []
        messages = []
        if self.peek().kind == "STRING":
            messages.append(("user", self.parse_expr()))
        elif self.peek().is_op("{"):
            start = self.advance()
            self.skip_separators()
            while not self.peek().is_op("}"):
                if self.peek().kind == "EOF":
                    raise self.error("missing '}' to close prompt", start)
                role_tok = self.expect_ident("'system', 'user' or 'assistant'")
                if role_tok.value not in ("system", "user", "assistant"):
                    raise self.error(
                        f"unknown prompt role '{role_tok.value}' (use system, user or assistant)", role_tok
                    )
                self.expect_op(":")
                messages.append((role_tok.value, self.parse_expr()))
                self.skip_separators()
            self.advance()
        else:
            raise self.error("expected a string or '{' after prompt signature")
        if not any(role == "user" for role, _ in messages):
            raise self.error(f"prompt '{name}' needs at least one user message", tok)
        return Node("PromptDecl", tok.line, name=name, params=params, messages=messages)

    def stmt_tool(self):
        tok = self.advance()
        name = self.expect_ident("a tool name").value
        params = self.parse_params()
        description = None
        if self.peek().kind == "STRING":
            description = self.parse_primary()
        body = self.parse_block()
        return Node("ToolDecl", tok.line, name=name, params=params, description=description, body=body)

    def stmt_agent(self):
        tok = self.advance()
        name = self.expect_ident("an agent name").value
        start = self.expect_op("{")
        entries = []
        self.skip_separators()
        while not self.peek().is_op("}"):
            if self.peek().kind == "EOF":
                raise self.error("missing '}' to close agent", start)
            key = self.expect_ident("an agent setting").value
            self.expect_op(":")
            entries.append((key, self.parse_expr()))
            self.skip_separators()
        self.advance()
        return Node("AgentDecl", tok.line, name=name, entries=entries)

    def stmt_type(self):
        tok = self.advance()
        name = self.expect_ident("a type name").value
        self.expect_op("=")
        return Node("TypeDecl", tok.line, name=name, type=self.parse_type())

    def stmt_use(self):
        tok = self.advance()
        return Node("Use", tok.line, model=self.parse_expr())

    def stmt_if(self):
        tok = self.advance()
        cond = self.parse_expr()
        body = self.parse_block()
        orelse = []
        if self.peek().is_kw("else"):
            self.advance()
            if self.peek().is_kw("if"):
                orelse = [self.stmt_if()]
            else:
                orelse = self.parse_block()
        return Node("If", tok.line, cond=cond, body=body, orelse=orelse)

    def stmt_while(self):
        tok = self.advance()
        cond = self.parse_expr()
        return Node("While", tok.line, cond=cond, body=self.parse_block())

    def stmt_for(self):
        tok = self.advance()
        names = [self.expect_ident("a loop variable").value]
        if self.match_op(","):
            names.append(self.expect_ident("a loop variable").value)
        self.expect_kw("in")
        iterable = self.parse_expr()
        return Node("For", tok.line, names=names, iterable=iterable, body=self.parse_block())

    def stmt_return(self):
        tok = self.advance()
        nxt = self.peek()
        if nxt.nl_before or nxt.is_op("}", ";") or nxt.kind == "EOF":
            return Node("Return", tok.line, value=None)
        return Node("Return", tok.line, value=self.parse_expr())

    def stmt_break(self):
        return Node("Break", self.advance().line)

    def stmt_continue(self):
        return Node("Continue", self.advance().line)

    def stmt_throw(self):
        tok = self.advance()
        return Node("Throw", tok.line, value=self.parse_expr())

    def stmt_try(self):
        tok = self.advance()
        body = self.parse_block()
        self.expect_kw("catch")
        name = self.expect_ident("an error variable").value
        handler = self.parse_block()
        return Node("Try", tok.line, body=body, name=name, handler=handler)

    def parse_params(self):
        self.expect_op("(")
        params = []
        while not self.peek().is_op(")"):
            name_tok = self.expect_ident("a parameter name")
            ptype = None
            default = None
            if self.match_op(":"):
                ptype = self.parse_type()
            if self.match_op("="):
                default = self.parse_expr()
            params.append(Node("Param", name_tok.line, name=name_tok.value, type=ptype, default=default))
            if not self.match_op(","):
                break
        self.expect_op(")")
        seen_default = False
        for p in params:
            if p.default is not None:
                seen_default = True
            elif seen_default:
                raise SutraSyntaxError(f"parameter '{p.name}' without a default follows one with a default", p.line)
        return params

    # ------------------------------------------------------------------ types
    def parse_type(self):
        first = self.parse_type_atom()
        if not self.peek().is_op("|"):
            return first
        options = [first]
        while self.match_op("|"):
            options.append(self.parse_type_atom())
        if any(o.kind != "TLiteral" for o in options):
            raise self.error("unions are only supported between string literals, e.g. \"yes\" | \"no\"")
        return Node("TEnum", first.line, values=[o.value for o in options])

    def parse_type_atom(self):
        tok = self.peek()
        if tok.kind == "IDENT":
            self.advance()
            return Node("TName", tok.line, name=tok.value)
        if tok.kind == "STRING":
            if tok.value is None:
                raise self.error("string literal types cannot contain interpolation")
            self.advance()
            return Node("TLiteral", tok.line, value=tok.value)
        if tok.is_op("["):
            self.advance()
            elem = self.parse_type()
            self.expect_op("]")
            return Node("TList", tok.line, elem=elem)
        if tok.is_op("{"):
            self.advance()
            fields = []
            self.skip_separators()
            while not self.peek().is_op("}"):
                ftok = self.peek()
                if ftok.kind not in ("IDENT", "KEYWORD", "STRING") or ftok.value is None:
                    raise self.error("expected a field name")
                self.advance()
                optional = bool(self.match_op("?"))
                self.expect_op(":")
                fields.append((ftok.value, self.parse_type(), optional))
                self.skip_separators()
            self.advance()
            return Node("TObject", tok.line, fields=fields)
        raise self.error(f"expected a type but found {self.describe(tok)}")

    # ------------------------------------------------------------ expressions
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek().is_kw("or"):
            tok = self.advance()
            left = Node("Logical", tok.line, op="or", left=left, right=self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek().is_kw("and"):
            tok = self.advance()
            left = Node("Logical", tok.line, op="and", left=left, right=self.parse_not())
        return left

    def parse_not(self):
        if self.peek().is_kw("not"):
            tok = self.advance()
            return Node("Unary", tok.line, op="not", operand=self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        while True:
            tok = self.peek()
            if tok.kind == "OP" and tok.value in COMPARISON_OPS:
                self.advance()
                left = Node("Binary", tok.line, op=tok.value, left=left, right=self.parse_additive())
            elif tok.is_kw("in"):
                self.advance()
                left = Node("Binary", tok.line, op="in", left=left, right=self.parse_additive())
            elif tok.is_kw("not") and self.peek(1).is_kw("in"):
                self.advance()
                self.advance()
                left = Node("Binary", tok.line, op="not in", left=left, right=self.parse_additive())
            else:
                return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.peek().is_op("+", "-"):
            tok = self.advance()
            left = Node("Binary", tok.line, op=tok.value, left=left, right=self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.peek().is_op("*", "/", "%"):
            tok = self.advance()
            left = Node("Binary", tok.line, op=tok.value, left=left, right=self.parse_unary())
        return left

    def parse_unary(self):
        tok = self.peek()
        if tok.is_op("-"):
            self.advance()
            return Node("Unary", tok.line, op="-", operand=self.parse_unary())
        if tok.is_kw("ask"):
            return self.parse_ask()
        return self.parse_postfix()

    def parse_ask(self):
        tok = self.advance()
        prompt = self.parse_additive()
        model = None
        out_type = None
        while True:
            if self.peek().is_kw("using") and model is None:
                self.advance()
                model = self.parse_postfix()
            elif self.peek().is_kw("as") and out_type is None:
                self.advance()
                out_type = self.parse_type()
            else:
                break
        return Node("Ask", tok.line, prompt=prompt, model=model, type=out_type)

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            tok = self.peek()
            # A newline before '(' or '[' starts a new statement, not a call/index.
            if tok.is_op("(") and not tok.nl_before:
                self.advance()
                args, kwargs = self.parse_call_args()
                expr = Node("Call", tok.line, callee=expr, args=args, kwargs=kwargs)
            elif tok.is_op("[") and not tok.nl_before:
                self.advance()
                index = self.parse_expr()
                self.expect_op("]")
                expr = Node("Index", tok.line, obj=expr, index=index)
            elif tok.is_op("."):
                self.advance()
                name_tok = self.peek()
                if name_tok.kind not in ("IDENT", "KEYWORD"):
                    raise self.error("expected a field name after '.'")
                self.advance()
                expr = Node("Member", tok.line, obj=expr, name=name_tok.value)
            else:
                return expr

    def parse_call_args(self):
        args = []
        kwargs = []
        while not self.peek().is_op(")"):
            if self.peek().kind == "IDENT" and self.peek(1).is_op(":"):
                name = self.advance().value
                self.advance()
                kwargs.append((name, self.parse_expr()))
            else:
                if kwargs:
                    raise self.error("positional argument after named argument")
                args.append(self.parse_expr())
            if not self.match_op(","):
                break
        self.expect_op(")")
        return args, kwargs

    def parse_string(self, tok):
        parts = []
        for part in tok.parts:
            if isinstance(part, Interp):
                parts.append(parse_expression_source(part.source, part.line))
            else:
                parts.append(part)
        if len(parts) == 1 and isinstance(parts[0], str):
            return Node("Literal", tok.line, value=parts[0])
        return Node("Template", tok.line, parts=parts)

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            return Node("Literal", tok.line, value=tok.value)
        if tok.kind == "STRING":
            self.advance()
            return self.parse_string(tok)
        if tok.kind == "IDENT":
            self.advance()
            return Node("Name", tok.line, name=tok.value)
        if tok.is_kw("true", "false", "none"):
            self.advance()
            return Node("Literal", tok.line, value={"true": True, "false": False, "none": None}[tok.value])
        if tok.is_kw("fn"):
            self.advance()
            params = self.parse_params()
            body = self.parse_block()
            return Node("Lambda", tok.line, params=params, body=body)
        if tok.is_op("("):
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.is_op("["):
            self.advance()
            items = []
            while not self.peek().is_op("]"):
                items.append(self.parse_expr())
                if not self.match_op(","):
                    break
            self.expect_op("]")
            return Node("List", tok.line, items=items)
        if tok.is_op("{"):
            self.advance()
            entries = []
            while not self.peek().is_op("}"):
                key_tok = self.peek()
                if key_tok.kind in ("IDENT", "KEYWORD"):
                    key = key_tok.value
                elif key_tok.kind == "STRING" and key_tok.value is not None:
                    key = key_tok.value
                else:
                    raise self.error("expected a map key (a name or plain string)")
                self.advance()
                self.expect_op(":")
                entries.append((key, self.parse_expr()))
                self.match_op(",")
            self.expect_op("}")
            return Node("Map", tok.line, entries=entries)
        raise self.error(f"unexpected {self.describe(tok)}")
