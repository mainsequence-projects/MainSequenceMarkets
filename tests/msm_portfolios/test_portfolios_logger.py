from __future__ import annotations

import structlog

from msm_portfolios import utils


def test_portfolios_logger_binds_sub_application() -> None:
    assert structlog.get_context(utils.get_portfolios_logger()).get("sub_application") == (
        "portfolios"
    )
    assert structlog.get_context(utils.logger).get("sub_application") == "portfolios"
