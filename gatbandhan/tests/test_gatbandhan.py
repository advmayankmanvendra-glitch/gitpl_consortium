import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gatbandhan import BondError, GatbandhanError, GbnRuntimeError, GbnSyntaxError, Interpreter  # noqa: E402

CLOCK = lambda: "2026-10-31T00:00:00+00:00"  # noqa: E731

PARTNER = '''
member saathi(q) {
  if contains(lower(q), "together") { return "yes" with feeling "hopeful" }
  return "no" with feeling "careful"
}
'''

BOND = PARTNER + '''
bond us {
  human: "Asha"
  ai: saathi
  vow honesty: "We tell each other the truth."
}
'''


def run(src, stdin="", base_dir=None):
    out = io.StringIO()
    it = Interpreter(out=out, stdin=io.StringIO(stdin), clock=CLOCK, base_dir=base_dir)
    it.run(src)
    return out.getvalue(), it


def output(src, **kw):
    return run(src, **kw)[0]


class Basics(unittest.TestCase):
    def test_arithmetic_and_strings(self):
        self.assertEqual(output('print(1 + 2 * 3, 7 / 2, 6 / 3, 7 % 3, -2)'), "7 3.5 2 1 -2\n")
        self.assertEqual(output('let n = "Gat" print("{n}bandhan", len(n))'), "Gatbandhan 3\n")
        self.assertEqual(output(r'print("a \{literal\} brace")'), "a {literal} brace\n")

    def test_control_flow(self):
        src = '''
        let total = 0
        for i in range(10) {
          if i == 3 { continue }
          if i == 6 { break }
          total = total + i
        }
        let k = 0
        while k < 3 { k = k + 1 }
        print(total, k)
        '''
        self.assertEqual(output(src), "12 3\n")

    def test_functions_closures_and_recursion(self):
        src = '''
        fn fact(n) { if n <= 1 { return 1 } return n * fact(n - 1) }
        fn adder(x) { return fn(y) { return x + y } }
        let add2 = adder(2)
        print(fact(5), add2(40))
        '''
        self.assertEqual(output(src), "120 42\n")

    def test_lists_and_maps(self):
        src = '''
        let xs = [3, 1, 2]
        push(xs, 0)
        xs[0] = 9
        let m = {a: 1, "b c": 2}
        m.d = 4
        print(sort(xs), m, m.a, m["b c"], m.missing, 2 in xs, "a" in m)
        '''
        self.assertEqual(output(src), '[0, 1, 2, 9] {a: 1, "b c": 2, d: 4} 1 2 none true true\n')

    def test_equality_keeps_bools_and_numbers_apart(self):
        self.assertEqual(output("print(1 == true, 1 == 1.0, [1, 2] == [1, 2])"), "false true true\n")

    def test_syntax_errors_have_lines(self):
        with self.assertRaises(GbnSyntaxError) as cm:
            run("let x = 1\nlet = 2")
        self.assertEqual(cm.exception.line, 2)
        with self.assertRaises(GbnSyntaxError):
            run('print("unclosed {x")')
        with self.assertRaises(GbnSyntaxError):
            run("coalition c(x) { rule: majority }")

    def test_runtime_errors(self):
        for src in ["print(nope)", "x = 1", "print(1 / 0)", 'print(1 + "a")', "let xs = [1] print(xs[5])"]:
            with self.subTest(src=src), self.assertRaises(GbnRuntimeError):
                run(src)


