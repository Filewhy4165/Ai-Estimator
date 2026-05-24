# Dependency Management

## Files

- `requirements/runtime.in`: editable runtime intent
- `requirements/dev.in`: editable developer intent
- `requirements/runtime.lock.txt`: pinned runtime install set
- `requirements/dev.lock.txt`: pinned developer install set

## Local setup

```powershell
.\scripts\setup-dev.ps1
```

## Reproducible setup (recommended for team/CI)

```powershell
.\scripts\setup-dev.ps1 -UseLockFiles
```

## Private mirror setup

Project-scoped mirror (inside virtual environment):

```powershell
.\scripts\setup-dev.ps1 -IndexUrl "https://packages.example.com/pypi/simple" -UseLockFiles
```

Persistent user-level mirror:

```powershell
python -m pip config --user set global.index-url "https://packages.example.com/pypi/simple"
```

Check active pip configuration:

```powershell
python -m pip config debug
python -m pip config list
```

Windows config template location:

- `%APPDATA%\pip\pip.ini`

Use `config/pip.ini.example` as a starting template.

## Upgrading dependencies intentionally

```powershell
.\scripts\update-locks.ps1
```

Commit updated lock files after verification.

