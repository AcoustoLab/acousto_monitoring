AI-based Vibroacoustic Machinery State Monitoring and Diagnostics System


# Tech Stack:

# Installation:

First, install `uv` package manager.
Then in the project root, create a virtual environment and install the dependencies:
```bash
uv sync
```

# Development:

Create an issue, then create a brunch with the name `TSKTM_DGNSTCS-<N>` and start working on the issue.
After you are done, create a pull request to the `main` branch.

## Before commiting:
```bash
uv run ruff format
uv run ruff check
uv run pyright
uv run pytest
```
or
```bash
uv run pre-commit run --all-files
```

# Project Structure:
README.md - general description of the project
/src - folder for code placement
/docs - folder for documents placement
/configs - folder for config files placement
/tests - folder for tests placement
/assets - folder for resources placement
