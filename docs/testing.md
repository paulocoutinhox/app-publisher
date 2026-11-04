# Testing

Run `make lint`, `make coverage`, `make build` and `make check`. Ruff validates imports, lint and formatting. Coverage requires 100% statements and branches. All HTTP calls are mocked in tests. pytest-socket disables network sockets, so an accidentally unmocked request fails locally and in CI. Native commands use controlled subprocess runners.

The screenshot-rendering test uses the bundled `tests/fixtures/poppins-regular.ttf` under the accompanying SIL Open Font License. It does not depend on system fonts and must run on Linux, macOS and Windows without skipping.

Test application identities are synthetic. Do not add real credential files, signing keys, production account details or captured authenticated traffic to fixtures. Build-output suppression, invalid YAML diagnostics, credential redaction, edit cleanup and track replacement must retain regression coverage.

Live acceptance is a separate operation against an authorized store application. Authentication success does not prove that a binary, a product or review submission will be accepted. Record the actual operation and response without secrets. Broader mocked capabilities must remain identified as such in the capability matrix.

Continuous hosted checks run the full suite, coverage and packaging on ubuntu-latest and windows-latest with Python 3.11, 3.13 and 3.14. Run the Test workflow manually with `include-macos` enabled to add macos-15-intel on all three Python versions. Local macOS ARM64 validation uses the same commands. The mocked Apple and Google API cases run on every operating system without vendor SDKs or store credentials.
