"""Ktor server HTTP provider dialect — ``routing { route("/api") { get("{id}") { } } }``.

A Ktor route is a bare call with a trailing handler block: ``get("/x") { }``,
or ``get { }`` with no path, which serves the enclosing route. ``route("/p")``
blocks nest prefixes, and the prefix a verb serves under is every ``route``
block around it, by lambda scope. A path-less verb outside any ``route`` serves
``/`` when it sits directly in ``routing { }``; inside an extension function
such as ``fun Route.users()`` its prefix is wherever that function is called,
which this file cannot see, so it is refused.

The receiver is what keeps the Ktor client out: a request is a dotted call on
a client value (``client.get("/x")``), a route is a bare call on the implicit
``Route`` receiver. Ktor's typed ``get<Resource> { }`` names no path and is
skipped by the same shape, as is a ``route(path, HttpMethod.X)`` block whose
verb sits in an inner ``handle { }``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from repowise.core.ingestion.framework_routes import HTTP_METHODS

from ..base import line_at
from ..calls import FileStrings, code_matches
from ..langs import KOTLIN
from ..strings import KOTLIN_SYNTAX, call_arguments, match_paren
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

# The routing DSL's package. A file that never names it declares no routes.
_KTOR_ROUTING = "io.ktor.server.routing"

# A bare call of the DSL: `routing {`, `route("/p") {`, `get("/x") {`, `get {`.
# The look-behind drops a dotted call, which is a client request or a map read.
_CALL_RE = re.compile(r"(?<![\w.])(routing|route|get|post|put|patch|delete|head|options)\s*([({])")


class KtorServerDialect:
    name = "ktor-server"
    extensions = KOTLIN
    requires = (_KTOR_ROUTING,)

    def extract(self, ctx: ScanContext) -> list[Contract]:
        content = ctx.content
        strings = FileStrings(content, KOTLIN_SYNTAX)
        routing: list[PrefixScope] = []
        scopes: list[PrefixScope] = []
        verbs: list[tuple[int, str, str | None]] = []
        for m in code_matches(ctx, _CALL_RE):
            if not is_call_site(content, m.start()):
                continue
            name = m.group(1)
            if m.group(2) == "(":
                close = match_paren(content, m.end() - 1)
                if close < 0:
                    continue
                args = call_arguments(content, m.end() - 1, close) or []
                block = trailing_block(content, close + 1)
            else:
                args, block = [], m.end() - 1
            if block < 0:
                continue  # a route always opens its handler or nested block
            end = block_end(content, block)
            if end < 0:
                continue
            path = strings.text(args[0]) if args else ""
            if path is not None and "${" in path:
                path = None
            if name == "routing":
                routing.append(PrefixScope(block, end, ""))
            elif name == "route":
                scopes.append(PrefixScope(block, end, path))
            elif len(args) <= 1:
                verbs.append((m.start(), name.upper(), path))

        out: list[Contract] = []
        for offset, method, path in verbs:
            if method not in HTTP_METHODS or path is None:
                continue
            prefix = enclosing_prefix(scopes, offset)
            if prefix is None:
                continue
            if not prefix and not path:
                # `get { }` straight under `routing { }` serves the root.
                if not any(s.start < offset < s.end for s in routing):
                    continue
                path = "/"
            c = build_provider_contract(
                ctx,
                method=method,
                path_raw=compose_prefix(prefix, path),
                framework="ktor",
                line=line_at(content, offset),
            )
            if c is not None:
                out.append(c)
        return out
