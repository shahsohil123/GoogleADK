# Resources Folder

This folder stores static resources, config files, and other assets that should **not** be scanned by ADK as agents.

## Why it's not scanned
- No `__init__.py` file (not a Python package)
- ADK only scans for Python agent packages
- Safe place for non-agent code and assets

## Use cases
- Configuration files
- Static assets
- Data files
- Helper scripts
- Documentation
