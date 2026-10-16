# Installation

We recommend [uv](https://docs.astral.sh/uv/) to create environments and sync
dependencies for **journal_club**.

## Requirements

- **Python 3.13 or newer** (`requires-python` in `pyproject.toml`)
- Linux, macOS, or Windows

## Install from a checkout (recommended)

```bash
git clone https://github.com/Leuven-Gravity-Institute/journal-club.git
cd journal-club

uv sync --extra dev --extra docs --extra test
```

Activate the virtualenv if you prefer not to prefix commands with `uv run`:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

Install git hooks:

```bash
uv run prek install
```

## Install from PyPI

The template repository is primarily meant to be copied; a PyPI name may still
point at placeholder metadata. If a published distribution exists for your use
case:

```bash
uv pip install journal_club
```

Optional extras:

```bash
uv pip install "journal_club[dev]"
uv pip install "journal_club[docs]"
```

## Verify the CLI

```bash
uv run journal_club --help
```

Or import the package:

```bash
uv run python -c "import journal_club; print(journal_club.__version__)"
```

## Core runtime dependency

- **Typer** — command-line interface

## Getting help

1. [Troubleshooting](../development/troubleshooting.md)
2. [Issues](https://github.com/Leuven-Gravity-Institute/journal-club/issues)
