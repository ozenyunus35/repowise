"""Javalin HTTP provider dialect, Java and Kotlin.

Javalin registers a route in three shapes, all read here:

* a verb on the app, Express style: ``app.get("/orders/{id}", ctx -> ...)``
  (v5/v6), where ``app`` is bound to ``Javalin.create(...)`` or typed
  ``Javalin``, or chained straight off ``Javalin.create(...)``;
* a verb on the config's routes (v7): ``config.routes.get("/x", ctx -> ...)``;
* ``ApiBuilder``'s static calls, nested in ``path`` blocks:
  ``path("/api", () -> { get("/x", h); get(h); })``. A verb with no path
  serves the enclosing ``path``, by lambda scope.

A route needs a handler, which is what tells it from a lookup: a path and a
handler argument, or a path and a trailing Kotlin lambda. A dotted verb on any
other receiver (a map, the test client) is not a route, and the bare
``ApiBuilder`` calls are read only in a file that imports it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from repowise.core.ingestion.framework_routes import HTTP_METHODS

from ..base import line_at
from ..calls import FileStrings, code_matches
from ..langs import JAVA, KOTLIN
from ..strings import JAVA_SYNTAX, KOTLIN_SYNTAX, call_arguments, match_paren
from .dialect import build_provider_contract
from .lambda_routes import (
    PrefixScope,
    block_end,
    enclosing_prefix,
    is_call_site,
    trailing_block,
)
from .mounts import compose_prefix

if TYPE_CHECKING:
    from repowise.core.workspace.contracts import Contract

    from ..base import ScanContext

_JAVALIN = "io.javalin"
_API_BUILDER = "io.javalin.apibuilder"

_VERBS = r"get|post|put|patch|delete|head|options"

# `Javalin.create(` / `Javalin.create {`: the head of a chain of routes.
_CREATE_RE = re.compile(r"\bJavalin\s*\.\s*create\s*([({])")
# Names bound to a Javalin app: `app = Javalin.create`, `Javalin app`, `app: Javalin`.
_BINDING_RES = (
    re.compile(r"\b([A-Za-z_]\w*)\s*=\s*Javalin\s*\.\s*create\b"),
    re.compile(r"\bJavalin\s+([A-Za-z_]\w*)\b"),
    re.compile(r"\b([A-Za-z_]\w*)\s*:\s*Javalin\b"),
)
# `app.get(` / `config.routes.get(`.
_DOTTED_RE = re.compile(rf"(?<![\w.])([A-Za-z_]\w*)((?:\s*\.\s*routes)?)\s*\.\s*({_VERBS})\s*\(")
# A link of the chain after `Javalin.create(...)`: `.get(`, `.start(`.
_CHAIN_LINK_RE = re.compile(r"\s*\.\s*([A-Za-z_]\w*)\s*\(")
# ApiBuilder's bare calls: `path("/api", ...)`, `get("/x", h)`, `get(h)`, `get {`.
_BARE_RE = re.compile(rf"(?<![\w.])(path|{_VERBS})\s*([({{])")


def _is_handler(arg: str) -> bool:
    """A lambda or method reference, the handler a path-less verb takes."""
    return "->" in arg or "::" in arg


class JavalinDialect:
    name = "javalin"
    extensions = JAVA | KOTLIN
    requires = (_JAVALIN,)

    def extract(self, ctx: ScanContext) -> list[Contract]:
        content = ctx.content
        syntax = KOTLIN_SYNTAX if ctx.suffix in KOTLIN else JAVA_SYNTAX
        strings = FileStrings(content, syntax)
        routes: dict[int, tuple[str, str]] = {}

        def read(offset: int, verb: str, paren: int, scopes: list[PrefixScope] | None) -> int:
            """Record the route whose argument list opens at *paren*; return where it ends."""
            close = match_paren(content, paren)
            if close < 0:
                return -1
            args = call_arguments(content, paren, close) or []
            block = trailing_block(content, close + 1)
            end = block_end(content, block) if block >= 0 else close
            path = strings.text(args[0]) if args else None
            if path is not None and "${" in path:
                return end
            if path is not None:
                if len(args) < 2 and block < 0:
                    return end  # a path with no handler is a lookup
            elif scopes is None or not (
                (len(args) == 1 and _is_handler(args[0])) or (not args and block >= 0)
            ):
                return end
            prefix = enclosing_prefix(scopes, offset) if scopes is not None else ""
            if prefix is None:
                return end
            full = compose_prefix(prefix, path or "")
            if verb.upper() in HTTP_METHODS and full:
                routes[offset] = (verb.upper(), full)
            return end

        bindings = {m.group(1) for r in _BINDING_RES for m in r.finditer(content)}
        for m in code_matches(ctx, _DOTTED_RE):
            if m.group(2) or m.group(1) in bindings:
                read(m.start(3), m.group(3), m.end() - 1, None)

        for m in code_matches(ctx, _CREATE_RE):
            opener = m.end() - 1
            pos = match_paren(content, opener, closer="}" if m.group(1) == "{" else ")")
            while pos >= 0:
                block = trailing_block(content, pos + 1)
                if block >= 0:
                    pos = block_end(content, block)
                    continue
                link = _CHAIN_LINK_RE.match(content, pos + 1)
                if link is None:
                    break
                if re.fullmatch(_VERBS, link.group(1)):
                    pos = read(link.start(1), link.group(1), link.end() - 1, None)
                else:
                    pos = match_paren(content, link.end() - 1)

        if _API_BUILDER in content:
            scopes: list[PrefixScope] = []
            bare: list[tuple[int, str, int]] = []
            for m in code_matches(ctx, _BARE_RE):
                if not is_call_site(content, m.start()):
                    continue
                if m.group(1) != "path":
                    bare.append((m.start(), m.group(1), m.end() - 1))
                    continue
                if m.group(2) != "(":
                    continue
                close = match_paren(content, m.end() - 1)
                if close < 0:
                    continue
                args = call_arguments(content, m.end() - 1, close) or []
                path = strings.text(args[0]) if args else None
                if path is not None and "${" in path:
                    path = None
                block = trailing_block(content, close + 1)
                if block >= 0:
                    scopes.append(PrefixScope(block, block_end(content, block), path))
                else:
                    scopes.append(PrefixScope(m.end() - 1, close, path))
            for offset, verb, opener in bare:
                if offset in routes:
                    continue
                if content[opener] == "{":
                    # `get { ctx -> }`: Kotlin's trailing handler, no path.
                    prefix = enclosing_prefix(scopes, offset)
                    if prefix and verb.upper() in HTTP_METHODS:
                        routes[offset] = (verb.upper(), prefix)
                    continue
                read(offset, verb, opener, scopes)

        out: list[Contract] = []
        for offset in sorted(routes):
            method, path = routes[offset]
            c = build_provider_contract(
                ctx,
                method=method,
                path_raw=path,
                framework="javalin",
                line=line_at(content, offset),
            )
            if c is not None:
                out.append(c)
        return out
