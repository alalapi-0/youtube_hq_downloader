"""Publish the saved downloader record counts as one standard Hub snapshot.

The Hub runs this reader with its own environment and passes `--hub-root`. It does
not install dependencies, refresh tokens, print URLs, or replace the downloader
scripts. It only reads the registered saved-tool files and writes the ignored
`.hub/status.json`. It never opens credential files.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ID = "youtube-hq-downloader"
ADAPTER = "downloader"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(argv)

    hub_root = args.hub_root.resolve(strict=True)
    project_root = args.project_root.absolute()
    if project_root.is_symlink() or not project_root.is_dir():
        return 2
    project_root = project_root.resolve(strict=True)
    sys.path.insert(0, str(hub_root / "src"))

    from hub.connection_sources import SourceResolver
    from hub.metric_collect import validate_metric_source_config
    from hub.metric_export import export_metric_snapshot
    from hub.metric_saved_tools import collect_downloader
    from hub.metric_sources import read_structured
    from hub.metrics import utcnow

    observed_at = utcnow()
    resolver = SourceResolver(hub_root, clock=lambda: observed_at)
    registered = Path(resolver.projects[PROJECT_ID]["root_path"]).expanduser()
    if registered.resolve(strict=True) != project_root:
        return 2
    config, _ = read_structured(hub_root, "data/connections/metric_sources.yaml")
    validate_metric_source_config(config, resolver.projects)
    spec = config["projects"][PROJECT_ID]
    if spec["adapter"] != ADAPTER:
        return 2
    management = resolver.refresh(PROJECT_ID)
    if not management["success"]:
        return 2

    def records(project, project_id, observed):
        return collect_downloader(project, project_id, observed, spec)

    export_metric_snapshot(
        project_root,
        PROJECT_ID,
        {"records": records},
        exporter_id="youtube-hq-downloader-export",
        exporter_version="1.0",
        management=management,
        clock=lambda: observed_at,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
