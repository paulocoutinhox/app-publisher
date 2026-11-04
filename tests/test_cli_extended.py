from pathlib import Path
from types import SimpleNamespace

from app_publisher import cli


def test_extended_cli_functions(monkeypatch):
    calls = []
    engine = SimpleNamespace(
        build=lambda **kwargs: ["build"],
        review=lambda **kwargs: ["review"],
        beta=lambda **kwargs: ["beta"],
        screenshots=lambda **kwargs: ["batch"],
        render_screenshots=lambda **kwargs: ["render"],
    )
    monkeypatch.setattr(cli, "open_engine", lambda config: engine)
    monkeypatch.setattr(cli, "show_changes", lambda changes: calls.extend(changes))
    cli.build(Path("app.yaml"), provider="apple", apply=False)
    cli.review(Path("app.yaml"), apply=False)
    cli.beta(Path("app.yaml"), apply=False)
    cli.screenshots_batch(Path("app.yaml"), apply=False)
    cli.screenshots_render(Path("app.yaml"), apply=False)
    assert calls == ["build", "review", "beta", "batch", "render"]