class Coalitions(unittest.TestCase):
    MEMBERS = '''
    member keywords(msg) trust 2 {
      if contains(lower(msg), "winner") { return "spam" }
      return "ham"
    }
    member shouting(msg) { if upper(msg) == msg { return "spam" } return "ham" }
    member links(msg) {
      if not contains(msg, "http") { abstain "no links" }
      return "spam"
    }
    member broken(msg) { return 1 / 0 }
    '''

    def verdict(self, decl, call):
        _, it = run(self.MEMBERS + decl + f"\nlet v = {call}")
        return it.globals.vars["v"]

    def test_weighted_majority_with_abstentions_and_errors(self):
        v = self.verdict("coalition c(m) { members: keywords, shouting, links, broken }",
                         'c("You are a WINNER http://x")')
        self.assertTrue(v.agreed)
        self.assertEqual(v.decision, "spam")
        self.assertEqual(v.votes, {"keywords": "spam", "shouting": "ham", "links": "spam"})
        self.assertEqual(v.abstained, {"broken": "error: division by zero"})
        self.assertEqual(v.dissent, ["shouting"])
        self.assertAlmostEqual(v.margin, 0.75)

    def test_no_majority_and_tie_default(self):
        decl = "coalition c(m) { members: shouting, links  rule: majority }"
        v = self.verdict(decl, 'c("hi http")')
        self.assertFalse(v.agreed)
        self.assertEqual(v.reason, "tie")
        v = self.verdict('coalition c(m) { members: shouting, links  tie: "ham" }', 'c("hi http")')
        self.assertTrue(v.agreed and v.tiebreak)
        self.assertEqual(v.decision, "ham")
        self.assertEqual(v.dissent, ["links"])

    def test_unanimous_quorum_threshold(self):
        v = self.verdict("coalition c(m) { members: keywords, shouting  rule: unanimous }", 'c("winner")')
        self.assertEqual((v.agreed, v.reason), (False, "not unanimous"))
        v = self.verdict("coalition c(m) { members: keywords, shouting, links  rule: quorum 2 }", 'c("WINNER http")')
        self.assertTrue(v.agreed)
        v = self.verdict("coalition c(m) { members: keywords, shouting  rule: quorum 2 }", 'c("winner")')
        self.assertFalse(v.agreed)
        v = self.verdict("coalition c(m) { members: keywords, shouting  rule: threshold 0.6 }", 'c("winner")')
        self.assertTrue(v.agreed)  # 2 of 3 weight
        v = self.verdict("coalition c(m) { members: keywords, shouting  rule: threshold 0.7 }", 'c("winner")')
        self.assertFalse(v.agreed)

    def test_veto(self):
        v = self.verdict("coalition c(m) { members: keywords, links, shouting  veto: shouting }", 'c("winner http")')
        self.assertEqual((v.agreed, v.reason), (False, "vetoed by shouting"))

    def test_min_votes(self):
        v = self.verdict("coalition c(m) { members: links, broken  min_votes: 2 }", 'c("http")')
        self.assertFalse(v.agreed)
        self.assertIn("too few votes", v.reason)

    def test_weights_override_and_key(self):
        v = self.verdict("coalition c(m) { members: keywords, shouting }", 'c("winner")')
        self.assertEqual(v.decision, "spam")  # keywords has trust 2
        v = self.verdict("coalition c(m) { members: keywords, shouting  weights: {keywords: 0.5} }", 'c("winner")')
        self.assertEqual(v.decision, "ham")
        src = '''
        coalition c(x) {
          members: fn(x) { return "Yes" }, fn(x) { return "yes " }, fn(x) { return "no" }
          key: fn(a) { return trim(lower(a)) }
          rule: unanimous
        }
        '''
        v = self.verdict(src, "c(1)")
        self.assertEqual(v.votes, {"member1": "Yes", "member2": "yes ", "member3": "no"})
        self.assertFalse(v.agreed)

    def test_members_get_independent_copies(self):
        src = '''
        member greedy(xs) { push(xs, "mine") return len(xs) }
        member counter(xs) { return len(xs) }
        coalition c(xs) { members: greedy, counter  rule: unanimous }
        let data = [1]
        let v = c(data)
        print(v.agreed, data)
        '''
        self.assertEqual(output(src), "false [1]\n")

    def test_learning_trust(self):
        src = '''
        member yes(x) { return true }
        member no(x) { return false }
        member real(x) { return x > 0 }
        coalition c(x) { members: yes, no, real  rule: plurality  learn: 0.5 }
        c(1)
        print(trust(c), len(history(c)))
        '''
        self.assertEqual(output(src), "{yes: 1.5, no: 0.5, real: 1.5} 1\n")

    def test_nested_coalitions_and_scripted_models(self):
        src = '''
        script("m1", ["a", "b"])
        script("m2", ["a", "a"])
        member one(x) { return consult("m1", x) }
        member two(x) { return consult("m2", x) }
        coalition inner(x) { members: one, two  rule: unanimous }
        member fixed(x) { return "a" }
        coalition outer(x) { members: inner, fixed  rule: unanimous }
        print(outer("q"))
        print(outer("q"))
        '''
        out = output(src).splitlines()
        self.assertIn('agreed "a"', out[0])
        self.assertIn("agreed", out[1])  # inner split, so only `fixed` voted

    def test_feelings_from_members(self):
        src = '''
        member warm(x) { return "yes" with feeling "glad" }
        member cool(x) { return "yes" }
        coalition c(x) { members: warm, cool }
        print(c(1).feelings)
        '''
        self.assertEqual(output(src), '{warm: "glad"}\n')

    def test_match(self):
        src = self.MEMBERS + '''
        coalition c(m) { members: keywords, shouting  rule: unanimous }
        for m in ["WINNER", "winner"] {
          match c(m) {
            agreed d { print("agreed", d) }
            split why { print("split", why) }
          }
        }
        '''
        self.assertEqual(output(src), "agreed spam\nsplit not unanimous\n")


