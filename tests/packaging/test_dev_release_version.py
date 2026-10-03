"""Release numbering and first-publication safeguards."""

import io
import urllib.error
from unittest.mock import patch

import pytest
from packaging.version import Version

from scripts import dev_release_version as release


@pytest.mark.parametrize("index", [{}, {"0.1.0.dev1": [{}]}])
def test_first_release_without_a_previous_final(index):
    assert release.release_version(Version("0.1.0"), index, 2) == "0.1.0.dev2"
    assert release.release_version(Version("0.1.0"), index) == "0.1.0"


def test_development_preserves_planned_minor_and_sorts_before_final():
    target = release.release_version(Version("0.2.0"), {"0.1.9": [{}]}, 41)
    assert target == "0.2.0.dev41"
    assert Version("0.1.9") < Version(target) < Version("0.2.0")


@pytest.mark.parametrize("files", [[], [{"yanked": True}], [{}]])
@pytest.mark.parametrize("run", [None, 7])
def test_final_versions_cannot_be_reused_even_when_yanked_or_deleted(files, run):
    with pytest.raises(release.DevVersionError, match="next release"):
        release.release_version(Version("0.1.0"), {"0.1.0": files}, run)


def test_development_rerun_refuses_the_same_serial():
    with pytest.raises(release.DevVersionError, match="already exists"):
        release.release_version(Version("0.1.0"), {"0.1.0.dev7": []}, 7)


@pytest.mark.parametrize("run", [-1, 0])
def test_invalid_run_numbers_are_refused(run):
    with pytest.raises(release.DevVersionError, match="positive"):
        release.release_version(Version("0.1.0"), {}, run)


@pytest.mark.parametrize("version", ["0.1", "0.1.0.dev7", "0.1.0rc1", "0.1.0.post1", "0.1.0+local", "1!0.1.0"])
def test_project_must_declare_exactly_three_final_components(version):
    with pytest.raises(release.DevVersionError, match="X.Y.Z"):
        release.declared_release(f'[project]\nversion = "{version}"\n')


def test_only_project_version_changes_even_if_another_version_appears_first():
    text = '[tool.other]\nversion = "9.9.9"\n\n[project]\nname = "ms-markets"\nversion = \'0.1.0\' # next release\n\n[tool.last]\nversion = "8.8.8"\n'
    rewritten = release.apply_version(text, "0.1.0.dev8")
    assert 'version = "9.9.9"' in rewritten
    assert 'version = "8.8.8"' in rewritten
    assert 'version = "0.1.0.dev8"' in rewritten


def test_index_orders_final_versions_numerically_and_ignores_prereleases():
    assert release.latest_final_version({"0.1.9": [], "0.1.10": [], "9.0.0rc1": [], "8.0.0.dev1": [], "invalid": []}) == Version("0.1.10")


def test_unknown_project_is_the_only_http_error_allowed():
    with patch.object(release.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("url", 404, "not found", {}, None)):
        assert release.fetch_releases("ms-markets") == {}
    for status in (403, 429, 500):
        with patch.object(release.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("url", status, "failed", {}, None)):
            with pytest.raises(release.DevVersionError, match="HTTP"):
                release.fetch_releases("ms-markets")


@pytest.mark.parametrize("payload", [b'[]', b'{}', b'{"releases": []}', b'not-json'])
def test_invalid_index_fails_closed(payload):
    with patch.object(release.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
        with pytest.raises(release.DevVersionError):
            release.fetch_releases("ms-markets")


def test_network_failure_does_not_look_like_a_first_release():
    with patch.object(release.urllib.request, "urlopen", side_effect=urllib.error.URLError("unavailable")):
        with pytest.raises(release.DevVersionError):
            release.fetch_releases("ms-markets")


def test_cli_reads_project_name_and_only_modifies_build_copy(tmp_path, monkeypatch, capsys):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "ms-markets"\nversion = "0.1.0"\n')
    monkeypatch.setattr(release, "PYPROJECT", project)
    queried = []
    monkeypatch.setattr(release, "fetch_releases", lambda package: queried.append(package) or {})
    assert release.main(["--final"]) == 0
    assert capsys.readouterr().out == "0.1.0\n"
    assert release.main(["--run-number", "9", "--write"]) == 0
    assert capsys.readouterr().out == "0.1.0.dev9\n"
    assert queried == ["ms-markets", "ms-markets"]
    assert 'version = "0.1.0.dev9"' in project.read_text()


def test_bump_patch_is_offline(tmp_path, monkeypatch, capsys):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "ms-markets"\nversion = "0.1.9"\n')
    monkeypatch.setattr(release, "PYPROJECT", project)
    monkeypatch.setattr(release, "fetch_releases", lambda *_: pytest.fail("bump requested network access"))
    assert release.main(["--bump-patch"]) == 0
    assert capsys.readouterr().out == "0.1.10\n"
    assert release.declared_release(project.read_text()) == Version("0.1.10")
