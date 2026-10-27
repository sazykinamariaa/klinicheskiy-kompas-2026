"""Мини-язык условий для правил из config/*.json.

Правила (alert_rules.json, routing_rules.json, drug_aviandr.json) хранят условия
строками вида ``phq9 >= 20 OR gad7 >= 15``. Этот модуль разбирает такие строки и
считает их по ТРЁХЗНАЧНОЙ логике (Клини): True / False / None (= «неизвестно»).

Ключевое свойство для безопасности: сравнение с неизвестным значением даёт None,
а не False. Поэтому «неизвестно» никогда не превращается в «противопоказаний нет».
Правило срабатывает только при True; None фиксируется как «не вычислено: нет данных».

Клинических значений здесь нет: пороги живут в строках конфигурации.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Set

Tri = Optional[bool]


class ExprError(ValueError):
    """Условие не удалось разобрать (в конфигурации оно написано прозой)."""


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|>=|<=|<|>)
      | (?P<punct>[()\[\],])
      | (?P<word>[^\s()\[\],<>=!]+)
    )""",
    re.X,
)
_KEYWORDS = {"and", "or", "not", "in"}
_BOOL_TRUE = {"yes", "true", "да"}
_BOOL_FALSE = {"no", "false", "нет"}


def tokenize(src: str) -> List[tuple]:
    pos, out = 0, []
    src = src.strip()
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m:
            raise ExprError("неожиданный символ в позиции %d: %r" % (pos, src[pos:pos + 10]))
        pos = m.end()
        if m.group("op"):
            out.append(("op", m.group("op")))
        elif m.group("punct"):
            out.append(("p", m.group("punct")))
        else:
            w = m.group("word")
            if w.lower() in _KEYWORDS:
                out.append(("kw", w.lower()))
            else:
                out.append(("word", w))
    return out


# ---- AST -------------------------------------------------------------------

class Node:
    def ev(self, env: "Env") -> Any:  # pragma: no cover
        raise NotImplementedError


class Ref(Node):
    def __init__(self, name: str):
        self.name = name

    def ev(self, env: "Env") -> Any:
        return env.lookup(self.name)


class Lit(Node):
    def __init__(self, value: Any):
        self.value = value

    def ev(self, env: "Env") -> Any:
        return self.value


class Call(Node):
    def __init__(self, fn: str, args: List[str]):
        self.fn, self.args = fn, args

    def ev(self, env: "Env") -> Any:
        return env.call(self.fn, self.args)


class ListLit(Node):
    def __init__(self, items: List[Any]):
        self.items = items

    def ev(self, env: "Env") -> Any:
        return self.items


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _BOOL_TRUE:
            return True
        if s in _BOOL_FALSE:
            return False
        return s
    return v


def _to_num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    return None


class Cmp(Node):
    def __init__(self, op: str, l: Node, r: Node):
        self.op, self.l, self.r = op, l, r

    def ev(self, env: "Env") -> Tri:
        a, b = self.l.ev(env), self.r.ev(env)
        if self.op == "in":
            if a is None:
                return None
            return _norm(a) in [_norm(x) for x in b]
        if a is None or b is None:
            return None
        if self.op in ("==", "!="):
            eq = _norm(a) == _norm(b)
            return eq if self.op == "==" else (not eq)
        x, y = _to_num(a), _to_num(b)
        if x is None or y is None:
            return None
        return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[self.op]


class Truthy(Node):
    """Голое слово в булевой позиции: факт-флаг или ссылка на правило."""

    def __init__(self, inner: Node):
        self.inner = inner

    def ev(self, env: "Env") -> Tri:
        v = self.inner.ev(env)
        if v is None:
            return None
        v = _norm(v)
        if isinstance(v, bool):
            return v
        return bool(v)


class Not(Node):
    def __init__(self, a: Node):
        self.a = a

    def ev(self, env: "Env") -> Tri:
        v = self.a.ev(env)
        return None if v is None else (not v)


class And(Node):
    def __init__(self, parts: List[Node]):
        self.parts = parts

    def ev(self, env: "Env") -> Tri:
        unknown = False
        for p in self.parts:
            v = p.ev(env)
            if v is False:
                return False
            if v is None:
                unknown = True
        return None if unknown else True


class Or(Node):
    def __init__(self, parts: List[Node]):
        self.parts = parts

    def ev(self, env: "Env") -> Tri:
        unknown = False
        for p in self.parts:
            v = p.ev(env)
            if v is True:
                return True
            if v is None:
                unknown = True
        return None if unknown else False


# ---- Parser ----------------------------------------------------------------

