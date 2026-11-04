# Quality audit

The package version is 0.0.1. `pyproject.toml` owns the version. The architecture and mandatory standards are described in [AGENTS.md](../AGENTS.md).

The quality gates are Ruff lint and formatting, 100% statement and branch test coverage, distribution build and Twine metadata checks. Models, exceptions and provider classes each have focused modules. Test rendering uses a portable licensed font. Diagnostic regressions verify that build output, invalid YAML input and common credential formats are hidden.

Use the [capability matrix](compatibility.md) for supported API operations and limitations. Mock coverage verifies implemented control flow. It does not prove the complete external service schema, store approval or production readiness. A live test must identify the application and testing destination privately and inspect the resulting remote state.