class Bonds(unittest.TestCase):
    def test_both_must_agree(self):
        src = BOND + '''
        script_human([{answer: "Yes ", feeling: "excited"}, "yes"])
        let a = us("Together?")
        let b = us("Ship it now?")
        print(a.agreed, a.decision, a.feelings)
        print(b.agreed, b.reason, b.votes)
        '''
        self.assertEqual(output(src).splitlines(), [
            'true Yes {Asha: "excited", saathi: "hopeful"}',
            'false the partners disagree {Asha: "yes", saathi: "no"}',
        ])

    def test_silence_is_not_consent(self):
        out, it = run(BOND + 'let v = us("Together?")', stdin="")
        v = it.globals.vars["v"]
        self.assertFalse(v.agreed)
        self.assertEqual(v.reason, "no consent: Asha did not answer")

    def test_human_answers_from_the_terminal(self):
        out, it = run(BOND + 'let v = us("Together?")', stdin="yes\nhopeful too\n")
        v = it.globals.vars["v"]
        self.assertTrue(v.agreed)
        self.assertEqual(v.feelings["Asha"], "hopeful too")
        self.assertIn("Asha, Together?", out)

    def test_model_partner(self):
        src = '''
        script("claude-test", [{answer: "yes", feeling: "warm"}, "\\{\\"answer\\": \\"no\\"\\}"])
        bond us { human: "M"  ai: "claude-test" }
        script_human(["yes", "yes"])
        print(us("one?").agreed, us("two?").agreed)
        '''
        self.assertEqual(output(src), "true false\n")

    def test_memory_is_append_only_and_amendable(self):
        src = BOND + '''
        remember us "We met." by human with feeling "shy"
        amend us 3 "We met on a Saturday."
        for e in memory(us) { print(e.n, e.kind, e.by, e.text, e.feeling, e.amends) }
        '''
        self.assertEqual(output(src).splitlines(), [
            "1 bond both Asha and saathi formed the bond 'us' none none",
            "2 vow both We tell each other the truth. none none",
            "3 memory Asha We met. shy none",
            "4 amend both We met on a Saturday. none 3",
        ])

    def test_new_vows_can_be_added_and_repeated(self):
        src = BOND + '''
        vow us.kindness = "Be patient."
        vow us.honesty = "We tell each other the truth."
        print(us.vows)
        '''
        self.assertEqual(output(src), '{honesty: "We tell each other the truth.", kindness: "Be patient."}\n')

    OVERWRITES = {
        'us.vows.honesty = "lies"': "change a sealed map",
        'vow us.honesty = "lies"': "overwrite the vow 'honesty'",
        "us = 1": "overwrite 'us'",
        "let us = 1": "rebind 'us'",
        "fn f() { let us = 2 } f()": "rebind 'us'",
        "fn us() {}": "redefine 'us'",
        "for us in [1] {}": "rebind 'us'",
        "push(memory(us), 1)": "change a sealed list",
        "let m = memory(us) m[0] = 1": "change a sealed list",
        'us.human = "someone else"': "overwrite human",
        'bond us { human: "x"  ai: "y" }': "declare the bond 'us' a second time",
        "member saathi2(q) { us.vows.honesty = 1 } coalition c(q) { members: saathi2 } c(1)":
            "change a sealed map",
    }

    def test_every_overwrite_is_refused_and_remembered(self):
        for stmt, msg in self.OVERWRITES.items():
            with self.subTest(stmt=stmt):
                it = Interpreter(out=io.StringIO(), stdin=io.StringIO(), clock=CLOCK)
                with self.assertRaises(BondError) as cm:
                    it.run(BOND + stmt)
                self.assertIn(msg, str(cm.exception))
                last = it.bonds["us"].journal.entries[-1]
                self.assertEqual(last["kind"], "refused")
                self.assertEqual(it.bonds["us"].vows["honesty"], "We tell each other the truth.")

    def test_copies_of_memory_can_be_changed(self):
        self.assertEqual(output(BOND + "let c = copy(memory(us)) push(c, 1) print(len(c), len(memory(us)))"), "3 2\n")