class _Parser:
    def __init__(self, toks: List[tuple]):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self) -> Node:
        n = self.or_()
        if self.i != len(self.t):
            raise ExprError("лишние слова после условия: %r" % (self.t[self.i:],))
        return n

    def or_(self) -> Node:
        parts = [self.and_()]
        while self.peek() == ("kw", "or"):
            self.take()
            parts.append(self.and_())
        return parts[0] if len(parts) == 1 else Or(parts)

    def and_(self) -> Node:
        parts = [self.not_()]
        while self.peek() == ("kw", "and"):
            self.take()
            parts.append(self.not_())
        return parts[0] if len(parts) == 1 else And(parts)

    def not_(self) -> Node:
        if self.peek() == ("kw", "not"):
            self.take()
            return Not(self.not_())
        return self.cmp_()

    def cmp_(self) -> Node:
        if self.peek() == ("p", "("):
            self.take()
            n = self.or_()
            if self.take() != ("p", ")"):
                raise ExprError("нет закрывающей скобки")
            return n
        left = self.primary(lhs=True)
        kind, val = self.peek()
        if kind == "op":
            self.take()
            return Cmp(val, left, self.primary(lhs=False))
        if (kind, val) == ("kw", "in"):
            self.take()
            return Cmp("in", left, self.list_())
        return Truthy(left)

    def list_(self) -> Node:
        if self.take() != ("p", "["):
            raise ExprError("после IN ожидается [список]")
        items, cur = [], []
        while True:
            kind, val = self.take()
            if kind is None:
                raise ExprError("список не закрыт")
            if (kind, val) == ("p", "]"):
                if cur:
                    items.append(" ".join(cur))
                break
            if (kind, val) == ("p", ","):
                items.append(" ".join(cur))
                cur = []
            else:
                cur.append(val)
        return ListLit(items)

    def primary(self, lhs: bool) -> Node:
        kind, val = self.take()
        if kind != "word":
            raise ExprError("ожидалось слово, получено %r" % (val,))
        if self.peek() == ("p", "(") and lhs:
            self.take()
            args, cur = [], []
            while True:
                k, v = self.take()
                if k is None:
                    raise ExprError("вызов функции не закрыт")
                if (k, v) == ("p", ")"):
                    if cur:
                        args.append(" ".join(cur))
                    break
                if (k, v) == ("p", ","):
                    args.append(" ".join(cur))
                    cur = []
                else:
                    cur.append(v)
            return Call(val, args)
        if lhs:
            return Ref(val)
        low = val.lower()
        if low in _BOOL_TRUE:
            return Lit(True)
        if low in _BOOL_FALSE:
            return Lit(False)
        n = _to_num(val)
        return Lit(n if n is not None else val)


def parse(src: str) -> Node:
    return _Parser(tokenize(src)).parse()


# ---- Environment -----------------------------------------------------------

class Env:
    """Окружение вычисления: плоский словарь фактов + ссылки на сработавшие правила."""

    def __init__(
        self,
        facts: Dict[str, Any],
        fired_rules: Optional[Set[str]] = None,
        funcs: Optional[Dict[str, Callable[..., Any]]] = None,
    ):
        self.facts = facts
        self.fired = fired_rules or set()
        self.funcs = funcs or {}
        self.missing: Set[str] = set()

    _RULE_RE = re.compile(r"^[RMD]-(?:[A-Z]+-)?(?:\d+|\*)$")

    def lookup(self, name: str) -> Any:
        if self._RULE_RE.match(name):
            if name.endswith("*"):
                prefix = name[:-1]
                return any(r.startswith(prefix) for r in self.fired)
            return name in self.fired
        v = self.facts.get(name)
        if v is None:
            self.missing.add(name)
        return v

    def call(self, fn: str, args: List[str]) -> Any:
        f = self.funcs.get(fn)
        if f is None:
            raise ExprError("неизвестная функция %s()" % fn)
        return f(self, *args)


def evaluate(src_or_node, env: Env) -> Tri:
    node = parse(src_or_node) if isinstance(src_or_node, str) else src_or_node
    v = node.ev(env)
    if v is None:
        return None
    v = _norm(v)
    return bool(v) if not isinstance(v, bool) else v


def is_parsable(src: str) -> bool:
    try:
        parse(src)
        return True
    except ExprError:
        return False


def collect_refs(node: Node) -> Set[str]:
    """Имена фактов, на которые ссылается выражение (для проверки исполнимости)."""
    out: Set[str] = set()

    def walk(n: Node) -> None:
        if isinstance(n, Ref):
            if not Env._RULE_RE.match(n.name):
                out.add(n.name)
        elif isinstance(n, Cmp):
            walk(n.l)
            walk(n.r)
        elif isinstance(n, (Truthy,)):
            walk(n.inner)
        elif isinstance(n, Not):
            walk(n.a)
        elif isinstance(n, (And, Or)):
            for p in n.parts:
                walk(p)

    walk(node)
    return out
