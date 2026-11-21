"""Turn Python and Node repos into Docker test environments, and guard the patches graded in them."""

from .detect import Stack, detect, install_script
from .env import BuildFailed, EnvSpec, UnsupportedRepo, base_image_for, build_env, check_supported
from .patches import (
    PatchFailed,
    Task,
    extract_patch,
    is_js_runner_config,
    split_patch,
    strip_test_changes,
)
from .repo import GitError, Repo2EnvError
from .testrun import TestReport, parse_jest_json, parse_junit, parse_report, run_tests, suite_command

__all__ = [
    "BuildFailed",
    "EnvSpec",
    "GitError",
    "PatchFailed",
    "Repo2EnvError",
    "Stack",
    "Task",
    "TestReport",
    "UnsupportedRepo",
    "base_image_for",
    "build_env",
    "check_supported",
    "detect",
    "extract_patch",
    "install_script",
    "is_js_runner_config",
    "parse_jest_json",
    "parse_junit",
    "parse_report",
    "run_tests",
    "split_patch",
    "strip_test_changes",
    "suite_command",
]
__version__ = "0.1.0"