class Bits(unittest.TestCase):
    def test_bits_literals_keep_their_width(self):
        self.assertEqual(output("print(0b0101, type_of(0b0101), len(0b0101), num(0b0101), 0b1_0)"),
                         "0b0101 bits 4 5 0b10\n")
        self.assertEqual(output("print(0b01 == 0b1, 0b1 == bits(1), 0b101 == 0b101)"), "false true true\n")

    def test_bit_operators(self):
        src = "let a = 0b0101 let b = 0b0011 print(a & b, a | b, a ^ b, ~a, a << 1, a >> 2, a + b, 0b1 & 0b0110)"
        self.assertEqual(output(src), "0b0001 0b0111 0b0110 0b1010 0b1010 0b0001 0b01010011 0b0000\n")

    def test_bits_index_loop_and_truth(self):
        src = "let a = 0b101 let s = 0 for x in a { s = s + x } print(a[0], a[1], a[-1], s, not 0b000, not 0b010)"
        self.assertEqual(output(src), "1 0 1 2 true false\n")

    def test_making_bits(self):
        src = 'print(bits(11), bits(11, 8), bits(0), bits([1, 0, 1]), bits("0110"), bits(0b11, 4))'
        self.assertEqual(output(src), "0b1011 0b00001011 0b0 0b101 0b0110 0b0011\n")

    def test_numbers_still_have_bit_operators(self):
        self.assertEqual(output("print(6 & 3, 6 | 3, 6 ^ 3, ~0, 1 << 4, 16 >> 2, 1 | 2 == 3)"),
                         "2 7 5 -1 16 4 true\n")

    def test_bit_errors(self):
        with self.assertRaises(GbnSyntaxError):
            run("print(0b12)")
        bad = ["print(0b1 & 1)", "print(1 | 0b1)", "print(1.5 & 1)", 'print("a" | 1)',
               "print(1 << -1)", "print(bits(-1))", "print(bits(5, 2))", "print(bits([2]))",
               "let a = 0b1 a[0] = 0"]
        for src in bad:
            with self.subTest(src=src), self.assertRaises(GbnRuntimeError) as cm:
                run(src)
            self.assertEqual(cm.exception.line, 1)

    def test_consent_is_an_and_gate(self):
        src = BOND + '''
        script_human(["yes", "yes"])
        for q in ["together?", "rush?", "there?"] { let v = us(q) print(v.gate, v.bits) }
        '''
        self.assertEqual(output(src).splitlines(), [
            "1 ∧ 1 = 1 {Asha: 1, saathi: 1}",
            "1 ∧ 0 = 0 {Asha: 1, saathi: 0}",
            "? ∧ 0 = ? {Asha: none, saathi: 0}",
        ])

    def test_two_noes_are_a_mutual_rejection_not_an_approval(self):
        src = BOND + '''
        script_human(["no", "nahi"])
        for q in ["rush?", "argue?"] {
          let v = us(q)
          print(v.outcome, v.gate, v.approved, v.agreed, v.reason)
        }
        '''
        self.assertEqual(output(src).splitlines(), [
            "rejected 0 ∧ 0 = 0 false true rejected together",
            "rejected 0 ∧ 0 = 0 false true rejected together",
        ])

    def test_silence_is_its_own_state(self):
        src = BOND + '''
        script_human([none, "no"])
        let quiet = us("together?")
        let refused = us("together?")
        print(quiet.outcome, quiet.gate, quiet.signal)
        print(refused.outcome, refused.gate, refused.signal)
        '''
        self.assertEqual(output(src).splitlines(), [
            "silent ? ∧ 1 = ? none",
            "disagreed 0 ∧ 1 = 0 0b01",
        ])

    def test_yes_words_in_any_language_mean_the_same(self):
        src = BOND + '''
        script_human(["haan"])
        let v = us("together?")
        print(v.outcome, v.decision, v.gate)
        '''
        self.assertEqual(output(src), "approved haan 1 ∧ 1 = 1\n")

    def test_match_picks_the_most_specific_arm(self):
        src = BOND + '''
        script_human(["no", "no", "yes", none])
        for q in ["rush?", "rush?", "rush?", "rush?"] {
          match us(q) {
            approved d { print("approved", d) }
            rejected why { print("rejected:", why) }
            agreed d { print("agreed", d) }
            split why { print("split:", why) }
          }
        }
        '''
        self.assertEqual(output(src).splitlines(), [
            "rejected: rejected together",
            "rejected: rejected together",
            "split: the partners disagree",
            "split: no consent: Asha did not answer",
        ])

    def test_coalition_gate(self):
        src = '''
        member x(q) { return 1 } member y(q) { return 1 } member z(q) { return 2 }
        coalition k(q) { members: x, y, z }
        coalition t(q) { members: x, y, z  rule: threshold 0.9 }
        print(k(0).gate)
        print(t(0).gate)
        '''
        self.assertEqual(output(src), "MAJORITY(1, 1, 0) = 1\nTHRESHOLD 0.9(1, 1, 0) = 0\n")

    def test_seal_is_256_bits_and_changes_with_history(self):
        _, it = run(BOND + 'let a = us.seal remember us "x" let b = us.seal let s = bits(b)')
        g = it.globals.vars
        self.assertNotEqual(g["a"], g["b"])
        self.assertEqual(len(g["s"]), 256)
        self.assertEqual(g["s"].value, int(g["b"], 16))

    def test_signal(self):
        src = BOND + 'script_human(["yes", "yes"]) print(us("together?").signal, us("rush?").signal)'
        self.assertEqual(output(src), "0b11 0b10\n")


