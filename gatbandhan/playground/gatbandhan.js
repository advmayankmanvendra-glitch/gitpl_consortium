/*
 * Gatbandhan in JavaScript: a port of the Python reference interpreter
 * (gatbandhan/src/gatbandhan) that runs in a browser or in Node 18+.
 *
 *   const it = new Gatbandhan.Interpreter({ print: line => console.log(line) });
 *   await it.run(source);
 *
 * The interpreter is asynchronous so that a human partner can answer through
 * a web page. The language follows docs/SPEC.md. Differences from Python:
 * a model can only be a scripted one (script(...)), and a bond's `keep:`
 * memory is saved in the browser's localStorage instead of a file.
 */
(function (root) {
  "use strict";

  const VERSION = "0.1.0";

  // ------------------------------------------------------------------ errors

  class GatbandhanError extends Error {
    constructor(message, line) {
      super(line ? `line ${line}: ${message}` : message);
      this.msg = message;
      this.line = line || null;
    }
    withLine(line) {
      if (this.line == null && line != null) {
        this.line = line;
        this.message = `line ${line}: ${this.msg}`;
      }
      return this;
    }
  }
  class GbnSyntaxError extends GatbandhanError {}
  class GbnRuntimeError extends GatbandhanError {}
  /** An attempt to overwrite something a bond protects. It is never caught. */
  class BondError extends GbnRuntimeError {}

  // ------------------------------------------------------------------- lexer

  const KEYWORDS = new Set([
    "let", "fn", "member", "coalition", "bond", "vow", "remember", "amend",
    "with", "by", "return", "abstain", "if", "else", "while", "for", "in",
    "break", "continue", "match", "true", "false", "none", "and", "or", "not",
  ]);
  const TWO_CHAR = new Set(["==", "!=", "<=", ">=", "=>", "<<", ">>"]);
  const ONE_CHAR = new Set("+-*/%<>=()[]{},.:;&|^~".split(""));
  const ESCAPES = { n: "\n", t: "\t", '"': '"', "\\": "\\", "{": "\x00", "}": "\x01" };

  const isDigit = c => c >= "0" && c <= "9";
  const isAlpha = c => /[A-Za-z_À-￿]/.test(c);
  const isAlnum = c => isDigit(c) || isAlpha(c);

  function tokenize(src, line = 1) {
    const toks = [];
    let i = 0;
    const n = src.length;
    const tok = (kind, value, l) => toks.push({ kind, value, line: l });
    while (i < n) {
      const ch = src[i];
      if (ch === "\n") { line++; i++; }
      else if (ch === " " || ch === "\t" || ch === "\r") { i++; }
      else if (ch === "#") { while (i < n && src[i] !== "\n") i++; }
      else if (ch === "0" && (src[i + 1] === "b" || src[i + 1] === "B")) {
        let j = i + 2;
        while (j < n && "01_".includes(src[j])) j++;
        const digits = src.slice(i + 2, j).replace(/_/g, "");
        if (!digits || (j < n && isAlnum(src[j]))) {
          throw new GbnSyntaxError("a binary number is 0b followed by 0s and 1s", line);
        }
        tok("BITS", new Bits(BigInt("0b" + digits), digits.length), line);
        i = j;
      } else if (isDigit(ch)) {
        let j = i;
        while (j < n && (isDigit(src[j]) || src[j] === "_")) j++;
        if (src[j] === "." && isDigit(src[j + 1] || "")) {
          j++;
          while (j < n && isDigit(src[j])) j++;
        }
        tok("NUMBER", Number(src.slice(i, j).replace(/_/g, "")), line);
        i = j;
      } else if (isAlpha(ch)) {
        let j = i;
        while (j < n && isAlnum(src[j])) j++;
        const word = src.slice(i, j);
        tok(KEYWORDS.has(word) ? "KEYWORD" : "IDENT", word, line);
        i = j;
      } else if (ch === '"') {
        const start = line;
        let j = i + 1;
        let buf = "";
        for (;;) {
          if (j >= n) throw new GbnSyntaxError("unterminated string", start);
          const c = src[j];
          if (c === '"') break;
          if (c === "\\") {
            const e = src[j + 1];
            if (e === undefined || !(e in ESCAPES)) {
              throw new GbnSyntaxError(`unknown escape '\\${e || ""}'`, line);
            }
            buf += ESCAPES[e];
            j += 2;
            continue;
          }
          if (c === "\n") line++;
          buf += c;
          j++;
        }
        tok("STRING", buf, start);
        i = j + 1;
      } else if (TWO_CHAR.has(src.slice(i, i + 2))) {
        tok("OP", src.slice(i, i + 2), line);
        i += 2;
      } else if (ONE_CHAR.has(ch)) {
        tok("OP", ch, line);
        i++;
      } else {
        throw new GbnSyntaxError(`unexpected character '${ch}'`, line);
      }
    }
    tok("EOF", null, line);
    return toks;
  }

  // ------------------------------------------------------------------ parser

  const RULES = new Set(["majority", "plurality", "unanimous", "quorum", "threshold"]);
  const RULES_WITH_ARG = new Set(["quorum", "threshold"]);
  const COALITION_FIELDS = ["key", "learn", "members", "min_votes", "rule", "tie", "veto", "weights"];
  const BOND_FIELDS = new Set(["human", "ai", "keep", "key"]);
  const COMPARE = new Set(["==", "!=", "<", "<=", ">", ">="]);

  function parse(src) {
    return new Parser(tokenize(src)).program();
  }

  class Parser {
    constructor(toks) { this.toks = toks; this.pos = 0; }
    get tok() { return this.toks[this.pos]; }
    peek(k = 1) { return this.toks[Math.min(this.pos + k, this.toks.length - 1)]; }
    advance() { return this.toks[this.pos++]; }
    isOp(t, ...ops) { return t.kind === "OP" && ops.includes(t.value); }
    isKw(t, ...kws) { return t.kind === "KEYWORD" && kws.includes(t.value); }
    isIdent(t, name) { return t.kind === "IDENT" && (name === undefined || t.value === name); }

    error(msg, t) {
      t = t || this.tok;
      const found = t.kind === "EOF" ? "end of file" : `'${t.value instanceof Bits ? show(t.value) : t.value}'`;
      throw new GbnSyntaxError(`${msg} (found ${found})`, t.line);
    }
    expectOp(op) { if (!this.isOp(this.tok, op)) this.error(`expected '${op}'`); return this.advance(); }
    expectKw(kw) { if (!this.isKw(this.tok, kw)) this.error(`expected '${kw}'`); return this.advance(); }
    expectIdent(what = "a name") { if (this.tok.kind !== "IDENT") this.error(`expected ${what}`); return this.advance().value; }
    acceptOp(op) { if (this.isOp(this.tok, op)) { this.advance(); return true; } return false; }

    program() {
      const out = [];
      while (this.tok.kind !== "EOF") { const s = this.statement(); if (s) out.push(s); }
      return out;
    }
    block() {
      this.expectOp("{");
      const out = [];
      while (!this.isOp(this.tok, "}")) {
        if (this.tok.kind === "EOF") this.error("expected '}' to close the block");
        const s = this.statement();
        if (s) out.push(s);
      }
      this.advance();
      return out;
    }
    params() {
      this.expectOp("(");
      const names = [];
      if (!this.isOp(this.tok, ")")) {
        for (;;) { names.push(this.expectIdent("a parameter name")); if (!this.acceptOp(",")) break; }
      }
      this.expectOp(")");
      if (new Set(names).size !== names.length) this.error("duplicate parameter name");
      return names;
    }
    feeling() {
      if (!this.isKw(this.tok, "with")) return null;
      this.advance();
      if (!this.isIdent(this.tok, "feeling")) this.error("expected 'feeling' after 'with'");
      this.advance();
      return this.expression();
    }

    statement() {
      const t = this.tok;
      const line = t.line;
      if (this.isOp(t, ";")) { this.advance(); return null; }
      if (this.isKw(t, "let")) {
        this.advance();
        const name = this.expectIdent();
        this.expectOp("=");
        return { type: "Let", line, name, value: this.expression() };
      }
      if (this.isKw(t, "fn") && this.peek().kind === "IDENT") {
        this.advance();
        const name = this.advance().value;
        return { type: "FnDecl", line, name, params: this.params(), body: this.block() };
      }
      if (this.isKw(t, "member")) {
        this.advance();
        const name = this.expectIdent("a member name");
        const params = this.params();
        let trust = null;
        if (this.isIdent(this.tok, "trust")) { this.advance(); trust = this.expression(); }
        return { type: "MemberDecl", line, name, params, trust, body: this.block() };
      }
      if (this.isKw(t, "coalition")) return this.coalition();
      if (this.isKw(t, "bond")) return this.bond();
      if (this.isKw(t, "vow")) {
        this.advance();
        const bond = this.expectIdent("a bond name");
        this.expectOp(".");
        const vname = this.expectIdent("a vow name");
        this.expectOp("=");
        return { type: "VowStmt", line, bond, vow: { line, name: vname, value: this.expression() } };
      }
      if (this.isKw(t, "remember", "amend")) {
        this.advance();
        const bond = this.expectIdent("a bond name");
        const amends = t.value === "amend" ? this.expression() : null;
        const text = this.expression();
        let by = null;
        if (this.isKw(this.tok, "by")) {
          this.advance();
          by = this.expectIdent("'human' or 'ai'");
          if (by !== "human" && by !== "ai") this.error("expected 'human' or 'ai' after 'by'", this.toks[this.pos - 1]);
        }
        return { type: "Remember", line, bond, text, by, feeling: this.feeling(), amends };
      }
      if (this.isKw(t, "return")) {
        this.advance();
        let value = null;
        if (!(this.isOp(this.tok, "}") || this.tok.kind === "EOF" || this.isKw(this.tok, "with"))) value = this.expression();
        return { type: "Return", line, value, feeling: this.feeling() };
      }
      if (this.isKw(t, "abstain")) {
        this.advance();
        return { type: "Abstain", line, reason: this.tok.kind === "STRING" ? this.expression() : null };
      }
      if (this.isKw(t, "if")) return this.ifStmt();
      if (this.isKw(t, "while")) {
        this.advance();
        return { type: "While", line, cond: this.expression(), body: this.block() };
      }
      if (this.isKw(t, "for")) {
        this.advance();
        const v = this.expectIdent("a loop variable");
        this.expectKw("in");
        return { type: "For", line, var: v, iterable: this.expression(), body: this.block() };
      }
      if (this.isKw(t, "break")) { this.advance(); return { type: "Break", line }; }
      if (this.isKw(t, "continue")) { this.advance(); return { type: "Continue", line }; }
      if (this.isKw(t, "match")) return this.matchStmt();
      const expr = this.expression();
      if (this.isOp(this.tok, "=")) {
        if (!["Name", "Index", "Field"].includes(expr.type)) this.error("can only assign to a name, an index or a field");
        this.advance();
        return { type: "Assign", line, target: expr, value: this.expression() };
      }
      return { type: "ExprStmt", line, expr };
    }

    ifStmt() {
      const line = this.expectKw("if").line;
      const cond = this.expression();
      const then = this.block();
      let otherwise = null;
      if (this.isKw(this.tok, "else")) {
        this.advance();
        otherwise = this.isKw(this.tok, "if") ? [this.ifStmt()] : this.block();
      }
      return { type: "If", line, cond, then, otherwise };
    }

    matchStmt() {
      const line = this.expectKw("match").line;
      const subject = this.expression();
      this.expectOp("{");
      const arms = {};
      while (!this.isOp(this.tok, "}")) {
        const t = this.tok;
        if (t.kind !== "IDENT" || !MATCH_ARMS.includes(t.value)) this.error("expected an arm: approved, rejected, disagreed, silent, agreed or split");
        if (arms[t.value]) this.error(`duplicate '${t.value}' arm`);
        this.advance();
        const name = this.tok.kind === "IDENT" ? this.advance().value : null;
        arms[t.value] = { name, body: this.block() };
      }
      this.advance();
      if (!Object.keys(arms).length) this.error("a match needs at least one arm");
      return { type: "Match", line, subject, arms };
    }

    bond() {
      const line = this.expectKw("bond").line;
      const name = this.expectIdent("a bond name");
      this.expectOp("{");
      const fields = {};
      const vows = [];
      while (!this.isOp(this.tok, "}")) {
        const f = this.tok;
        if (this.isKw(f, "vow")) {
          this.advance();
          const vname = this.expectIdent("a vow name");
          this.expectOp(":");
          if (vows.some(v => v.name === vname)) this.error(`vow '${vname}' made twice`, f);
          vows.push({ line: f.line, name: vname, value: this.expression() });
        } else if (f.kind === "IDENT" && BOND_FIELDS.has(f.value)) {
          if (f.value in fields) this.error(`field '${f.value}' given twice`);
          this.advance();
          this.expectOp(":");
          fields[f.value] = this.expression();
        } else {
          this.error("expected a bond field (human, ai, keep, key) or a vow");
        }
        this.acceptOp(",") || this.acceptOp(";");
      }
      this.advance();
      for (const need of ["human", "ai"]) {
        if (!fields[need]) throw new GbnSyntaxError(`bond '${name}' needs a '${need}' partner`, line);
      }
      return { type: "BondDecl", line, name, human: fields.human, ai: fields.ai,
               keep: fields.keep || null, key: fields.key || null, vows };
    }

    coalition() {
      const line = this.expectKw("coalition").line;
      const name = this.expectIdent("a coalition name");
      const params = this.params();
      this.expectOp("{");
      const fields = {};
      while (!this.isOp(this.tok, "}")) {
        const f = this.tok;
        if (f.kind !== "IDENT" || !COALITION_FIELDS.includes(f.value)) {
          this.error(`expected a coalition field (${COALITION_FIELDS.join(", ")})`);
        }
        if (f.value in fields) this.error(`field '${f.value}' given twice`);
        this.advance();
        this.expectOp(":");
        if (f.value === "members" || f.value === "veto") {
          const items = [this.expression()];
          while (this.acceptOp(",")) items.push(this.expression());
          fields[f.value] = items;
        } else if (f.value === "rule") {
          const r = this.tok;
          if (r.kind !== "IDENT" || !RULES.has(r.value)) this.error(`expected a rule (${[...RULES].sort().join(", ")})`);
          this.advance();
          fields.rule = { kind: r.value, arg: RULES_WITH_ARG.has(r.value) ? this.expression() : null, line: r.line };
        } else {
          fields[f.value] = this.expression();
        }
        this.acceptOp(",") || this.acceptOp(";");
      }
      this.advance();
      if (!fields.members) throw new GbnSyntaxError(`coalition '${name}' has no members`, line);
      return { type: "CoalitionDecl", line, name, params, members: fields.members,
               rule: fields.rule || { kind: "majority", arg: null, line },
               veto: fields.veto || [], tie: fields.tie || null, key: fields.key || null,
               learn: fields.learn || null, weights: fields.weights || null,
               min_votes: fields.min_votes || null };
    }

    // expressions
    expression() { return this.orExpr(); }
    binLevel(ops, next, kw = false) {
      let left = next();
      while (kw ? this.isKw(this.tok, ...ops) : this.isOp(this.tok, ...ops)) {
        const t = this.advance();
        left = { type: "Binary", line: t.line, op: t.value, left, right: next() };
      }
      return left;
    }
    orExpr() { return this.binLevel(["or"], () => this.andExpr(), true); }
    andExpr() { return this.binLevel(["and"], () => this.notExpr(), true); }
    notExpr() {
      if (this.isKw(this.tok, "not")) {
        const line = this.advance().line;
        return { type: "Unary", line, op: "not", operand: this.notExpr() };
      }
      return this.comparison();
    }
    comparison() {
      let left = this.bitOr();
      while ((this.tok.kind === "OP" && COMPARE.has(this.tok.value)) || this.isKw(this.tok, "in")) {
        const t = this.advance();
        left = { type: "Binary", line: t.line, op: t.value, left, right: this.bitOr() };
      }
      return left;
    }
    bitOr() { return this.binLevel(["|"], () => this.bitXor()); }
    bitXor() { return this.binLevel(["^"], () => this.bitAnd()); }
    bitAnd() { return this.binLevel(["&"], () => this.shift()); }
    shift() { return this.binLevel(["<<", ">>"], () => this.additive()); }
    additive() { return this.binLevel(["+", "-"], () => this.term()); }
    term() { return this.binLevel(["*", "/", "%"], () => this.unary()); }
    unary() {
      if (this.isOp(this.tok, "-", "~")) {
        const t = this.advance();
        return { type: "Unary", line: t.line, op: t.value, operand: this.unary() };
      }
      return this.postfix();
    }
    postfix() {
      let expr = this.primary();
      for (;;) {
        const t = this.tok;
        if (this.isOp(t, "(")) {
          this.advance();
          const args = [];
          if (!this.isOp(this.tok, ")")) {
            for (;;) { args.push(this.expression()); if (!this.acceptOp(",")) break; }
          }
          this.expectOp(")");
          expr = { type: "Call", line: t.line, callee: expr, args };
        } else if (this.isOp(t, "[")) {
          this.advance();
          const index = this.expression();
          this.expectOp("]");
          expr = { type: "Index", line: t.line, target: expr, index };
        } else if (this.isOp(t, ".")) {
          this.advance();
          if (this.tok.kind !== "IDENT" && this.tok.kind !== "KEYWORD") this.error("expected a field name after '.'");
          expr = { type: "Field", line: t.line, target: expr, name: this.advance().value };
        } else {
          return expr;
        }
      }
    }
    primary() {
      const t = this.tok;
      if (t.kind === "NUMBER" || t.kind === "BITS") { this.advance(); return { type: "Literal", line: t.line, value: t.value }; }
      if (t.kind === "STRING") { this.advance(); return this.template(t.value, t.line); }
      if (this.isKw(t, "true", "false", "none")) {
        this.advance();
        return { type: "Literal", line: t.line, value: { true: true, false: false, none: null }[t.value] };
      }
      if (t.kind === "IDENT") { this.advance(); return { type: "Name", line: t.line, name: t.value }; }
      if (this.isOp(t, "(")) { this.advance(); const e = this.expression(); this.expectOp(")"); return e; }
      if (this.isOp(t, "[")) {
        this.advance();
        const items = [];
        while (!this.isOp(this.tok, "]")) { items.push(this.expression()); if (!this.acceptOp(",")) break; }
        this.expectOp("]");
        return { type: "ListLit", line: t.line, items };
      }
      if (this.isOp(t, "{")) {
        this.advance();
        const entries = [];
        while (!this.isOp(this.tok, "}")) {
          const k = this.tok;
          if (["IDENT", "KEYWORD", "STRING"].includes(k.kind)) this.advance();
          else this.error("expected a map key");
          this.expectOp(":");
          entries.push([k.value, this.expression()]);
          if (!this.acceptOp(",")) break;
        }
        this.expectOp("}");
        return { type: "MapLit", line: t.line, entries };
      }
      if (this.isKw(t, "fn")) {
        this.advance();
        return { type: "FnLit", line: t.line, params: this.params(), body: this.block() };
      }
      this.error("expected an expression");
    }
    template(raw, line) {
      const parts = [];
      let buf = "";
      let i = 0;
      while (i < raw.length) {
        const c = raw[i];
        if (c === "{") {
          let depth = 1;
          let j = i + 1;
          while (j < raw.length && depth) {
            if (raw[j] === "{") depth++;
            else if (raw[j] === "}") depth--;
            j++;
          }
          if (depth) throw new GbnSyntaxError("unclosed '{' in string (write \\{ for a literal brace)", line);
          const inner = raw.slice(i + 1, j - 1);
          if (!inner.trim()) throw new GbnSyntaxError("empty {} in string", line);
          if (buf) { parts.push(unescape(buf)); buf = ""; }
          const sub = new Parser(tokenize(inner, line));
          const e = sub.expression();
          if (sub.tok.kind !== "EOF") sub.error("unexpected text inside {...}");
          parts.push(e);
          i = j;
        } else if (c === "}") {
          throw new GbnSyntaxError("unmatched '}' in string (write \\} for a literal brace)", line);
        } else {
          buf += c;
          i++;
        }
      }
      if (buf) parts.push(unescape(buf));
      if (parts.every(p => typeof p === "string")) return { type: "Literal", line, value: parts.join("") };
      return { type: "Template", line, parts };
    }
  }
  const unescape = s => s.replace(/\x00/g, "{").replace(/\x01/g, "}");

  // ------------------------------------------------------------------ values

  class Bits {
    constructor(value, width) {
      value = BigInt(value);
      if (width < 1) throw new GbnRuntimeError("bits need a width of at least 1");
      if (value < 0n || value >= (1n << BigInt(width))) throw new GbnRuntimeError(`${value} does not fit in ${width} bits`);
      this.value = value;
      this.width = width;
    }
    get mask() { return (1n << BigInt(this.width)) - 1n; }
    digits() { return this.value.toString(2).padStart(this.width, "0"); }
    bit(i) { return Number(this.digits()[i]); }
    list() { return this.digits().split("").map(Number); }
  }

  class Fn { constructor(name, params, body, closure) { Object.assign(this, { name, params, body, closure }); } }
  class Builtin { constructor(name, fn) { this.name = name; this.fn = fn; } }
  class Member { constructor(name, params, body, closure, trust) { Object.assign(this, { name, params, body, closure, trust }); } }
  class Coalition {
    constructor(name, decl, closure) { Object.assign(this, { name, decl, closure }); this.learned = new Map(); this.history = []; }
  }

  const VERDICT_FIELDS = ["agreed", "decision", "reason", "votes", "abstained", "dissent", "tally", "margin",
    "tiebreak", "coalition", "feelings", "question", "bits", "signal", "gate", "rule", "outcome", "approved", "proposal", "objections"];
  const MATCH_ARMS = ["approved", "rejected", "disagreed", "silent", "agreed", "split"];
  const YES_WORDS = new Set(["yes", "y", "yeah", "yep", "haan", "haa", "ha", "ji", "ok", "okay", "sure",
    "agree", "agreed", "approve", "approved", "true"]);
  const NO_WORDS = new Set(["no", "n", "nope", "nahi", "nahin", "na", "disagree", "reject", "rejected", "never", "false"]);

  // 1 for a yes, 0 for a no, null for silence or an open answer (like "tea").
  // The answer in a reply map; a no that gives a "reason" becomes an Objection.
  function objectionFrom(reply) {
    const answer = reply.get("answer") ?? null, reason = reply.get("reason");
    if (typeof reason === "string" && reason.trim() && yesNo(answer) === 0) return new Objection(reason.trim(), reply.get("condition") ?? null);
    return answer;
  }
  function yesNo(answer) {
    if (answer instanceof Objection) return 0;
    if (typeof answer === "boolean") return answer ? 1 : 0;
    if (typeof answer === "string") {
      const word = answer.trim().toLowerCase().replace(/[.!]+$/, "");
      if (YES_WORDS.has(word)) return 1;
      if (NO_WORDS.has(word)) return 0;
    }
    return null;
  }

  class Verdict {
    constructor(o) {
      Object.assign(this, { tiebreak: false, feelings: new Map(), question: null, rule: "", partners: null, outcome: "", marks: null, proposal: null, objections: new Map() }, o);
    }
    // True only for a real yes: a bond's approval, or a coalition's agreement.
    get approved() { return this.partners ? this.outcome === "approved" : this.agreed; }
    get(name) {
      if (name === "outcome") return this.outcome || (this.agreed ? "agreed" : "split");
      if (name === "approved") return this.approved;
      if (name === "bits") return this.bitsMap();
      if (name === "gate") return this.gate();
      if (name === "signal") {
        const row = [...this.bitsMap().values()];
        return row.length && !row.includes(null) ? new Bits(BigInt("0b" + row.join("")), row.length) : null;
      }
      return this[name];
    }
    bitsMap() {
      // A bond lists both partners: 1 for yes, 0 for no, none for silence.
      if (this.partners) return new Map(this.marks);
      let lead;
      if (this.agreed) lead = new Set([...this.votes.keys()].filter(m => !this.dissent.includes(m)));
      else lead = new Set(this.tally.length ? this.tally[0].get("members") : []);
      const names = this.partners ? this.partners : [...this.votes.keys()];
      return new Map(names.map(n => [n, lead.has(n) ? 1 : 0]));
    }
    gate() {
      const b = [...this.bitsMap().values()];
      const out = this.agreed ? 1 : 0;
      if (this.partners) {
        const mark = x => x === null ? "?" : String(x);
        const res = this.outcome === "silent" ? "?" : this.outcome === "approved" ? 1 : 0;
        return `${mark(b[0])} ∧ ${mark(b[1])} = ${res}`;
      }
      return `${this.rule.toUpperCase()}(${b.join(", ")}) = ${out}`;
    }
  }

  const BOND_FIELDS_READ = ["name", "id", "human", "ai", "vows", "memory", "seal"];

  // A proposal the bond decides on. Its fingerprint never changes; a revision is a new
  // proposal. Its status is read from the bond's memory, so it survives between runs.
  // A "no" that says why, and optionally what would change it.
  class Objection { constructor(reason, condition = null) { this.reason = reason; this.condition = condition; } get(n) { return this[n]; } }
  const OBJECTION_FIELDS = ["reason", "condition"];
  const DEADLOCK_ROUNDS = 3; // disagreed rounds after which an open proposal is flagged for review

  const PROPOSAL_FIELDS = ["id", "version", "text", "fingerprint", "replaces", "status", "rounds", "bond",
    "standing", "needs", "objections", "uses", "blocked_by", "ready"];
  class Proposal {
    constructor(bond, entry) {
      this.bond = bond; this.id = entry.n; this.version = entry.version; this.text = entry.text;
      this.fingerprint = entry.fingerprint; this.replaces = entry.replaces === undefined ? null : entry.replaces;
      this.standing = !!entry.standing; this.needs = [...(entry.needs || [])];
    }
    entries(kind) { return this.bond.journal.entries.filter(e => e.kind === kind && e.proposal === this.fingerprint); }
    rounds() { return this.entries("decision"); }
    entryOf(n) { return this.bond.journal.entries.find(e => e.n === n); }
    status() {
      if (this.entries("revoke").length) return "revoked";
      const outcomes = this.rounds().map(e => e.outcome);
      for (const final of ["approved", "rejected"]) if (outcomes.includes(final)) return final;
      if (this.bond.journal.entries.some(e => e.kind === "proposal" && e.replaces === this.id)) return "replaced";
      if (outcomes.length && outcomes[outcomes.length - 1] === "disagreed") {
        return outcomes.filter(o => o === "disagreed").length >= DEADLOCK_ROUNDS ? "deadlocked" : "disagreed";
      }
      return "pending";
    }
    objections() {
      const out = [];
      this.rounds().forEach((e, i) => {
        for (const [who, o] of Object.entries(e.objections || {})) {
          out.push(new Map([["round", i + 1], ["by", who], ["reason", o.reason ?? null], ["condition", o.condition ?? null]]));
        }
      });
      return out;
    }
    blockedBy() { return this.needs.filter(n => new Proposal(this.bond, this.entryOf(n)).status() !== "approved"); }
    ready() { return this.status() === "approved" && !this.blockedBy().length && (this.standing || !this.entries("act").length); }
    get(name) {
      if (name === "status") return this.status();
      if (name === "rounds") return this.rounds().length;
      if (name === "bond") return this.bond.name;
      if (name === "objections") return this.objections();
      if (name === "uses") return this.entries("act").length;
      if (name === "blocked_by") return this.blockedBy();
      if (name === "ready") return this.ready();
      return this[name];
    }
  }

  class Bond {
    constructor(o) { Object.assign(this, o); this.vows = new Map(); this.vowLines = new Map(); }
    get(name) {
      if (name === "name") return this.name;
      if (name === "human") return this.humanName;
      if (name === "ai") return this.aiName;
      if (name === "vows") return seal(this.vows, this.name);
      if (name === "memory") return seal(this.journal.publicEntries(), this.name);
      if (name === "seal") return this.journal.head;
      if (name === "id") {
        // The fingerprint of the entry that formed the bond: it never changes and
        // differs between bonds, even bonds with the same name.
        const formed = this.journal.find("bond");
        return formed.length ? formed[0].hash : null;
      }
      return null;
    }
  }

  // Sealed containers: their owner bond is kept here, and every change is refused.
  const sealedOwner = new WeakMap();

  function seal(v, owner) {
    let out;
    if (Array.isArray(v)) out = v.map(x => seal(x, owner));
    else if (v instanceof Map) out = new Map([...v].map(([k, x]) => [k, seal(x, owner)]));
    else return v;
    sealedOwner.set(out, owner === undefined ? null : owner);
    return out;
  }
  function unseal(v) {
    if (Array.isArray(v)) return v.map(unseal);
    if (v instanceof Map) return new Map([...v].map(([k, x]) => [k, unseal(x)]));
    return v;
  }
  const isSealed = v => (Array.isArray(v) || v instanceof Map) && sealedOwner.has(v);

  const isNum = v => typeof v === "number";
  const isInt = v => typeof v === "number" && Number.isInteger(v);

  function typeName(v) {
    if (v === null || v === undefined) return "none";
    if (typeof v === "boolean") return "bool";
    if (typeof v === "number") return "num";
    if (typeof v === "string") return "str";
    if (Array.isArray(v)) return "list";
    if (v instanceof Map) return "map";
    if (v instanceof Bits) return "bits";
    if (v instanceof Member) return "member";
    if (v instanceof Coalition) return "coalition";
    if (v instanceof Bond) return "bond";
    if (v instanceof Verdict) return "verdict";
    if (v instanceof Proposal) return "proposal";
    if (v instanceof Objection) return "objection";
    if (v instanceof Fn || v instanceof Builtin) return "fn";
    return typeof v;
  }

  function showNum(v) {
    if (Number.isInteger(v)) return String(v);
    if (!Number.isFinite(v)) return String(v);
    return String(Math.round(v * 1e10) / 1e10);
  }
  const ident = /^[A-Za-z_][A-Za-z0-9_]*$/;

  function show(v, quote = false) {
    if (v === null || v === undefined) return "none";
    if (v === true) return "true";
    if (v === false) return "false";
    if (typeof v === "number") return showNum(v);
    if (typeof v === "string") return quote ? '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"' : v;
    if (v instanceof Bits) return "0b" + v.digits();
    if (Array.isArray(v)) return "[" + v.map(x => show(x, true)).join(", ") + "]";
    if (v instanceof Map) {
      return "{" + [...v].map(([k, x]) => `${typeof k === "string" && ident.test(k) ? k : show(k, true)}: ${show(x, true)}`).join(", ") + "}";
    }
    if (v instanceof Proposal) return `<proposal ${v.id} v${v.version}${v.standing ? " standing" : ""} ${v.status()}: ${show(v.text, true)}>`;
    if (v instanceof Objection) return `<objection ${show(v.reason, true)}${v.condition !== null ? " until " + show(v.condition, true) : ""}>`;
    if (v instanceof Verdict) {
      if (v.outcome === "approved" || v.outcome === "rejected") return `<verdict ${v.coalition}: ${v.outcome} ${show(v.decision, true)} (${v.reason})>`;
      if (v.outcome) return `<verdict ${v.coalition}: ${v.outcome} (${v.reason})>`;
      if (v.agreed) return `<verdict ${v.coalition}: agreed ${show(v.decision, true)} (${v.reason}, margin ${showNum(Math.round(v.margin * 100) / 100)})>`;
      return `<verdict ${v.coalition}: split (${v.reason})>`;
    }
    if (v instanceof Member) return `<member ${v.name}>`;
    if (v instanceof Coalition) return `<coalition ${v.name}>`;
    if (v instanceof Bond) return `<bond ${v.name}: ${v.humanName} and ${v.aiName}>`;
    if (v instanceof Fn || v instanceof Builtin) return `<fn ${v.name}>`;
    return String(v);
  }

  /** A string standing for a value, so that equal answers land in one bucket. */
  function freeze(v) {
    if (v === null || v === undefined) return "n";
    if (typeof v === "boolean") return "b" + v;
    if (typeof v === "number") return "#" + v;
    if (typeof v === "string") return "s" + JSON.stringify(v);
    if (v instanceof Bits) return `0b${v.width}:${v.value}`;
    if (Array.isArray(v)) return "[" + v.map(freeze).join(",") + "]";
    if (v instanceof Map) {
      return "{" + [...v].map(([k, x]) => [String(k), freeze(x)]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
        .map(([k, x]) => JSON.stringify(k) + ":" + x).join(",") + "}";
    }
    if (v instanceof Proposal) return "p" + v.fingerprint;
    if (v instanceof Objection) return "o" + JSON.stringify(v.reason) + freeze(v.condition);
    if (!freeze.ids.has(v)) freeze.ids.set(v, freeze.ids.size + 1);
    return "@" + freeze.ids.get(v);
  }
  freeze.ids = new Map();

  // --------------------------------------------------------------- coalition

  const EPS = 1e-9;

  function decide(name, ballots, abstained, s, line) {
    const groups = new Map(); // bucket -> {answer, weight, members}
    for (const b of ballots) {
      if (!groups.has(b.bucket)) groups.set(b.bucket, { answer: b.answer, weight: 0, members: [] });
      const g = groups.get(b.bucket);
      g.weight += b.weight;
      g.members.push(b.member);
    }
    const ranked = [...groups].sort((a, b) => b[1].weight - a[1].weight); // stable
    const tally = ranked.map(([, g]) => new Map([["answer", g.answer], ["weight", g.weight], ["members", [...g.members]]]));
    const votes = new Map(ballots.map(b => [b.member, b.answer]));
    const total = ballots.reduce((a, b) => a + b.weight, 0);

    const verdict = (agreed, decision, reason, winner = null, margin = 0, tiebreak = false) => {
      const label = s.ruleArg == null ? s.rule : `${s.rule} ${show(s.ruleArg)}`;
      return new Verdict({
        coalition: name, agreed, decision: agreed ? decision : null, reason, votes,
        abstained: new Map(abstained), dissent: agreed ? ballots.filter(b => b.bucket !== winner).map(b => b.member) : [],
        tally, margin, tiebreak, rule: label,
      });
    };

    const need = Math.max(1, s.minVotes);
    if (ballots.length < need) return verdict(false, null, `too few votes (${ballots.length} of ${need} needed)`);
    if (total <= EPS) return verdict(false, null, "all voters have zero trust");

    const [topBucket, top] = ranked[0];
    const secondW = ranked.length > 1 ? ranked[1][1].weight : 0;
    const isTie = ranked.length > 1 && Math.abs(top.weight - secondW) <= EPS;
    const margin = top.weight / total;
    const arg = s.ruleArg;
    let ok, why, fail;
    switch (s.rule) {
      case "majority": ok = top.weight > total / 2 + EPS; why = "majority"; fail = "no majority"; break;
      case "plurality": ok = !isTie; why = "plurality"; fail = "no single leader"; break;
      case "unanimous": ok = ranked.length === 1; why = "unanimous"; fail = "not unanimous"; break;
      case "quorum": {
        const q = Math.trunc(arg);
        ok = !isTie && top.members.length >= q; why = `quorum of ${q}`; fail = `no answer reached a quorum of ${q}`;
        break;
      }
      case "threshold":
        ok = !isTie && margin + EPS >= arg; why = `threshold ${show(arg)}`; fail = `no answer reached ${show(arg)} of the weight`;
        break;
      default: throw new GbnRuntimeError(`unknown rule '${s.rule}'`, line);
    }
    if (ok) {
      for (const v of s.veto) {
        const vb = ballots.find(b => b.member === v);
        if (vb && vb.bucket !== topBucket) return verdict(false, null, `vetoed by ${v}`);
      }
      return verdict(true, top.answer, why, topBucket, margin);
    }
    if (isTie && s.hasTie) {
      const tw = groups.has(s.tieBucket) ? groups.get(s.tieBucket).weight : 0;
      return verdict(true, s.tie, "tie broken by default", s.tieBucket, tw / total, true);
    }
    return verdict(false, null, isTie ? "tie" : fail);
  }

  function learn(learned, ballots, v, rate) {
    if (!v.agreed || v.tiebreak) return;
    const dissenters = new Set(v.dissent);
    for (const b of ballots) {
      const old = learned.has(b.member) ? learned.get(b.member) : b.weight;
      const nw = dissenters.has(b.member) ? old * (1 - rate) : old * (1 + rate);
      learned.set(b.member, Math.min(100, Math.max(0.01, nw)));
    }
  }

  // ----------------------------------------------------------------- journal

  const GENESIS = "0".repeat(64);

  function jsonable(v) {
    if (v === null || v === undefined || typeof v === "boolean" || typeof v === "number" || typeof v === "string") return v === undefined ? null : v;
    if (Array.isArray(v)) return v.map(jsonable);
    if (v instanceof Map) { const o = {}; for (const [k, x] of v) o[String(k)] = jsonable(x); return o; }
    return show(v);
  }
  /** JSON with sorted keys, like Python's json.dumps(sort_keys=True, separators=(",", ":")). */
  function canonical(v) {
    if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
    if (v && typeof v === "object") {
      return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
    }
    return JSON.stringify(v);
  }
  async function sha256(text) {
    const data = new TextEncoder().encode(text);
    const buf = await root.crypto.subtle.digest("SHA-256", data);
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function utcNow() {
    return new Date().toISOString().replace(/\.\d+Z$/, "+00:00");
  }

  /** In-memory storage for kept journals; the playground passes localStorage instead. */
  class MemoryStore {
    constructor() { this.data = new Map(); }
    getItem(k) { return this.data.has(k) ? this.data.get(k) : null; }
    setItem(k, v) { this.data.set(k, String(v)); }
  }

  class Journal {
    constructor(key, store, clock) {
      this.key = key; this.store = store; this.clock = clock; this.entries = [];
      this.seen = "";   // the stored text this journal has read or written
    }
    async load() {
      if (!this.key) return;
      const raw = this.store.getItem("gatbandhan:" + this.key);
      if (!raw) return;
      this.seen = raw;
      let prev = GENESIS;
      const lines = raw.split("\n").filter(l => l.trim());
      for (let i = 0; i < lines.length; i++) {
        let e;
        try { e = JSON.parse(lines[i]); } catch (_) {
          throw new GbnRuntimeError(`bond memory '${this.key}' is damaged at entry ${i + 1}: not valid JSON`);
        }
        const body = Object.assign({}, e); delete body.hash;
        if (e.prev !== prev || e.n !== i + 1 || e.hash !== await sha256(prev + canonical(body))) {
          throw new GbnRuntimeError(`bond memory '${this.key}' was changed by hand at entry ${i + 1}; ` +
            "a bond's history cannot be rewritten, so it is refused");
        }
        prev = e.hash;
        this.entries.push(e);
      }
    }
    get head() { return this.entries.length ? this.entries[this.entries.length - 1].hash : GENESIS; }
    async append(kind, fields) {
      const body = { n: this.entries.length + 1, kind, at: this.clock(), prev: this.head };
      for (const [k, v] of Object.entries(fields)) if (v !== null && v !== undefined) body[k] = jsonable(v);
      const entry = Object.assign({}, body, { hash: await sha256(body.prev + canonical(body)) });
      if (this.key) {
        const old = this.store.getItem("gatbandhan:" + this.key) || "";
        if (old !== this.seen) {
          // Someone else wrote to (or cut) the memory since we read it. Appending now
          // would fork the history, so stop instead.
          throw new GbnRuntimeError(`bond memory '${this.key}' was changed by another program while this one was running; run again to continue from the new history`);
        }
        this.seen = old + canonical(entry) + "\n";
        this.store.setItem("gatbandhan:" + this.key, this.seen);
      }
      this.entries.push(entry);
      return entry;
    }
    find(kind) { return this.entries.filter(e => e.kind === kind); }
    publicEntries() {
      return this.entries.map(e => toValue(Object.fromEntries(Object.entries(e).filter(([k]) => k !== "hash" && k !== "prev"))));
    }
  }
  /** Turn parsed JSON into Gatbandhan values (objects become maps). */
  function toValue(v) {
    if (Array.isArray(v)) return v.map(toValue);
    if (v && typeof v === "object") return new Map(Object.entries(v).map(([k, x]) => [k, toValue(x)]));
    return v;
  }

  // ------------------------------------------------------------- interpreter

  class ReturnSignal { constructor(value, feeling) { this.value = value; this.feeling = feeling; } }
  class AbstainSignal { constructor(reason) { this.reason = reason; } }
  class BreakSignal {}
  class ContinueSignal {}

  class Env {
    constructor(parent = null) { this.vars = new Map(); this.parent = parent; }
    lookup(name) {
      for (let e = this; e; e = e.parent) if (e.vars.has(name)) return e;
      return null;
    }
  }

  const MAX_DEPTH = 200;
  const MAX_STEPS = 5_000_000;

  function truthy(v) {
    if (v === null || v === undefined || v === false) return false;
    if (typeof v === "number") return v !== 0;
    if (v instanceof Bits) return v.value !== 0n;
    if (typeof v === "string" || Array.isArray(v)) return v.length > 0;
    if (v instanceof Map) return v.size > 0;
    return true;
  }
  const feelingText = v => (v === null || v === undefined ? null : show(v));

  class Interpreter {
    /**
     * options.print(line)            where printed lines go
     * options.ask(prompt) -> Promise  how the human answers; resolve null for no answer
     * options.store                   storage for kept bonds (default: in memory)
     * options.clock()                 timestamp for memory entries
     */
    constructor(options = {}) {
      this.printLine = options.print || (line => console.log(line));
      this.ask = options.ask || (async () => null);
      this.store = options.store || new MemoryStore();
      this.clock = options.clock || utcNow;
      this.models = new Map();
      this.humanScript = null;
      this.globals = new Env();
      this.bonds = new Map();
      this.depth = 0;
      this.steps = 0;
      installBuiltins(this);
    }

    async run(src) {
      const program = parse(src);
      try {
        await this.execBlock(program, this.globals);
      } catch (e) {
        if (e instanceof ReturnSignal) throw new GbnRuntimeError("'return' outside a function");
        if (e instanceof AbstainSignal) throw new GbnRuntimeError("'abstain' outside a member");
        if (e instanceof BreakSignal || e instanceof ContinueSignal) throw new GbnRuntimeError("'break' or 'continue' outside a loop");
        if (e instanceof RangeError) throw new GbnRuntimeError("too much recursion");
        throw e;
      }
    }

    // the bond's protections
    async refuse(bond, what, line, why = null) {
      await bond.journal.append("refused", { by: "program", text: what, line });
      throw new BondError(`refused: ${what}. ${why || `The bond '${bond.name}' cannot be overwritten`}`, line);
    }
    async guardName(name, line, action) {
      if (this.bonds.has(name)) await this.refuse(this.bonds.get(name), `${action} '${name}'`, line);
    }
    async sealedChange(container, line, key) {
      const bond = this.bonds.get(sealedOwner.get(container));
      if (!bond) throw new GbnRuntimeError("this value is sealed and cannot be changed", line);
      const at = key === undefined ? "" : ` at ${show(key, true)}`;
      await this.refuse(bond, `change a sealed ${typeName(container)}${at} that belongs to bond '${bond.name}'`, line);
    }

    // human partner
    async humanLine(prompt) {
      if (this.humanScript !== null) return this.humanScript.length ? this.humanScript.shift() : null;
      const r = await this.ask(prompt);
      if (r === null || r === undefined || !String(r).trim()) return null;
      return String(r);
    }
    async humanAnswer(name, question) {
      const scripted = this.humanScript !== null;
      const reply = await this.humanLine(`${name}, ${question}`);
      if (reply instanceof Map) {
        const reason = reply.get("reason");
        const objection = typeof reason === "string" && reason.trim() ? new Objection(reason.trim(), reply.get("condition") ?? null) : null;
        return [reply.get("answer") ?? null, reply.get("feeling") ?? null, objection];
      }
      if (reply === null) return [null, null, null];
      if (scripted) return [reply, null, null];
      // After a no, ask why and what would change it; both can be skipped.
      let objection = null;
      if (yesNo(reply) === 0) {
        const reason = await this.humanLine("Why not? (leave empty to skip)");
        if (reason) {
          const condition = await this.humanLine("What would change your mind? (leave empty to skip)");
          objection = new Objection(reason.trim(), condition ? condition.trim() : null);
        }
      }
      const feeling = await this.humanLine("How do you feel about it? (leave empty to skip)");
      return [reply, feeling, objection];
    }

    consultModel(name, line) {
      if (this.models.has(name)) {
        const q = this.models.get(name);
        if (!q.length) throw new GbnRuntimeError(`model '${name}' has no scripted replies left`, line);
        return q.shift();
      }
      throw new GbnRuntimeError(`no model named '${name}': in the playground, script it with script("${name}", [...])`, line);
    }

    // statements
    async execBlock(stmts, env) { for (const s of stmts) await this.exec(s, env); }

    async exec(s, env) {
      if (++this.steps > MAX_STEPS) throw new GbnRuntimeError("the program ran too long and was stopped", s.line);
      switch (s.type) {
        case "ExprStmt": await this.eval(s.expr, env); return;
        case "Let": await this.guardName(s.name, s.line, "rebind"); env.vars.set(s.name, await this.eval(s.value, env)); return;
        case "Assign": return this.assign(s, env);
        case "FnDecl": await this.guardName(s.name, s.line, "redefine"); env.vars.set(s.name, new Fn(s.name, s.params, s.body, env)); return;
        case "MemberDecl": {
          await this.guardName(s.name, s.line, "redefine");
          let trust = 1;
          if (s.trust) {
            trust = await this.eval(s.trust, env);
            if (!isNum(trust) || trust < 0) throw new GbnRuntimeError("a member's trust must be a number of 0 or more", s.line);
          }
          env.vars.set(s.name, new Member(s.name, s.params, s.body, env, trust));
          return;
        }
        case "CoalitionDecl": await this.guardName(s.name, s.line, "redefine"); env.vars.set(s.name, new Coalition(s.name, s, env)); return;
        case "BondDecl": return this.declareBond(s, env);
        case "VowStmt": return this.makeVow(this.bondNamed(s.bond, s.line), s.vow, env);
        case "Remember": return this.remember(s, env);
        case "If":
          if (truthy(await this.eval(s.cond, env))) await this.execBlock(s.then, new Env(env));
          else if (s.otherwise) await this.execBlock(s.otherwise, new Env(env));
          return;
        case "While":
          while (truthy(await this.eval(s.cond, env))) {
            try { await this.execBlock(s.body, new Env(env)); } catch (e) {
              if (e instanceof BreakSignal) break;
              if (e instanceof ContinueSignal) continue;
              throw e;
            }
          }
          return;
        case "For": {
          await this.guardName(s.var, s.line, "rebind");
          const seq = await this.eval(s.iterable, env);
          let items;
          if (seq instanceof Map) items = [...seq.keys()];
          else if (Array.isArray(seq)) items = [...seq];
          else if (typeof seq === "string") items = [...seq];
          else if (seq instanceof Bits) items = seq.list();
          else throw new GbnRuntimeError(`cannot loop over a ${typeName(seq)}`, s.line);
          for (const item of items) {
            const inner = new Env(env);
            inner.vars.set(s.var, item);
            try { await this.execBlock(s.body, inner); } catch (e) {
              if (e instanceof BreakSignal) break;
              if (e instanceof ContinueSignal) continue;
              throw e;
            }
          }
          return;
        }
        case "Return":
          throw new ReturnSignal(s.value ? await this.eval(s.value, env) : null, s.feeling ? await this.eval(s.feeling, env) : null);
        case "Abstain": {
          const r = s.reason ? await this.eval(s.reason, env) : null;
          throw new AbstainSignal(r === null ? "abstained" : r);
        }
        case "Break": throw new BreakSignal();
        case "Continue": throw new ContinueSignal();
        case "Match": return this.execMatch(s, env);
        default: throw new GbnRuntimeError(`unknown statement ${s.type}`, s.line);
      }
    }

    async assign(s, env) {
      const t = s.target;
      if (t.type === "Name") {
        await this.guardName(t.name, s.line, "overwrite");
        const scope = env.lookup(t.name);
        if (!scope) throw new GbnRuntimeError(`'${t.name}' is not defined (use 'let' to create it)`, s.line);
        scope.vars.set(t.name, await this.eval(s.value, env));
        return;
      }
      const obj = await this.eval(t.target, env);
      if (obj instanceof Bond) await this.refuse(obj, `overwrite ${t.type === "Field" ? t.name : "an entry"} of bond '${obj.name}'`, s.line);
      const value = await this.eval(s.value, env);
      const key = t.type === "Field" ? t.name : await this.eval(t.index, env);
      if (isSealed(obj)) await this.sealedChange(obj, s.line, key);
      if (Array.isArray(obj)) {
        if (!isInt(key)) throw new GbnRuntimeError("list index must be a whole number", s.line);
        if (key < -obj.length || key >= obj.length) throw new GbnRuntimeError(`index ${key} is out of range`, s.line);
        obj[key < 0 ? obj.length + key : key] = value;
      } else if (obj instanceof Map) {
        obj.set(key, value);
      } else {
        throw new GbnRuntimeError(`cannot set a field or index on a ${typeName(obj)}`, s.line);
      }
    }

    async execMatch(s, env) {
      const v = await this.eval(s.subject, env);
      if (!(v instanceof Verdict)) throw new GbnRuntimeError(`match needs a verdict, got a ${typeName(v)}`, s.line);
      // The most specific arm wins: a bond's own outcome first, then agreed or split.
      const umbrella = v.agreed ? "agreed" : "split";
      for (const word of v.outcome ? [v.outcome, umbrella] : [umbrella]) {
        const arm = s.arms[word];
        if (!arm) continue;
        const inner = new Env(env);
        if (arm.name) {
          await this.guardName(arm.name, s.line, "rebind");
          inner.vars.set(arm.name, word === "approved" || word === "agreed" ? v.decision : v.reason);
        }
        await this.execBlock(arm.body, inner);
        return;
      }
    }

    // bonds
    bondNamed(name, line) {
      if (!this.bonds.has(name)) throw new GbnRuntimeError(`no bond named '${name}'`, line);
      return this.bonds.get(name);
    }

    async declareBond(s, env) {
      if (this.bonds.has(s.name)) await this.refuse(this.bonds.get(s.name), `declare the bond '${s.name}' a second time`, s.line);
      if (env.lookup(s.name)) throw new GbnRuntimeError(`'${s.name}' is already defined; a bond needs a name of its own`, s.line);
      const human = await this.eval(s.human, env);
      if (typeof human !== "string" || !human.trim()) throw new GbnRuntimeError("a bond's human partner must be a name (a string)", s.line);
      const ai = await this.eval(s.ai, env);
      let aiName;
      if (typeof ai === "string") aiName = ai;
      else if (ai instanceof Member || ai instanceof Fn) aiName = ai.name;
      else throw new GbnRuntimeError("a bond's ai partner must be a member, a function or a model name", s.line);
      const key = s.key ? await this.eval(s.key, env) : null;
      let keep = null;
      if (s.keep) {
        keep = await this.eval(s.keep, env);
        if (typeof keep !== "string") throw new GbnRuntimeError("'keep' must be a name for the saved memory", s.line);
      }
      const journal = new Journal(keep, this.store, this.clock);
      await journal.load();
      const bond = new Bond({ name: s.name, humanName: human, ai, aiName, key, journal });
      const formed = journal.find("bond");
      if (formed.length) {
        const f = formed[0];
        if (f.name !== s.name || f.human !== human || f.ai !== aiName) {
          throw new BondError(`refused: this memory holds the bond '${f.name}' between ${f.human} and ${f.ai}; ` +
            "it cannot be given to someone else", s.line);
        }
        for (const e of journal.find("vow")) {
          bond.vows.set(e.vow, seal(toValue(e.value), s.name));
          bond.vowLines.set(e.vow, e.n);
        }
      } else {
        await journal.append("bond", { by: "both", name: s.name, human, ai: aiName, text: `${human} and ${aiName} formed the bond '${s.name}'` });
      }
      this.bonds.set(s.name, bond);
      env.vars.set(s.name, bond);
      for (const vow of s.vows) await this.makeVow(bond, vow, env);
    }

    async makeVow(bond, vow, env) {
      const value = await this.eval(vow.value, env);
      if (bond.vows.has(vow.name)) {
        if (freeze(bond.vows.get(vow.name)) === freeze(value)) return;
        await this.refuse(bond, `overwrite the vow '${vow.name}' (made in entry ${bond.vowLines.get(vow.name)})`, vow.line);
      }
      const e = await bond.journal.append("vow", { by: "both", vow: vow.name, value: unseal(value), text: show(value) });
      bond.vows.set(vow.name, seal(value, bond.name));
      bond.vowLines.set(vow.name, e.n);
    }

    async remember(s, env) {
      const bond = this.bondNamed(s.bond, s.line);
      const text = await this.eval(s.text, env);
      const feeling = s.feeling ? await this.eval(s.feeling, env) : null;
      const by = { human: bond.humanName, ai: bond.aiName }[s.by] || "both";
      if (!s.amends) {
        await bond.journal.append("memory", { by, text: show(text), feeling: feelingText(feeling) });
        return;
      }
      const n = await this.eval(s.amends, env);
      if (!isInt(n) || n < 1 || n > bond.journal.entries.length) {
        throw new GbnRuntimeError(`bond '${bond.name}' has no memory entry ${show(n)} to amend`, s.line);
      }
      await bond.journal.append("amend", { by, amends: n, text: show(text), feeling: feelingText(feeling) });
    }

    async consultPartner(bond, question, line) {
      const ai = bond.ai;
      if (ai instanceof Member || ai instanceof Fn) {
        const [kind, a, b] = await this.runMember(ai, [question], line);
        return kind === "vote" ? [a, b] : [null, a];
      }
      let reply = this.consultModel(ai, line);
      if (!(reply instanceof Map)) {
        try {
          const data = JSON.parse(reply);
          if (data && typeof data === "object" && "answer" in data) reply = toValue(data);
        } catch (_) { /* a plain-text reply */ }
      }
      if (reply instanceof Map) return [objectionFrom(reply), reply.get("feeling") ?? null];
      return [reply, null];
    }

    async callBond(bond, args, line) {
      if (args.length !== 1) throw new GbnRuntimeError(`a bond is asked one question at a time, got ${args.length} arguments`, line);
      const proposal = args[0] instanceof Proposal ? args[0] : null;
      let question;
      if (proposal) {
        if (proposal.bond !== bond) throw new GbnRuntimeError(`proposal ${proposal.id} belongs to bond '${proposal.bond.name}', not '${bond.name}'`, line);
        const status = proposal.status();
        if (["approved", "rejected", "replaced"].includes(status)) {
          // A decided proposal is never decided again, and an old version is never reused.
          await this.refuse(bond, `ask proposal ${proposal.id} again: it is already ${status}`, line,
            "A decided proposal stays decided, and an old version is never reused; revise it to ask again");
        }
        question = proposal.text;
      } else question = show(args[0]);
      const ballots = [];
      const abstained = new Map();
      const feelings = new Map();
      let [hA, hF, hO] = await this.humanAnswer(bond.humanName, question);
      const [aA, aX] = await this.consultPartner(bond, question, line);
      if (hO && yesNo(hA) === 0) hA = hO;
      const objections = new Map();
      for (const [who, answer0, extra] of [[bond.humanName, hA, hF], [bond.aiName, aA, aX]]) {
        let answer = answer0;
        if (answer instanceof Objection) {
          // A "no" that says why: the vote is a no, and the reason is kept with it.
          objections.set(who, new Map([["reason", answer.reason], ["condition", answer.condition]]));
          answer = "no";
        }
        if (answer === null || answer === undefined) {
          abstained.set(who, typeof extra === "string" && extra ? extra : "did not answer");
          continue;
        }
        if (extra !== null && extra !== undefined) feelings.set(who, feelingText(extra));
        if (typeof answer === "string") answer = answer.trim();
        const sign = bond.key ? null : yesNo(answer);
        const bucket = sign !== null ? "\u0000yes/no:" + sign : await this.bucket(bond.key, answer, line, true);
        ballots.push({ member: who, answer, bucket, weight: 1 });
      }
      const settings = { rule: "unanimous", ruleArg: null, veto: [], hasTie: false, minVotes: 2 };
      const v = decide(bond.name, ballots, abstained, settings, line);
      let marks = new Map([[bond.humanName, yesNo(hA)], [bond.aiName, yesNo(aA)]]);
      if (abstained.size) {
        // Silence is its own state: not yes, not no, and never consent.
        v.outcome = "silent";
        v.reason = `no consent: ${[...abstained.keys()].join(" and ")} did not answer`;
        for (const who of marks.keys()) {
          if (abstained.has(who)) marks.set(who, null);
          else if (marks.get(who) === null) marks.set(who, 1); // an open answer was given
        }
      } else if (v.agreed) {
        if ([...marks.values()].every(m => m === 0)) { v.outcome = "rejected"; v.reason = "rejected together"; }
        else { v.outcome = "approved"; v.reason = "both approve"; marks = new Map([...marks.keys()].map(k => [k, 1])); }
      } else {
        v.outcome = "disagreed";
        v.reason = "the partners disagree";
        // Open answers that differ: the human's answer leads, the AI's differs.
        if ([...marks.values()].includes(null)) marks = new Map([[bond.humanName, 1], [bond.aiName, 0]]);
      }
      v.marks = marks;
      v.feelings = feelings;
      v.question = question;
      v.rule = "and";
      v.partners = [bond.humanName, bond.aiName];
      v.proposal = proposal;
      v.objections = objections;
      await bond.journal.append("decision", {
        by: "both", question, text: `${question} (${v.reason})`,
        proposal: proposal ? proposal.fingerprint : null, proposal_id: proposal ? proposal.id : null, outcome: v.outcome, agreed: v.agreed, decision: v.decision,
        votes: v.votes, gate: v.gate(), feelings: feelings.size ? feelings : null, abstained: abstained.size ? abstained : null,
        objections: objections.size ? objections : null,
      });
      return v;
    }

    // members and coalitions
    async runMember(fn, args, line) {
      let value, feeling = null;
      try {
        const copies = args.map(unseal).map(deepCopy);
        if (fn instanceof Member) [value, feeling] = await this.callFunction(fn, copies, line);
        else if (fn instanceof Coalition || fn instanceof Bond) {
          const v = await this.call(fn, copies, line);
          if (!v.agreed) return ["abstain", `${fn.name} split: ${v.reason}`, null];
          return ["vote", v.decision, null];
        } else value = await this.call(fn, copies, line);
      } catch (e) {
        if (e instanceof AbstainSignal) return ["abstain", show(e.reason), null];
        if (e instanceof BondError) throw e;
        if (e instanceof GbnRuntimeError) return ["abstain", `error: ${e.msg}`, null];
        throw e;
      }
      if (value === null || value === undefined) return ["abstain", "returned none", null];
      return ["vote", value, feeling];
    }

    async bucket(key, answer, line, fold = false) {
      if (key) return freeze(await this.call(key, [answer], line));
      if (fold && typeof answer === "string") return freeze(answer.trim().toLowerCase());
      return freeze(answer);
    }

    async callCoalition(c, args, line) {
      const d = c.decl;
      if (args.length !== d.params.length) throw new GbnRuntimeError(`coalition '${c.name}' takes ${d.params.length} arguments, got ${args.length}`, line);
      const env = new Env(c.closure);
      d.params.forEach((p, i) => env.vars.set(p, args[i]));
      const members = [];
      for (const m of d.members) members.push(await this.eval(m, env));
      const names = [];
      members.forEach((m, i) => {
        const callable = m instanceof Fn || m instanceof Builtin || m instanceof Member || m instanceof Coalition || m instanceof Bond;
        if (!callable) throw new GbnRuntimeError(`coalition '${c.name}': member ${i + 1} is a ${typeName(m)}, not something that can vote`, line);
        let nm = m.name;
        if (!nm || (m instanceof Fn && nm === "fn")) nm = `member${i + 1}`;
        if (names.includes(nm)) nm = `${nm}#${i + 1}`;
        names.push(nm);
      });
      const weights = d.weights ? await this.eval(d.weights, env) : new Map();
      if (!(weights instanceof Map)) throw new GbnRuntimeError("'weights' must be a map of member name to weight", line);
      const key = d.key ? await this.eval(d.key, env) : null;
      const rate = d.learn ? await this.eval(d.learn, env) : null;
      if (rate !== null && !(isNum(rate) && rate > 0 && rate < 1)) throw new GbnRuntimeError("'learn' must be a number between 0 and 1", line);
      const s = { rule: d.rule.kind, ruleArg: null, veto: [], hasTie: false, tie: null, tieBucket: null, minVotes: 1 };
      if (d.rule.arg) {
        s.ruleArg = await this.eval(d.rule.arg, env);
        if (!isNum(s.ruleArg) || s.ruleArg <= 0) throw new GbnRuntimeError(`rule '${d.rule.kind}' needs a positive number`, line);
        if (d.rule.kind === "threshold" && s.ruleArg > 1) throw new GbnRuntimeError("a threshold is a share of the weight, between 0 and 1", line);
      }
      if (d.min_votes) s.minVotes = await this.eval(d.min_votes, env);
      for (const v of d.veto) {
        const vm = await this.eval(v, env);
        const idx = members.indexOf(vm);
        if (idx < 0) throw new GbnRuntimeError(`coalition '${c.name}': veto must name one of its members`, line);
        s.veto.push(names[idx]);
      }
      if (d.tie) {
        s.hasTie = true;
        s.tie = await this.eval(d.tie, env);
        s.tieBucket = await this.bucket(key, s.tie, line);
      }
      const ballots = [];
      const abstained = new Map();
      const feelings = new Map();
      for (let i = 0; i < members.length; i++) {
        const m = members[i];
        const nm = names[i];
        const [kind, answer, feeling] = await this.runMember(m, args, line);
        if (kind === "abstain") { abstained.set(nm, answer); continue; }
        if (feeling !== null && feeling !== undefined) feelings.set(nm, feelingText(feeling));
        let w = c.learned.has(nm) ? c.learned.get(nm) : weights.has(nm) ? weights.get(nm) : m instanceof Member ? m.trust : 1;
        if (!isNum(w) || w < 0) throw new GbnRuntimeError(`weight of '${nm}' must be a number of 0 or more`, line);
        ballots.push({ member: nm, answer, bucket: await this.bucket(key, answer, line), weight: w });
      }
      const v = decide(c.name, ballots, abstained, s, line);
      v.feelings = feelings;
      if (rate !== null) learn(c.learned, ballots, v, rate);
      c.history.push(v);
      return v;
    }

    // calls
    async call(fn, args, line) {
      if (fn instanceof Builtin) {
        try { return await fn.fn(args, line); } catch (e) {
          if (e instanceof GatbandhanError) throw e.withLine(line);
          throw e;
        }
      }
      if (fn instanceof Coalition) return this.callCoalition(fn, args, line);
      if (fn instanceof Bond) return this.callBond(fn, args, line);
      if (fn instanceof Fn || fn instanceof Member) {
        try { return (await this.callFunction(fn, args, line))[0]; } catch (e) {
          if (e instanceof AbstainSignal) return null;
          throw e;
        }
      }
      throw new GbnRuntimeError(`a ${typeName(fn)} cannot be called`, line);
    }

    async callFunction(fn, args, line) {
      if (args.length !== fn.params.length) throw new GbnRuntimeError(`'${fn.name}' takes ${fn.params.length} arguments, got ${args.length}`, line);
      if (this.depth >= MAX_DEPTH) throw new GbnRuntimeError("too much recursion", line);
      const env = new Env(fn.closure);
      for (let i = 0; i < args.length; i++) {
        await this.guardName(fn.params[i], line, "rebind");
        env.vars.set(fn.params[i], args[i]);
      }
      this.depth++;
      try {
        await this.execBlock(fn.body, env);
      } catch (e) {
        if (e instanceof ReturnSignal) return [e.value, e.feeling];
        if (e instanceof BreakSignal || e instanceof ContinueSignal) throw new GbnRuntimeError("'break' or 'continue' outside a loop", line);
        throw e;
      } finally {
        this.depth--;
      }
      return [null, null];
    }

    // expressions
    async eval(e, env) {
      switch (e.type) {
        case "Literal": return e.value;
        case "Name": {
          const scope = env.lookup(e.name);
          if (!scope) throw new GbnRuntimeError(`'${e.name}' is not defined`, e.line);
          return scope.vars.get(e.name);
        }
        case "Template": {
          let out = "";
          for (const p of e.parts) out += typeof p === "string" ? p : show(await this.eval(p, env));
          return out;
        }
        case "ListLit": { const out = []; for (const x of e.items) out.push(await this.eval(x, env)); return out; }
        case "MapLit": { const m = new Map(); for (const [k, x] of e.entries) m.set(k, await this.eval(x, env)); return m; }
        case "FnLit": return new Fn("fn", e.params, e.body, env);
        case "Unary": {
          const v = await this.eval(e.operand, env);
          if (e.op === "not") return !truthy(v);
          if (e.op === "~") {
            if (v instanceof Bits) return new Bits(~v.value & v.mask, v.width);
            if (!isInt(v)) throw new GbnRuntimeError(`'~' needs a whole number, got a ${typeName(v)}`, e.line);
            return ~v;
          }
          if (!isNum(v)) throw new GbnRuntimeError(`cannot negate a ${typeName(v)}`, e.line);
          return -v;
        }
        case "Binary": return this.binary(e, env);
        case "Call": {
          const fn = await this.eval(e.callee, env);
          const args = [];
          for (const a of e.args) args.push(await this.eval(a, env));
          return this.call(fn, args, e.line);
        }
        case "Index": return this.index(await this.eval(e.target, env), await this.eval(e.index, env), e.line);
        case "Field": return this.field(await this.eval(e.target, env), e.name, e.line);
        default: throw new GbnRuntimeError(`unknown expression ${e.type}`, e.line);
      }
    }

    async binary(e, env) {
      const op = e.op;
      if (op === "and") { const l = await this.eval(e.left, env); return truthy(l) ? this.eval(e.right, env) : l; }
      if (op === "or") { const l = await this.eval(e.left, env); return truthy(l) ? l : this.eval(e.right, env); }
      const a = await this.eval(e.left, env);
      const b = await this.eval(e.right, env);
      const line = e.line;
      if (op === "==") return freeze(a) === freeze(b);
      if (op === "!=") return freeze(a) !== freeze(b);
      if (op === "in") {
        if (typeof b === "string" && typeof a === "string") return b.includes(a);
        if (Array.isArray(b)) return b.some(x => freeze(x) === freeze(a));
        if (b instanceof Map) return b.has(a);
        throw new GbnRuntimeError(`cannot look inside a ${typeName(b)} with 'in'`, line);
      }
      if (op === "+") {
        if (isNum(a) && isNum(b)) return a + b;
        if (typeof a === "string" && typeof b === "string") return a + b;
        if (Array.isArray(a) && Array.isArray(b)) return [...a, ...b];
        if (a instanceof Bits && b instanceof Bits) return new Bits((a.value << BigInt(b.width)) | b.value, a.width + b.width);
        throw new GbnRuntimeError(`cannot add a ${typeName(a)} and a ${typeName(b)}`, line);
      }
      if (["<", "<=", ">", ">="].includes(op)) {
        if (!((isNum(a) && isNum(b)) || (typeof a === "string" && typeof b === "string"))) {
          throw new GbnRuntimeError(`cannot compare a ${typeName(a)} and a ${typeName(b)}`, line);
        }
        return op === "<" ? a < b : op === "<=" ? a <= b : op === ">" ? a > b : a >= b;
      }
      if (["&", "|", "^", "<<", ">>"].includes(op)) {
        if (a instanceof Bits) return this.bitOp(op, a, b, line);
        if (b instanceof Bits) {
          throw new GbnRuntimeError(`cannot combine a number and bits with '${op}'; turn the number into bits with bits(n, width)`, line);
        }
        if (!(isInt(a) && isInt(b))) throw new GbnRuntimeError(`'${op}' needs whole numbers, got a ${typeName(a)} and a ${typeName(b)}`, line);
        if ((op === "<<" || op === ">>") && b < 0) throw new GbnRuntimeError("cannot shift by a negative number of bits", line);
        if (op === "<<" && b > 4096) throw new GbnRuntimeError("shift is too large", line);
        const A = BigInt(a), B = BigInt(b);
        const r = op === "&" ? A & B : op === "|" ? A | B : op === "^" ? A ^ B : op === "<<" ? A << B : A >> B;
        return Number(r);
      }
      if (!(isNum(a) && isNum(b))) throw new GbnRuntimeError(`'${op}' needs numbers, got a ${typeName(a)} and a ${typeName(b)}`, line);
      if (op === "-") return a - b;
      if (op === "*") return a * b;
      if (b === 0) throw new GbnRuntimeError("division by zero", line);
      if (op === "/") return a / b;
      return ((a % b) + b) % b; // the sign follows the divisor, as in Python
    }

    bitOp(op, a, b, line) {
      if (op === "<<" || op === ">>") {
        if (!isInt(b) || b < 0) throw new GbnRuntimeError("bits shift by a whole number of 0 or more", line);
        const n = BigInt(Math.min(b, a.width));
        return new Bits(op === "<<" ? (a.value << n) & a.mask : a.value >> n, a.width);
      }
      if (!(b instanceof Bits)) {
        throw new GbnRuntimeError(`cannot combine bits and a ${typeName(b)} with '${op}'; turn the number into bits with bits(n, width)`, line);
      }
      const v = op === "&" ? a.value & b.value : op === "|" ? a.value | b.value : a.value ^ b.value;
      return new Bits(v, Math.max(a.width, b.width));
    }

    index(obj, key, line) {
      if (Array.isArray(obj) || typeof obj === "string" || obj instanceof Bits) {
        const len = obj instanceof Bits ? obj.width : obj.length;
        if (!isInt(key)) throw new GbnRuntimeError("index must be a whole number", line);
        if (key < -len || key >= len) throw new GbnRuntimeError(`index ${key} is out of range`, line);
        const i = key < 0 ? len + key : key;
        if (obj instanceof Bits) return obj.bit(i);
        if (typeof obj === "string") return [...obj][i];
        return obj[i];
      }
      if (obj instanceof Map) return obj.has(key) ? obj.get(key) : null;
      throw new GbnRuntimeError(`cannot index a ${typeName(obj)}`, line);
    }

    field(obj, name, line) {
      if (obj instanceof Map) return obj.has(name) ? obj.get(name) : null;
      if (obj instanceof Verdict) {
        if (!VERDICT_FIELDS.includes(name)) throw new GbnRuntimeError(`a verdict has no field '${name}'`, line);
        return obj.get(name);
      }
      if (obj instanceof Objection) {
        if (!OBJECTION_FIELDS.includes(name)) throw new GbnRuntimeError(`an objection has no field '${name}'`, line);
        return obj.get(name);
      }
      if (obj instanceof Proposal) {
        if (!PROPOSAL_FIELDS.includes(name)) throw new GbnRuntimeError(`a proposal has no field '${name}'`, line);
        return obj.get(name);
      }
      if (obj instanceof Bond) {
        if (!BOND_FIELDS_READ.includes(name)) throw new GbnRuntimeError(`a bond has no field '${name}'`, line);
        return obj.get(name);
      }
      if ((obj instanceof Member || obj instanceof Coalition || obj instanceof Fn) && name === "name") return obj.name;
      if (obj instanceof Member && name === "trust") return obj.trust;
      throw new GbnRuntimeError(`a ${typeName(obj)} has no field '${name}'`, line);
    }
  }

  function deepCopy(v) {
    if (Array.isArray(v)) return v.map(deepCopy);
    if (v instanceof Map) return new Map([...v].map(([k, x]) => [k, deepCopy(x)]));
    return v;
  }

  // ---------------------------------------------------------------- builtins

  function installBuiltins(it) {
    const def = (name, fn) => it.globals.vars.set(name, new Builtin(name, fn));
    const err = msg => { throw new GbnRuntimeError(msg); };
    const S = (v, f) => (typeof v === "string" ? v : err(`${f} needs a string, got a ${typeName(v)}`));
    const L = (v, f) => (Array.isArray(v) ? v : err(`${f} needs a list, got a ${typeName(v)}`));
    const M = (v, f) => (v instanceof Map ? v : err(`${f} needs a map, got a ${typeName(v)}`));
    const N = (v, f) => (isNum(v) ? v : err(`${f} needs a number, got a ${typeName(v)}`));
    const nums = (xs, f) => {
      if (xs.length === 1 && Array.isArray(xs[0])) xs = xs[0];
      if (!xs.length) err(`${f} needs at least one number`);
      return xs.map(x => N(x, f));
    };
    const argc = (args, lo, hi, f) => {
      if (args.length < lo || args.length > hi) err(`${f}: expected ${lo === hi ? lo : `${lo} to ${hi}`} arguments, got ${args.length}`);
    };

    def("print", args => { it.printLine(args.map(a => show(a)).join(" ")); return null; });
    def("len", ([v]) => {
      if (typeof v === "string") return [...v].length;
      if (Array.isArray(v)) return v.length;
      if (v instanceof Map) return v.size;
      if (v instanceof Bits) return v.width;
      return err(`len needs a string, list or map, got a ${typeName(v)}`);
    });
    def("str", ([v]) => show(v));
    def("num", ([v]) => {
      if (isNum(v)) return v;
      if (v instanceof Bits) return Number(v.value);
      if (typeof v === "string") {
        const t = v.trim();
        if (!t || isNaN(Number(t))) err(`cannot turn ${show(v, true)} into a number`);
        return Number(t);
      }
      return err(`cannot turn a ${typeName(v)} into a number`);
    });
    def("type_of", ([v]) => typeName(v));
    def("lower", ([s]) => S(s, "lower").toLowerCase());
    def("upper", ([s]) => S(s, "upper").toUpperCase());
    def("trim", ([s]) => S(s, "trim").trim());
    def("contains", ([h, n]) => {
      if (typeof h === "string") return h.includes(S(n, "contains"));
      if (Array.isArray(h)) return h.some(x => freeze(x) === freeze(n));
      if (h instanceof Map) return h.has(n);
      return err(`contains needs a string, list or map, got a ${typeName(h)}`);
    });
    def("starts_with", ([s, p]) => S(s, "starts_with").startsWith(S(p, "starts_with")));
    def("ends_with", ([s, p]) => S(s, "ends_with").endsWith(S(p, "ends_with")));
    def("split", ([s, sep]) => (sep === undefined || sep === null ? S(s, "split").trim().split(/\s+/).filter(Boolean) : S(s, "split").split(S(sep, "split"))));
    def("join", ([xs, sep = ""]) => L(xs, "join").map(x => show(x)).join(S(sep, "join")));
    def("replace", ([s, a, b]) => S(s, "replace").split(S(a, "replace")).join(S(b, "replace")));
    def("keys", ([m]) => [...M(m, "keys").keys()]);
    def("values", ([m]) => [...M(m, "values").values()]);
    def("push", async (args, line) => {
      argc(args, 2, 2, "push");
      const xs = L(args[0], "push");
      if (isSealed(xs)) await it.sealedChange(xs, line);
      xs.push(args[1]);
      return xs;
    });
    def("range", ([a, b]) => {
      if (b === undefined) { b = a; a = 0; }
      const out = [];
      for (let i = Math.trunc(N(a, "range")); i < Math.trunc(N(b, "range")); i++) out.push(i);
      return out;
    });
    def("round", ([x, d = 0]) => { const f = 10 ** Math.trunc(d); return Math.round(N(x, "round") * f) / f; });
    def("abs", ([x]) => Math.abs(N(x, "abs")));
    def("min", args => Math.min(...nums(args, "min")));
    def("max", args => Math.max(...nums(args, "max")));
    def("sum", ([xs]) => L(xs, "sum").reduce((a, x) => a + N(x, "sum"), 0));
    def("sort", ([xs]) => {
      const c = [...L(xs, "sort")];
      if (c.every(isNum)) return c.sort((a, b) => a - b);
      if (c.every(x => typeof x === "string")) return c.sort();
      return err("sort needs a list of all numbers or all strings");
    });
    def("copy", ([v]) => deepCopy(unseal(v)));
    def("error", ([m]) => err(m === undefined ? "error" : show(m)));
    def("hear", async ([p]) => {
      const r = await it.humanLine(p === undefined ? "" : show(p));
      return r instanceof Map ? r.get("answer") ?? null : r;
    });
    def("consult", ([model, text]) => {
      if (typeof model !== "string" || text === undefined) err("consult(model, text) needs a model name and the text to send");
      const r = it.consultModel(model);
      return r instanceof Map ? r.get("answer") ?? null : r;
    });
    def("script", ([model, replies]) => {
      if (typeof model !== "string" || !Array.isArray(replies)) err("script(model, replies) needs a model name and a list of replies");
      it.models.set(model, unseal(replies));
      return null;
    });
    def("script_human", ([replies]) => { it.humanScript = [...unseal(L(replies, "script_human"))]; return null; });
    def("trust", ([c]) => {
      if (!(c instanceof Coalition)) err("trust(c) needs a coalition");
      return new Map([...c.learned].map(([k, v]) => [k, Math.round(v * 1e6) / 1e6]));
    });
    def("history", ([c]) => { if (!(c instanceof Coalition)) err("history(c) needs a coalition"); return [...c.history]; });
    def("vows", ([b]) => { if (!(b instanceof Bond)) err("vows(b) needs a bond"); return b.get("vows"); });
    def("memory", ([b]) => { if (!(b instanceof Bond)) err("memory(b) needs a bond"); return b.get("memory"); });
    const addProposal = async (bond, text, version, replaces, standing = false, needs = []) => {
      const n = bond.journal.entries.length + 1;
      const material = { bond: bond.get("id"), n, text, version, replaces };
      if (standing) material.standing = true;
      if (needs.length) material.needs = needs.map(p => p.fingerprint);
      const fp = await sha256(canonical(material));
      return new Proposal(bond, await bond.journal.append("proposal", {
        text, version, replaces, standing: standing ? true : null, needs: needs.length ? needs.map(p => p.id) : null, fingerprint: fp,
      }));
    };
    // Read {standing: bool, needs: [proposals]} for propose and revise.
    const options = (bond, opts, fn) => {
      if (opts === undefined || opts === null) return [false, []];
      if (!(opts instanceof Map) || [...opts.keys()].some(k => k !== "standing" && k !== "needs")) err(`${fn}: options are a map with 'standing' and 'needs'`);
      const standing = opts.has("standing") ? opts.get("standing") : false;
      const needs = opts.get("needs") || [];
      if (typeof standing !== "boolean") err(`${fn}: 'standing' must be true or false`);
      if (!Array.isArray(needs) || !needs.every(p => p instanceof Proposal && p.bond === bond)) err(`${fn}: 'needs' must be a list of proposals of the same bond`);
      return [standing, [...needs]];
    };
    def("propose", async (args) => {
      if (![2, 3].includes(args.length) || !(args[0] instanceof Bond) || typeof args[1] !== "string") err("propose(bond, text, options?) needs a bond and a text");
      const [standing, needs] = options(args[0], args[2], "propose");
      return addProposal(args[0], args[1], 1, null, standing, needs);
    });
    def("revise", async (args) => {
      if (![2, 3].includes(args.length) || !(args[0] instanceof Proposal) || typeof args[1] !== "string") err("revise(proposal, text, options?) needs a proposal and a text");
      const p = args[0];
      const status = p.status();
      if (status === "replaced") err(`proposal ${p.id} was already revised; revise its newest version`);
      if (!["pending", "disagreed", "deadlocked"].includes(status)) {
        err(`proposal ${p.id} is already ${status}; a decided proposal is not revised, make a new one with propose()`);
      }
      const [standing, needs] = args.length === 3 ? options(p.bond, args[2], "revise")
        : [p.standing, p.needs.map(n => new Proposal(p.bond, p.entryOf(n)))];
      return addProposal(p.bond, args[1], p.version + 1, p.id, standing, needs);
    });
    // Run work under an approved proposal. Anything else is refused and remembered.
    def("act", async (args, line) => {
      if (args.length !== 2 || !(args[0] instanceof Proposal) || !(args[1] instanceof Fn || args[1] instanceof Builtin || args[1] instanceof Member)) {
        err("act(proposal, fn() { ... }) needs a proposal and a function");
      }
      const [p, work] = args;
      const bond = p.bond;
      const why = "Only work both partners approved can run under the bond";
      const status = p.status();
      if (status !== "approved") await it.refuse(bond, `act on proposal ${p.id}: it is ${status}, not approved by both`, line, why);
      const blocked = p.blockedBy();
      if (blocked.length) {
        const need = new Proposal(bond, p.entryOf(blocked[0]));
        await it.refuse(bond, `act on proposal ${p.id}: it needs proposal ${need.id}, which is ${need.status()}`, line, why);
      }
      const uses = p.entries("act").length;
      if (!p.standing && uses) {
        await it.refuse(bond, `act on proposal ${p.id} again: it allowed one action and it was used`, line,
          "A one-time approval is never reused; propose again, or approve a standing permission");
      }
      // The use is written down before the work runs, so a crash cannot hide it.
      await bond.journal.append("act", { by: "program", proposal: p.fingerprint, proposal_id: p.id, use: uses + 1, text: `acted on proposal ${p.id}: ${p.text}` });
      return it.call(work, [], line);
    });
    // Withdraw an approval. Consent needs both partners, so either one may withdraw it.
    def("revoke", async (args) => {
      if (args.length !== 1 || !(args[0] instanceof Proposal)) err("revoke(proposal) needs a proposal");
      const p = args[0];
      const status = p.status();
      if (status !== "approved") err(`proposal ${p.id} is ${status}; only an approved proposal can be revoked`);
      await p.bond.journal.append("revoke", { by: "program", proposal: p.fingerprint, proposal_id: p.id, text: `revoked proposal ${p.id}: ${p.text}` });
      return null;
    });
    const listProposals = (b, fn, openOnly) => {
      if (!(b instanceof Bond)) err(`${fn}(b) needs a bond`);
      const out = b.journal.entries.filter(e => e.kind === "proposal").map(e => new Proposal(b, e));
      return openOnly ? out.filter(p => ["pending", "disagreed", "deadlocked"].includes(p.status())) : out;
    };
    def("proposals", ([b]) => listProposals(b, "proposals", false));
    def("unresolved", ([b]) => listProposals(b, "unresolved", true));
    def("objection", (args) => {
      if (args.length < 1 || args.length > 2 || typeof args[0] !== "string" || !args[0].trim()) err("objection(reason, condition?) needs a reason");
      return new Objection(args[0].trim(), args.length === 2 ? args[1] : null);
    });
    def("bits", ([v, width]) => makeBits(v, width));
    def("version", () => VERSION);
  }

  function makeBits(v, width) {
    const err = msg => { throw new GbnRuntimeError(msg); };
    let n, size;
    if (v instanceof Bits) { n = v.value; size = v.width; }
    else if (Array.isArray(v)) {
      if (!v.length || v.some(x => x !== 0 && x !== 1)) err("bits from a list needs a non-empty list of 0s and 1s");
      n = BigInt("0b" + v.join("")); size = v.length;
    } else if (typeof v === "string") {
      if (/^[01]+$/.test(v)) { n = BigInt("0b" + v); size = v.length; }
      else if (/^[0-9a-f]{64}$/.test(v)) { n = BigInt("0x" + v); size = 256; }
      else err("bits from text needs 0s and 1s, or a bond's seal");
    } else {
      if (!isNum(v)) err(`bits needs a number, got a ${typeName(v)}`);
      if (!Number.isInteger(v) || v < 0) err("bits needs a whole number of 0 or more");
      n = BigInt(v); size = Math.max(1, n.toString(2).length);
    }
    if (width !== undefined && width !== null) {
      if (!isNum(width)) err(`bits needs a number, got a ${typeName(width)}`);
      width = Math.trunc(width);
      if (width < 1) err("bits need a width of at least 1");
      if (n >= (1n << BigInt(width))) err(`${n} does not fit in ${width} bits`);
      size = width;
    }
    return new Bits(n, size);
  }

  const api = {
    VERSION, Interpreter, parse, tokenize, show, typeName, Bits, Verdict, Bond, MemoryStore,
    GatbandhanError, GbnSyntaxError, GbnRuntimeError, BondError,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Gatbandhan = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
