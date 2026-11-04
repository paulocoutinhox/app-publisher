import json
import shutil
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from app_publisher.config import load_project
from app_publisher.core.credential_helper import CredentialHelper
from app_publisher.core.diagnostics import diagnose, save_report
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.sync_plan import apply_plan, generate_plan, load_plan, store_plan
from app_publisher.core.workflow_runner import WorkflowRunner
from app_publisher.errors.app_publisher_error import AppPublisherError
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.screenshots.screenshot_capture import ScreenshotCapture
from app_publisher.toolchain.doctor import inspect_tools
from app_publisher.toolchain.environment_doctor import EnvironmentDoctor

app = typer.Typer(
    help="Synchronize Apple App Store, Google Play, and Firebase projects using YAML.",
    no_args_is_help=True,
    invoke_without_command=True,
)
shots_app = typer.Typer(help="Screenshot capture and validation utilities.")
app.add_typer(shots_app, name="screenshots")
console = Console()


@app.callback()
def application_options(version: bool = typer.Option(False, "--version", is_eager=True)) -> None:
    if version:
        console.print(distribution_version("app-publisher"))
        raise typer.Exit()


def open_engine(config: Path) -> PublicationEngine:
    return PublicationEngine(load_project(config), config)


def show_changes(changes: list[str]) -> None:
    for change in changes:
        console.print(f"[cyan]•[/cyan] {change}")
    console.print(f"[green]{len(changes)} operation(s)[/green]")


@app.command()
def validate(config: Path) -> None:
    engine = open_engine(config)
    engine.validate()
    console.print("[green]Configuration and local files are valid.[/green]")


@app.command()
def doctor(config: Path, capture: bool = False) -> None:
    engine = open_engine(config)
    results = inspect_tools(engine.project.apple is not None, engine.project.google is not None, capture)
    if engine.project.apple and any(
        locale.apple and locale.apple.app_previews for locale in engine.project.locales.values()
    ):
        results["ffprobe"] = shutil.which("ffprobe") is not None
    for tool, installed in results.items():
        console.print(f"{'[green]OK[/green]' if installed else '[red]MISSING[/red]'} {tool}")
    if not all(results.values()):
        raise typer.Exit(1)


@app.command("doctor-full")
def doctor_full(config: Path) -> None:
    engine = open_engine(config)
    checks = EnvironmentDoctor().inspect(engine.project, engine.directory)
    for check in checks:
        color = "green" if check.status == "OK" else "yellow" if check.status == "UNVERIFIED" else "red"
        console.print(f"[{color}]{check.status}[/{color}] {check.name}: {check.detail}")
    if any(check.status == "MISSING" for check in checks):
        raise typer.Exit(1)


@app.command()
def diff(config: Path, provider: Literal["all", "apple", "google", "firebase"] = "all") -> None:
    show_changes(open_engine(config).synchronize(apply=False, provider=provider))


@app.command()
def sync(
    config: Path,
    provider: Literal["all", "apple", "google", "firebase"] = "all",
    apply: bool = typer.Option(
        False, "--apply", help="Perform remote writes. Without this flag, show a dry run."
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Write a structured JSON result without overwriting existing files."
    ),
) -> None:
    try:
        changes = open_engine(config).synchronize(apply=apply, provider=provider)
    except AppPublisherError as error:
        if report is not None:
            save_report(report, diagnose(error, action="sync" if apply else "diff", provider=provider))
        raise
    if report is not None:
        save_report(
            report,
            {
                "status": "success",
                "action": "sync" if apply else "diff",
                "provider": provider,
                "changes": changes,
                "cross_provider_atomic": False,
            },
        )
    show_changes(changes)


@app.command("plan")
def plan(
    config: Path,
    output: Path = typer.Option(Path("app-publisher-plan.json"), "--output"),
    provider: Literal["all", "apple", "google", "firebase"] = "all",
) -> None:
    saved = generate_plan(open_engine(config), provider=provider)
    store_plan(saved, output)
    console.print(f"[green]Saved plan:[/green] {output} ({len(saved['changes'])} changes)")


