"""jiyuu's command-line entry point.

Running `jiyuu` with no arguments, or `poetry run jiyuu` during development, invokes the
Typer application defined here.
"""

import typer

from . import __version__

app = typer.Typer()


@app.callback()
def main() -> None:
    """jiyuu's top-level command group.

    Typer collapses an app with exactly one registered command into that command itself, so
    it would be invoked with no name at all. Defining this callback, even though it does
    nothing on its own, keeps every command — `version` today, more as jiyuu grows — invoked
    by name instead.
    """


@app.command()
def version() -> None:
    """Print jiyuu's installed version."""
    print(__version__)