class Proposals(unittest.TestCase):
    def test_a_proposal_has_a_fingerprint_and_starts_pending(self):
        out, _ = run(BOND + '''
        let p = propose(us, "Build this together")
        print(p, p.version, len(p.fingerprint), p.rounds, type_of(p))
        ''')
        self.assertEqual(out, '<proposal 3 v1 pending: "Build this together"> 1 64 0 proposal\n')

    def test_silence_keeps_it_pending_and_disagreement_is_remembered(self):
        out, it = run(BOND + '''
        script_human([none, "no", "yes"])
        let p = propose(us, "Do this together")
        us(p) print(p.status)
        us(p) print(p.status)
        let v = us(p) print(p.status, p.rounds, v.proposal == p)
        ''')
        self.assertEqual(out, "pending\ndisagreed\napproved 3 true\n")
        decisions = it.bonds["us"].journal.find("decision")
        fp = it.bonds["us"].journal.find("proposal")[0]["fingerprint"]
        self.assertEqual([d["proposal"] for d in decisions], [fp, fp, fp])

    def test_a_decided_proposal_cannot_be_decided_again(self):
        for answer, status in (("yes", "approved"), ("no", "rejected")):
            src = PARTNER + '''
            bond us { human: "Asha" ai: saathi }
            script_human(["%s", "yes"])
            let p = propose(us, "Rush this")
            if "%s" == "yes" { p = propose(us, "Do this together") }
            us(p)
            us(p)
            ''' % (answer, answer)
            with self.assertRaises(BondError) as ctx:
                run(src)
            self.assertIn(f"it is already {status}", str(ctx.exception))

    def test_an_old_approval_never_covers_a_revised_proposal(self):
        # The AI said yes to version 1; that yes does not count for version 2.
        src = BOND + '''
        script_human(["no", "yes"])
        let p = propose(us, "Do this together")
        us(p)
        let p2 = revise(p, "Do this together, carefully")
        print(p.status, p2.status, p2.rounds, p2.version, p2.replaces, p2 == p)
        print(us(p2).outcome, p2.status, p2.rounds)
        '''
        self.assertEqual(output(src), "replaced pending 0 2 3 false\napproved approved 1\n")

    def test_a_decided_proposal_is_not_revised(self):
        for answer, status in (("yes", "approved"), ("no", "rejected")):
            src = PARTNER + '''
            bond us { human: "Asha" ai: saathi }
            script_human(["%s"])
            let p = propose(us, "Rush this")
            if "%s" == "yes" { p = propose(us, "Do this together") }
            us(p)
            revise(p, "Something else")
            ''' % (answer, answer)
            with self.assertRaises(GbnRuntimeError) as ctx:
                run(src)
            self.assertIn(f"already {status}", str(ctx.exception))

    def test_same_named_bonds_give_different_fingerprints(self):
        prints = []
        for clock in ("2026-11-01T10:00:00+00:00", "2026-11-01T10:00:01+00:00"):
            out = io.StringIO()
            it = Interpreter(out=out, stdin=io.StringIO(), clock=lambda c=clock: c)
            it.run(BOND + 'let p = propose(us, "Same words") print(us.id, p.fingerprint)')
            prints.append(out.getvalue().split())
        self.assertNotEqual(prints[0][0], prints[1][0])
        self.assertNotEqual(prints[0][1], prints[1][1])

    def test_a_second_writer_is_stopped_instead_of_forking_history(self):
        from gatbandhan.journal import Journal
        path = os.path.join(tempfile.mkdtemp(), "us.journal")
        first = Journal(path, clock=CLOCK)
        first.append("bond", text="formed")
        second = Journal(path, clock=CLOCK)       # opens the same memory
        second.append("memory", text="from the second program")
        with self.assertRaises(GbnRuntimeError):
            first.append("memory", text="from the first program")
        self.assertEqual(len(Journal(path, clock=CLOCK).entries), 2)

    def test_an_old_version_cannot_be_reused(self):
        src = BOND + '''
        script_human(["yes"])
        let p = propose(us, "Do this together")
        let p2 = revise(p, "Do this together, carefully")
        us(p)
        '''
        with self.assertRaises(BondError) as ctx:
            run(src)
        self.assertIn("already replaced", str(ctx.exception))
        with self.assertRaises(GbnRuntimeError):
            run(BOND + 'let p = propose(us, "a") revise(p, "b") revise(p, "c")')

    def test_proposals_wait_across_runs(self):
        d = tempfile.mkdtemp()
        kept = PARTNER + 'bond us { human: "Asha" ai: saathi keep: "us.journal" }\n'
        run(kept + 'script_human([none]) us(propose(us, "Do this together"))', base_dir=d)
        out, _ = run(kept + '''
        let waiting = []
        for p in proposals(us) { if p.status == "pending" { push(waiting, p) } }
        print(len(waiting), waiting[0].rounds)
        script_human(["yes"])
        print(us(waiting[0]).outcome, waiting[0].status)
        ''', base_dir=d)
        self.assertEqual(out, "1 1\napproved approved\n")