@app.command("apply-plan")
def apply_saved_plan(
    config: Path,
    plan_file: Path = typer.Option(Path("app-publisher-plan.json"), "--plan"),
    apply: bool = typer.Option(False, "--apply", help="Apply the verified plan. Otherwise preview it."),
    report: Path | None = typer.Option(None, "--report"),
) -> None:
    try:
        changes = apply_plan(open_engine(config), load_plan(plan_file), apply=apply)
    except AppPublisherError as error:
        if report is not None:
            save_report(report, diagnose(error, action="apply-plan", provider="from-plan"))
        raise
    if report is not None:
        save_report(
            report,
            {"status": "success", "action": "apply-plan", "changes": changes, "cross_provider_atomic": False},
        )
    show_changes(changes)


@app.command()
def release(
    config: Path,
    provider: Literal["all", "apple", "google"] = "all",
    apply: bool = typer.Option(False, "--apply", help="Upload artifacts and update store releases."),
) -> None:
    show_changes(open_engine(config).release(apply=apply, provider=provider))


@app.command("delete-listings")
def delete_listings(
    config: Path,
    apply: bool = typer.Option(False, "--apply", help="Delete only confirmed Google localized listings."),
) -> None:
    show_changes(open_engine(config).delete_listings(apply=apply))


@app.command("reply-reviews")
def reply_reviews(
    config: Path,
    provider: Literal["all", "apple", "google"] = "all",
    apply: bool = typer.Option(False, "--apply", help="Publish only explicitly confirmed review replies."),
) -> None:
    show_changes(open_engine(config).reply_reviews(apply=apply, provider=provider))


@app.command("reviews")
def reviews(config: Path, provider: Literal["all", "apple", "google"] = "all") -> None:
    console.print_json(json.dumps(open_engine(config).list_reviews(provider=provider)))


@app.command("testers")
def testers(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Synchronize Google Play testing Google Groups without publishing a release."
    ),
) -> None:
    show_changes(open_engine(config).testers(apply=apply))


@app.command("delete-purchase-options")
def delete_purchase_options(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Delete explicitly confirmed Google Play purchase options."
    ),
) -> None:
    show_changes(open_engine(config).delete_purchase_options(apply=apply))


@app.command("delete-offers")
def delete_offers(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Delete explicitly confirmed Google Play one-time purchase offers."
    ),
) -> None:
    show_changes(open_engine(config).delete_offers(apply=apply))


@app.command("workflow")
def workflow(
    config: Path,
    apply: bool = typer.Option(False, "--apply", help="Execute the declared publishing stages."),
    resume: bool = typer.Option(False, "--resume", help="Resume without repeating completed stages."),
    retry_failed: bool = typer.Option(
        False, "--retry-failed", help="Retry a partial stage after verifying remote state."
    ),
) -> None:
    show_changes(
        WorkflowRunner(open_engine(config)).run(apply=apply, resume=resume, retry_failed=retry_failed)
    )


@app.command("wait")
def wait(config: Path, timeout: int = typer.Option(900, min=1, max=7200)) -> None:
    show_changes(open_engine(config).wait(timeout=timeout))


@app.command("symbols")
def symbols(
    config: Path,
    provider: Literal["all", "apple", "google"] = "all",
    apply: bool = typer.Option(False, "--apply", help="Upload verified Crashlytics symbols."),
) -> None:
    show_changes(open_engine(config).symbols(apply=apply, provider=provider))


@app.command("schema")
def schema() -> None:
    from app_publisher.models.project_config import ProjectConfig

    console.print_json(json.dumps(ProjectConfig.model_json_schema()))


@app.command("build")
def build(
    config: Path,
    provider: Literal["all", "apple", "google"] = "all",
    apply: bool = typer.Option(False, "--apply", help="Execute native build tools."),
) -> None:
    show_changes(open_engine(config).build(apply=apply, provider=provider))


