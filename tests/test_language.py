import io
import unittest

from sutra import Interpreter, SutraRuntimeError, SutraSyntaxError, parse


def run(source):
    out = io.StringIO()
    Interpreter(out=out, model="mock").run(source)
    return out.getvalue()


class SyntaxTests(unittest.TestCase):
    def test_parses_program(self):
        program = parse('let x = 1\nprint("{x}")')
        self.assertEqual([s.kind for s in program.body], ["Let", "ExprStmt"])

    def test_unterminated_string(self):
        with self.assertRaises(SutraSyntaxError) as ctx:
            parse('let x = "oops')
        self.assertIn("unterminated", str(ctx.exception))

    def test_missing_brace_reports_line(self):
        with self.assertRaises(SutraSyntaxError) as ctx:
            parse("if true {\n  print(1)\n")
        self.assertIn("line 1", str(ctx.exception))

    def test_prompt_needs_user_message(self):
        with self.assertRaises(SutraSyntaxError):
            parse('prompt p { system: "hi" }')

    def test_union_of_non_literals_rejected(self):
        with self.assertRaises(SutraSyntaxError):
            parse("type T = str | num")

    def test_newline_breaks_call(self):
        # The parenthesised expression on the next line is a new statement, not a call.
        self.assertEqual(run("let f = 1\n(print(2))"), "2\n")


class BasicsTests(unittest.TestCase):
    def test_arithmetic_and_interpolation(self):
        self.assertEqual(run('let a = 7\nprint("{a} * 6 = {a * 6}")'), "7 * 6 = 42\n")

    def test_division(self):
        self.assertEqual(run("print(10 / 2, 7 / 2, 7 % 3)"), "5 3.5 1\n")

    def test_string_concat(self):
        self.assertEqual(run('print("n=" + 3)'), "n=3\n")

    def test_escaped_braces(self):
        self.assertEqual(run('print("\\{\\"a\\": 1\\}")'), '{"a": 1}\n')

    def test_quotes_inside_interpolation(self):
        self.assertEqual(run('let xs = ["a", "b"]\nprint("{join(xs, ", ")}")'), "a, b\n")

    def test_triple_quoted_dedent(self):
        src = 'let t = """\n    one\n      two\n    """\nprint(t)'
        self.assertEqual(run(src), "one\n  two\n")

    def test_functions_closures_recursion(self):
        src = """
        fn counter() {
          let n = 0
          return fn() { n += 1
            return n }
        }
        let c = counter()
        c()
        c()
        print(c())
        fn fact(n) { if n <= 1 { return 1 } return n * fact(n - 1) }
        print(fact(5))
        """
        self.assertEqual(run(src), "3\n120\n")

    def test_default_and_named_args(self):
        src = 'fn greet(name, greeting = "Hi") { return "{greeting}, {name}" }\nprint(greet("A"), greet(greeting: "Yo", name: "B"))'
        self.assertEqual(run(src), "Hi, A Yo, B\n")

    def test_control_flow(self):
        src = """
        let out = []
        for i in range(10) {
          if i % 2 == 0 { continue }
          if i > 7 { break }
          push(out, i)
        }
        let n = 0
        while n < 3 { n += 1 }
        print(out, n)
        if n == 1 { print("one") } else if n == 3 { print("three") } else { print("other") }
        """
        self.assertEqual(run(src), "[1, 3, 5, 7] 3\nthree\n")

    def test_maps_and_lists(self):
        src = """
        let m = {a: 1, "b c": 2}
        m.d = 4
        m["a"] = 10
        let xs = [3, 1, 2]
        xs[0] = 0
        print(m.a, m["b c"], m.d, sort(xs), "a" in m, 5 not in xs, len(m))
        """
        self.assertEqual(run(src), "10 2 4 [0, 1, 2] true true 3\n")

    def test_logic(self):
        self.assertEqual(run('print(none or "x", 0 and 1, not [], true and "y")'), "x 0 true y\n")

    def test_try_catch_and_throw(self):
        src = """
        try { throw {code: 42} } catch e { print(e.code) }
        try { let x = [1][5] } catch e { print(e) }
        """
        self.assertEqual(run(src), "42\nindex 5 is out of range for a list of length 1\n")

    def test_undefined_name(self):
        with self.assertRaises(SutraRuntimeError) as ctx:
            run("print(nope)")
        self.assertIn("'nope' is not defined", str(ctx.exception))

    def test_assign_requires_let(self):
        with self.assertRaises(SutraRuntimeError):
            run("x = 1")

    def test_type_errors(self):
        with self.assertRaises(SutraRuntimeError) as ctx:
            run("print(1 - [])")
        self.assertIn("cannot apply '-'", str(ctx.exception))

    def test_runtime_error_has_line(self):
        with self.assertRaises(SutraRuntimeError) as ctx:
            run("let a = 1\n\nlet b = a / 0")
        self.assertEqual(ctx.exception.line, 3)

    def test_builtins(self):
        src = 'print(upper("a"), trim("  b "), split("x y"), json({k: [1, true, none]}), parse_json("[1]"), type_of(1.5), words("a b c"))'
        self.assertEqual(run(src), 'A b ["x", "y"] {"k": [1, true, null]} [1] num 3\n')

    def test_higher_order(self):
        src = "print(filter(range(6), fn(x) { return x % 2 == 0 }), sort([3, 1, 2], fn(x) { return -x }))"
        self.assertEqual(run(src), "[0, 2, 4] [3, 2, 1]\n")


if __name__ == "__main__":
    unittest.main()