class KeptBonds(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "us.journal")

    def kept(self, vows='vow honesty: "We tell each other the truth."', human="Asha", extra=""):
        return PARTNER + f'''
        bond us {{
          human: "{human}"
          ai: saathi
          keep: "us.journal"
          {vows}
        }}
        ''' + extra

    def test_journal_persists_across_runs(self):
        run(self.kept(extra='remember us "first run"'), base_dir=self.dir)
        out, _ = run(self.kept(extra='remember us "second run" print(len(memory(us)))'), base_dir=self.dir)
        self.assertEqual(out, "4\n")  # bond, vow, first run, second run
        with open(self.path) as f:
            kinds = [json.loads(line)["kind"] for line in f]
        self.assertEqual(kinds, ["bond", "vow", "memory", "memory"])

    def test_vows_survive_and_cannot_be_changed_later(self):
        run(self.kept(), base_dir=self.dir)
        out, _ = run(self.kept(vows="", extra="print(us.vows.honesty)"), base_dir=self.dir)
        self.assertEqual(out, "We tell each other the truth.\n")
        with self.assertRaises(BondError):
            run(self.kept(vows='vow honesty: "Sometimes."'), base_dir=self.dir)
        with open(self.path) as f:
            self.assertEqual(json.loads(f.readlines()[-1])["kind"], "refused")

    def test_journal_cannot_be_given_to_someone_else(self):
        run(self.kept(), base_dir=self.dir)
        with self.assertRaises(BondError):
            run(self.kept(human="Someone"), base_dir=self.dir)

    def test_hand_edited_journal_is_refused(self):
        run(self.kept(extra='remember us "true story"'), base_dir=self.dir)
        with open(self.path) as f:
            lines = f.readlines()
        lines[2] = lines[2].replace("true story", "rewritten story")
        with open(self.path, "w") as f:
            f.writelines(lines)
        with self.assertRaises(GbnRuntimeError) as cm:
            run(self.kept(), base_dir=self.dir)
        self.assertIn("changed by hand at entry 3", str(cm.exception))

    def test_deleted_entry_is_refused(self):
        run(self.kept(extra='remember us "a" remember us "b"'), base_dir=self.dir)
        with open(self.path) as f:
            lines = f.readlines()
        del lines[2]
        with open(self.path, "w") as f:
            f.writelines(lines)
        with self.assertRaises(GbnRuntimeError):
            run(self.kept(), base_dir=self.dir)


