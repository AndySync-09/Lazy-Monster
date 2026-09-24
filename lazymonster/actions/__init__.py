import os


def make_executor(apps, dry_run: bool = False, writer=None):
    if dry_run:
        from .dryrun import DryRunExecutor
        return DryRunExecutor(apps, writer)
    if os.name == "nt":
        from .windows import WindowsExecutor
        return WindowsExecutor(apps, writer)
    from .posix import PosixExecutor                    # macOS and Linux (first cut)
    return PosixExecutor(apps, writer)
