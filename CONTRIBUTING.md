# Contributing

Start with [`AGENTS.md`](AGENTS.md). Pull requests must preserve strict YAML validation, safe dry-run defaults and explicit remote state handling. Write a failing test before adding a new provider action. Update the capability matrix for every feature and describe whether it was unit-mocked or real-store verified.

```bash
make install
make lint
make coverage
make build
make check
```