@app.command("review")
def review(
    config: Path, apply: bool = typer.Option(False, "--apply", help="Submit Apple versions for review.")
) -> None:
    show_changes(open_engine(config).review(apply=apply))


@app.command("review-products")
def review_products(
    config: Path,
    platform: Literal["IOS", "MAC_OS", "TV_OS", "VISION_OS"] = "IOS",
    first_purchase_review_completed: bool = typer.Option(
        False,
        "--first-purchase-review-completed",
        help="Confirm Apple's mandatory first in-app purchase submission was already completed manually.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Submit editable product metadata versions for Apple review."
    ),
) -> None:
    show_changes(
        open_engine(config).review_products(
            apply=apply, platform=platform, first_purchase_review_completed=first_purchase_review_completed
        )
    )


@app.command("signing")
def signing(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Create declared Apple profiles and download signing artifacts."
    ),
) -> None:
    show_changes(open_engine(config).signing(apply=apply))


@app.command("beta")
def beta(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Synchronize TestFlight groups, testers, invitations and build distribution."
    ),
) -> None:
    show_changes(open_engine(config).beta(apply=apply))


@shots_app.command("render")
def screenshots_render(
    config: Path, apply: bool = typer.Option(False, "--apply", help="Generate labeled store screenshots.")
) -> None:
    show_changes(open_engine(config).render_screenshots(apply=apply))


@shots_app.command("batch")
def screenshots_batch(
    config: Path,
    apply: bool = typer.Option(False, "--apply", help="Navigate scenarios and capture device screenshots."),
) -> None:
    show_changes(open_engine(config).screenshots(apply=apply))


@app.command("launch")
def launch(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Release an approved manual version or enable phased release."
    ),
) -> None:
    show_changes(open_engine(config).launch(apply=apply))


@app.command("privacy-manifest")
def privacy_manifest(
    config: Path,
    apply: bool = typer.Option(
        False, "--apply", help="Write the declared Apple PrivacyInfo.xcprivacy manifest."
    ),
) -> None:
    show_changes(open_engine(config).privacy(apply=apply))


@app.command("availability")
def availability(config: Path, provider: Literal["all", "apple", "google"] = "all") -> None:
    show_changes(open_engine(config).availability(provider))


@app.command()
def status(config: Path, provider: Literal["all", "apple", "google"] = "all") -> None:
    console.print_json(json.dumps(open_engine(config).status(provider)))


@app.command("inspect")
def inspect(config: Path, provider: Literal["all", "apple", "google"] = "all") -> None:
    console.print_json(json.dumps(open_engine(config).inspect(provider)))


@app.command()
def devices(config: Path) -> None:
    engine = open_engine(config)
    if engine.project.apple is None:
        raise AppPublisherError("Apple App Store is not configured")
    publisher = engine.apple()
    try:
        reference = AppleAssetLibrary(publisher.api, publisher.config.app_id).reference_data()
        groups = [
            {
                "id": item["placementProfileGroupId"],
                "display_class": item["displayClassId"],
                "platform": item["platform"],
            }
            for item in reference["placementProfileGroups"]
        ]
        console.print_json(json.dumps({"apple_placement_groups": groups}))
    finally:
        publisher.api.close()


@shots_app.command("validate")
def screenshots_validate(config: Path) -> None:
    engine = open_engine(config)
    engine.validate()
    console.print("[green]All configured screenshots passed local integrity checks.[/green]")


@shots_app.command("capture")
def screenshots_capture(
    platform: Literal["ios", "tvos", "watchos", "visionos", "macos", "android"], target: str, output: Path
) -> None:
    saved = ScreenshotCapture().capture(platform, target, output)
    console.print(f"[green]Saved screenshot: {saved}[/green]")


def main() -> None:
    try:
        app()
    except AppPublisherError as error:
        console.print(
            f"[red]Error:[/red] {CredentialHelper.redact(str(error))}", highlight=False, markup=False
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
