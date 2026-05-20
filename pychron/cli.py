import os

import typer

from pychron.cli_profiles import PROFILES, available_profile_names
from pychron.install_bootstrap import bootstrap_runtime_root, normalize_root
from pychron.install_support import (
    build_install_plan,
    export_config_bundle,
    import_config_bundle,
)
from pychron.starter_bundles import BUNDLES, available_bundle_names

DEFAULT_ROOT = "~/Pychron"

app = typer.Typer(
    help="Pychron installation and environment utilities.",
    no_args_is_help=True,
    add_completion=False,
)


def _normalize_profiles(profiles):
    return [profile for profile in (profiles or []) if profile]


def _normalize_bundles(bundles):
    return [bundle for bundle in (bundles or []) if bundle]


@app.command("bundles")
def bundles(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show bundle descriptions, versions, and included profiles.",
    ),
):
    for name in available_bundle_names():
        bundle = BUNDLES[name]
        if verbose:
            details = "{} version={} profiles={}".format(
                bundle.description, bundle.version, ",".join(bundle.profiles)
            )
            typer.echo("{}: {}".format(name, details))
            for note in bundle.notes:
                typer.echo("  note: {}".format(note))
        else:
            typer.echo(name)


@app.command("profiles")
def profiles(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show profile descriptions and included profiles.",
    ),
):
    for name in available_profile_names():
        if verbose:
            spec = PROFILES[name]
            details = spec.description
            if spec.includes:
                details = "{} includes={}".format(details, ",".join(spec.includes))
            typer.echo("{}: {}".format(name, details))
        else:
            typer.echo(name)


@app.command("install-plan")
def install_plan(
    root: str = typer.Option(
        DEFAULT_ROOT,
        "--root",
        help="Pychron data/config root to initialize.",
    ),
    bundles: list[str] = typer.Option(
        None,
        "--bundle",
        help="Build an install plan for one or more starter bundles.",
    ),
    profiles: list[str] = typer.Option(
        None,
        "--profile",
        help="Build an install plan for one or more profiles.",
    ),
):
    bundles = _normalize_bundles(bundles)
    profiles = _normalize_profiles(profiles)
    plan = build_install_plan(profiles=profiles, bundles=bundles, root=normalize_root(root))
    typer.echo("Platform: {}".format(plan.platform_name))
    if plan.requested_bundles:
        typer.echo("Starter bundles: {}".format(", ".join(plan.requested_bundles)))
    if plan.requested_profiles:
        typer.echo("Requested profiles: {}".format(", ".join(plan.requested_profiles)))
        typer.echo("Resolved profiles: {}".format(", ".join(plan.resolved_profiles)))
    if plan.extras:
        typer.echo("Recommended extras: {}".format(", ".join(plan.extras)))

    typer.echo("")
    typer.echo("Commands")
    for command in plan.commands:
        typer.echo(" - {}".format(command))

    typer.echo("")
    typer.echo("Notes")
    for note in plan.notes:
        typer.echo(" - {}".format(note))


@app.command("bootstrap")
def bootstrap(
    root: str = typer.Option(
        DEFAULT_ROOT,
        "--root",
        help="Pychron data/config root to initialize.",
    ),
    write_defaults: bool = typer.Option(
        True,
        "--write-defaults/--no-write-defaults",
        help="Write default initialization and UI config files.",
    ),
    bundles: list[str] = typer.Option(
        None,
        "--bundle",
        help="Apply one or more versioned starter bundles.",
    ),
    profiles: list[str] = typer.Option(
        None,
        "--profile",
        help="Apply one or more composable bootstrap profiles.",
    ),
    source_profiles: list[str] = typer.Option(
        None,
        "--source-profile",
        help="Copy one or more site/instrument example bundles from external source trees.",
    ),
    setupfiles_source: str = typer.Option(
        None,
        "--setupfiles-source",
        help="External directory containing setupfiles example bundles.",
    ),
    scripts_source: str = typer.Option(
        None,
        "--scripts-source",
        help="External directory containing scripts example bundles.",
    ),
    overwrite_source_files: bool = typer.Option(
        False,
        "--overwrite-source-files/--no-overwrite-source-files",
        help="Allow external source bundles to overwrite existing files in the target root.",
    ),
) -> None:
    bundles = _normalize_bundles(bundles)
    profiles = _normalize_profiles(profiles)
    source_profiles = _normalize_profiles(source_profiles)
    root, created, merged = bootstrap_runtime_root(
        root,
        write_defaults=write_defaults,
        profiles=profiles,
        bundles=bundles,
        source_profiles=source_profiles,
        setupfiles_source=setupfiles_source,
        scripts_source=scripts_source,
        overwrite_source_files=overwrite_source_files,
    )
    typer.echo("Bootstrapped Pychron root: {}".format(root))
    for item in created:
        typer.echo(" - {}".format(item))

    if write_defaults:
        typer.echo("Default configuration files were written where missing.")

    if bundles:
        typer.echo("Applied bundles: {}".format(", ".join(bundles)))
    if merged.resolved:
        typer.echo("Applied profiles: {}".format(", ".join(merged.resolved)))
    if source_profiles:
        typer.echo("Applied source bundles: {}".format(", ".join(source_profiles)))


@app.command("export-config")
def export_config(
    root: str = typer.Option(
        DEFAULT_ROOT,
        "--root",
        help="Pychron data/config root to export.",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="Zip archive path to write.",
    ),
    include_appdata: bool = typer.Option(
        False,
        "--include-appdata/--no-include-appdata",
        help="Include .appdata in the exported bundle.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite/--no-overwrite",
        help="Overwrite an existing archive.",
    ),
):
    exported = export_config_bundle(
        normalize_root(root),
        output,
        include_appdata=include_appdata,
        overwrite=overwrite,
    )
    typer.echo("Exported configuration bundle: {}".format(os.path.expanduser(output)))
    for item in exported:
        typer.echo(" - {}".format(item))


@app.command("import-config")
def import_config(
    root: str = typer.Option(
        DEFAULT_ROOT,
        "--root",
        help="Pychron data/config root to import into.",
    ),
    archive: str = typer.Option(
        ...,
        "--archive",
        help="Zip archive path to import.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite/--no-overwrite",
        help="Allow imported files to overwrite existing files.",
    ),
):
    extracted, skipped = import_config_bundle(normalize_root(root), archive, overwrite=overwrite)
    typer.echo("Imported configuration bundle: {}".format(os.path.expanduser(archive)))
    typer.echo("Extracted {} files".format(len(extracted)))
    for item in extracted:
        typer.echo(" - {}".format(item))
    if skipped:
        typer.echo("Skipped {} files".format(len(skipped)))
        for item in skipped:
            typer.echo(" - {}".format(item))


def main() -> None:
    app()


def bootstrap_main() -> None:
    app(["bootstrap"])


if __name__ == "__main__":
    main()