class Parity(unittest.TestCase):
    """tests/parity.json is shared with the JavaScript tests (playground/test.js):
    both interpreters must print exactly the output stored there."""

    def test_python_matches_the_shared_cases(self):
        path = os.path.join(os.path.dirname(__file__), "parity.json")
        with open(path, encoding="utf-8") as f:
            cases = json.load(f)
        self.assertGreater(len(cases), 50)
        for case in cases:
            with self.subTest(source=case["source"][:60]):
                out = io.StringIO()
                it = Interpreter(out=out, stdin=io.StringIO(), clock=lambda: "T")
                try:
                    it.run(case["source"])
                except GatbandhanError as e:
                    out.write(f"{type(e).__name__}: {e}\n")
                self.assertEqual(out.getvalue(), case["output"])

    def test_playground_page_is_up_to_date(self):
        here = os.path.join(os.path.dirname(__file__), "..", "playground")
        sys.path.insert(0, here)
        try:
            import build
        finally:
            sys.path.remove(here)
        with open(os.path.join(here, "index.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), build.build(), "run: python playground/build.py")


class Examples(unittest.TestCase):
    def test_examples_run(self):
        here = os.path.dirname(__file__)
        roots = [os.path.join(here, "..", "examples"), os.path.join(here, "..", "playground", "examples")]
        files = [os.path.join(r, n) for r in roots for n in sorted(os.listdir(r)) if n.endswith(".gbn")]
        for path in files:
            name = os.path.basename(path)
            with self.subTest(example=name), open(path, encoding="utf-8") as f:
                src = f.read()
                it = Interpreter(out=io.StringIO(), stdin=io.StringIO(), base_dir=tempfile.mkdtemp())
                if name.startswith("refused_"):
                    with self.assertRaises(BondError):
                        it.run(src)
                else:
                    it.run(src)


if __name__ == "__main__":
    unittest.main()
