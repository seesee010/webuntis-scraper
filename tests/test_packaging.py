"""Tests for packaging: pyproject metadata, entry points, path detection (#18)."""
from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import untis
from untis import config as config_mod
from untis import main as main_mod
from untis.config import _pick_dirs, _project_root

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())


# --- _project_root / _pick_dirs ------------------------------------------
def test_project_root_in_a_checkout(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    module = tmp_path / "src" / "untis" / "config.py"
    module.parent.mkdir(parents=True)
    module.write_text("")
    assert _project_root(module) == tmp_path


def test_project_root_when_installed(tmp_path):
    module = tmp_path / "lib" / "python3.14" / "site-packages" / "untis" / "config.py"
    module.parent.mkdir(parents=True)
    module.write_text("")
    assert _project_root(module) is None


def test_project_root_of_this_checkout():
    assert config_mod.PROJECT_ROOT == REPO


def test_pick_dirs_installed_always_uses_xdg(tmp_path):
    cfg, data = tmp_path / "cfg", tmp_path / "data"
    assert _pick_dirs(cfg, data, None) == (cfg, data)


def test_pick_dirs_checkout_with_xdg_config_uses_xdg(tmp_path):
    cfg, data = tmp_path / "cfg", tmp_path / "data"
    cfg.mkdir()
    (cfg / "config.json").write_text("{}")
    assert _pick_dirs(cfg, data, tmp_path / "repo") == (cfg, data)


def test_pick_dirs_checkout_without_xdg_config_uses_project(tmp_path):
    repo = tmp_path / "repo"
    assert _pick_dirs(tmp_path / "cfg", tmp_path / "data", repo) == (repo, repo)


# --- pyproject.toml ------------------------------------------------------
def test_console_script_points_to_main():
    target = PYPROJECT["project"]["scripts"]["untis"]
    module, func = target.split(":")
    assert (module, func) == ("untis.main", "main")
    assert callable(getattr(main_mod, func))


def test_version_is_single_sourced():
    assert PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "untis.__version__"}
    assert "version" in PYPROJECT["project"]["dynamic"]
    assert untis.__version__.count(".") == 2


def test_dependencies_have_upper_bounds():
    for dep in PYPROJECT["project"]["dependencies"]:
        assert ">=" in dep and "<" in dep.split(">=")[1], dep


def test_requires_python_and_package_location():
    assert PYPROJECT["project"]["requires-python"] == ">=3.11"
    assert PYPROJECT["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert (REPO / "src" / "untis" / "__init__.py").exists()
    assert not (REPO / "src" / "__init__.py").exists()      # no stray `src` package


def test_pytest_config_lives_in_pyproject():
    opts = PYPROJECT["tool"]["pytest"]["ini_options"]
    assert opts["asyncio_mode"] == "auto" and opts["pythonpath"] == ["src"]
    assert not (REPO / "pytest.ini").exists()


def test_requirements_txt_installs_the_project():
    lines = [l.strip() for l in (REPO / "requirements.txt").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    assert lines == ["-e ."]


# --- --version / python -m untis ------------------------------------------
def test_version_flag(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["untis", "--version"])
    with pytest.raises(SystemExit) as exc:
        main_mod._parse_args()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"untis {untis.__version__}"


def test_python_dash_m_untis():
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    out = subprocess.run([sys.executable, "-m", "untis", "-V"], capture_output=True,
                         text=True, env=env, cwd="/", timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == f"untis {untis.__version__}"


def test_no_separate_launcher():
    """The `untis` command comes from the console script (pip/pipx install);
    the old bin/untis shell launcher is gone."""
    assert not (REPO / "bin").exists()
