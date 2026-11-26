from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["project"]


def _requirement(name: str) -> Requirement:
    return next(
        Requirement(value)
        for value in _project()["dependencies"]
        if Requirement(value).name == name
    )


def test_package_metadata_enforces_sdk_9_floor_without_exact_patch_pin() -> None:
    requirement = _requirement("mainsequence")

    assert Version(_project()["version"]).major >= 2
    assert Version("8.1.11") not in requirement.specifier
    assert Version("8.99.0") not in requirement.specifier
    assert Version("9.0.0") not in requirement.specifier
    assert Version("9.0.1") not in requirement.specifier
    assert Version("9.0.5") not in requirement.specifier
    assert Version("9.0.18") not in requirement.specifier
    assert Version("9.0.19") not in requirement.specifier
    # 9.0.25/26 raise on `team_uids`, 9.0.29 brought access policies, and MetaTables
    # 0.1.60 and later need 9.0.31, the first SDK whose `Agent` parses platform Agent reads.
    assert Version("9.0.25") not in requirement.specifier
    assert Version("9.0.26") not in requirement.specifier
    assert Version("9.0.28") not in requirement.specifier
    assert Version("9.0.29") not in requirement.specifier
    assert Version("9.0.30") not in requirement.specifier
    assert Version("9.0.31") in requirement.specifier
    assert Version("9.99.0") in requirement.specifier
    assert Version("10.0.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)


def test_package_metadata_requires_extracted_metatables_client() -> None:
    requirement = _requirement("mainsequence-metatable")

    assert Version("0.1.30") not in requirement.specifier
    assert Version("0.1.31") not in requirement.specifier
    assert Version("0.1.32") not in requirement.specifier
    assert Version("0.1.33") not in requirement.specifier
    assert Version("0.1.34") not in requirement.specifier
    assert Version("0.1.35") not in requirement.specifier
    # 0.1.46 brought roles, 0.1.47's client is broken, 0.1.20-0.1.50 break on SDK 9.0.30,
    # 0.1.57 is the first release that hashes updater configurations holding dates and times,
    # 0.1.60 runs statement lists in one transaction, 0.1.61 binds UUIDs on SQLite inside
    # `IN` lists and as text, which the snapshot writes need on a SQLite DataSource, and
    # 0.1.64 waits out a MetaTables API rollout during discovery (MetaTables#108), which the
    # migration Job needs when it overlaps one, 0.1.66 is the first client of an API where
    # a table can be in several namespaces; an older client is refused by that API, 0.1.69
    # rebuilds a time-index table's stored statistics after a compiled-SQL write changes it
    # (MetaTables#117), which the account and portfolio deletes rely on, 0.1.71 binds
    # SQLite compiled SQL by position (MetaTables#121), so preparing a bulk upsert's statements
    # no longer takes time quadratic in their values, 0.1.73 keeps autogenerate from
    # dropping tables a provider does not own (MetaTables#125), 0.1.74 autogenerates an
    # added table on the selected runtime, stores a changed cadence, which the
    # InterpolatedPrices refusal tells a producer to do, and gives one update_hash to a
    # positional and a keyword configuration (MetaTables#127, #131, #130), 0.1.77
    # answers a delete impact in a fixed number of statements (MetaTables#136), reports a
    # client timeout as one (MetaTables#147) and keeps values, indexes and checks through
    # a SQLite rebuild (MetaTables#135), 0.1.78's client skills, which ms-markets
    # copies into .agents/skills/metatables, name no real application or vendor
    # (MetaTables#151), 0.1.80 runs several updaters as one invocation that runs a
    # shared dependency once (run_updaters, MetaTables#156), which run_portfolios uses,
    # 0.1.81 names the constraint and value that refused a time-index row
    # (MetaTables#157), and 0.1.82 exports the dtype tokens, sqlalchemy_type_to_token
    # and use_runtime_context, which ms-markets imports from metatables (MetaTables#160),
    # 0.1.83 registers a run's updates and edges with one request each (MetaTables#162),
    # 0.1.84 imports a node's table classes by address and rebuilds a typed updater in a
    # pydantic configuration (MetaTables#165, #164), which a node Job run needs (ADR 0067),
    # and 0.1.85's API, which `metatables serve --local` runs, starts and ends a run without
    # the deployment-wide catalog lock, so the parallel nodes of a node Job run no longer
    # queue behind every data request (MetaTables#167).
    assert Version("0.1.47") not in requirement.specifier
    assert Version("0.1.50") not in requirement.specifier
    assert Version("0.1.56") not in requirement.specifier
    assert Version("0.1.57") not in requirement.specifier
    assert Version("0.1.60") not in requirement.specifier
    assert Version("0.1.63") not in requirement.specifier
    assert Version("0.1.65") not in requirement.specifier
    assert Version("0.1.68") not in requirement.specifier
    assert Version("0.1.70") not in requirement.specifier
    assert Version("0.1.72") not in requirement.specifier
    assert Version("0.1.73") not in requirement.specifier
    assert Version("0.1.74") not in requirement.specifier
    assert Version("0.1.76") not in requirement.specifier
    assert Version("0.1.77") not in requirement.specifier
    assert Version("0.1.79") not in requirement.specifier
    assert Version("0.1.80") not in requirement.specifier
    assert Version("0.1.81") not in requirement.specifier
    assert Version("0.1.82") not in requirement.specifier
    assert Version("0.1.83") not in requirement.specifier
    assert Version("0.1.84") not in requirement.specifier
    assert Version("0.1.85") in requirement.specifier
    assert Version("0.1.99") in requirement.specifier
    assert Version("0.2.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)
    assert not any(Requirement(value).name == "metatables" for value in _project()["dependencies"])
