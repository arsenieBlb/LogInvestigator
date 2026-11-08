# Implementation decisions

## Runtime and dependencies

Checked official documentation and PyPI stable-release metadata before pinning on
2026-11-07. Tested CPython **3.12.10**, SQLite **3.49.1**, MCP **2.3.0**, Pydantic
**2.14.3**, HTTPX **0.28.1**, pytest **9.2.0**, pytest-asyncio **1.4.1.post1**,
Ruff **0.17.4**, mypy **2.4.1**, and uv **0.13.7**. `uv.lock` records all transitive
versions and hashes; `pyproject.toml` pins direct runtime and development dependencies.
Python support is declared 3.12–3.14; other minors are CI targets, not locally tested claims.

MCP 2.3 uses `MCPServer` and `Client`, rather than copying pre-v2 `FastMCP` examples.
The local transport is stdio and actual subprocess integration tests prove discovery,
tools, bounds, errors, cancellation and shutdown. MCP diagnostics go to stderr.

Use argparse and Python standard-library native demo services to keep the package
small. Use a SQLite keyword/FTS baseline before considering embeddings. Input rejection
is per record; all accepted records plus the import summary commit in one transaction.
A fatal read/size/storage failure commits no partial import. Reports are immutable
new files; feedback is a separately versioned record with a digest of the original.

The provider boundary supports tool calls and structured responses without requiring
an OpenAI SDK. The real adapter uses OpenRouter's documented Chat Completions API,
fixed endpoint, stable `openai/gpt-4.1-mini` default, deny-data-collection routing and
strict final JSON schema. The agent cannot choose arbitrary endpoints. Only synthetic
generated data was used for live checks. Secrets were neither printed nor saved.

## Conditional decisions

| Condition | Applied? | Handling |
|---|---|---|
| No usable live credential/local model | Credential present; usability checked live | Adapter and offline path complete regardless; exact live outcome in completion record. |
| Credentials/local model available | Yes: existing `OPENROUTER_API_KEY` | Bounded live smoke and selected cases attempted; no secret values recorded. |
| SQLite FTS5 unavailable | No locally | Explicit probe succeeded; forced-unavailable and keyword fallback tests pass. |
| Poor keyword issue retrieval | No recorded need for embeddings | Small public KB query tests pass; no embedding model or external index added. Broader relevance is unmeasured. |
| Browser interface specifically required | No | CLI plus Markdown/JSON is the requested sufficient interface. |
| FrameGuard captures available and selected | No | No import adapter; unrelated projects are not dependencies. |
| Other-project logs supplied | No | Public JSONL contract available; no runtime/source imports. |
| Remote MCP access required | No | Local stdio only; authentication/network transport deferred until a real requirement. |
| Docker unavailable | No: daemon 29.7.2 responds | Native process demo chosen; Compose optional in brief and not implemented or claimed tested. |

## Development feedback and evaluation

Use 10 development and 6 held-out neutral-ID cases. Ground truth is read only by the
scorer after investigation, never supplied to the provider or included in the KB.
Synthetic fixture replay is labelled separately from actual native-service runs and
live-provider investigations. Case-level results remain saved, including failures.

The initial development run exposed synthetic `WARN` severities rejected by the
documented `WARNING` schema. Saved original inputs, report and implementer review
under `artifacts/development-before` and `artifacts/reviews` preserve this history.
The generator correction and visible ingestion counts constitute the documented
development feedback change. This is fixture correctness, not evidence of improved
model reasoning. No diagnosis rule is tuned to held-out results.

Automatic diagnosis text matching and uncertainty checks are proxies. Independent
human semantic diagnosis/unsupported-claim scores remain unfilled until reviewed;
AI implementer review is labelled separately. No calibrated confidence percentages,
unmeasured speedups or unsupported quality claims are reported.

## Deferred scope

Automatic remediation, agent shell execution, Kubernetes, runtime multi-agent
coordination, public hosting, a large dashboard, custom training and vector storage
are intentionally deferred. Parallel implementation assistance does not add
multi-agent coordination to the shipped application.

## Official references consulted

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP stdio server guidance](https://modelcontextprotocol.io/docs/develop/build-server)
- [Python SQLite](https://docs.python.org/3.14/library/sqlite3.html)
- [SQLite FTS5](https://www.sqlite.org/fts5.html)
- [Pydantic](https://docs.pydantic.dev/latest/)
- [OpenRouter tools](https://openrouter.ai/docs/guides/features/tool-calling)
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [uv locking](https://docs.astral.sh/uv/concepts/projects/locking-and-syncing/)
- [Ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy.readthedocs.io/en/stable/), [pytest](https://docs.pytest.org/en/stable/)
