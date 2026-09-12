# Publishing to the MCP registry

`server.json` in the repository root is the entry. It is validated against the
published schema; check it after editing:

```bash
python3 -c "import json,jsonschema,urllib.request as u; \
  jsonschema.validate(json.load(open('server.json')), \
  json.load(u.urlopen('https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json'))); \
  print('ok')"
```

Two things about it are easy to get wrong and expensive to get wrong.

**The PyPI package is `echo-mem`, not `echo-memory`.** `echo-memory` on PyPI
belongs to Textstone Labs, a different company shipping a product with the same
name since March 2026. Publishing that identifier would send every installer to
somebody else's SDK.

**`description` has a 100 character limit.** The schema enforces it and the
publish fails rather than truncating.

## Publishing

```bash
# one-time: install the publisher
brew install mcp-publisher     # or download from the registry's releases

mcp-publisher login github     # proves the io.github.ayushcodes10/* namespace
mcp-publisher publish
```

The registry verifies PyPI ownership by looking for `mcp-name:
io.github.ayushcodes10/echo-mem` in the package description, which is the line
at the bottom of `README.md`. It has to be in a *released* distribution, so a
release must go out after that line was added before the publish will pass.

Several downstream directories ingest the registry on a schedule, so publishing
here propagates to listings that would otherwise each need a manual submission.
