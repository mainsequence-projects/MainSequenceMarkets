import datetime
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
import pytz
from pydantic import ConfigDict, Field, WithJsonSchema

from metatables import (
    PlatformTimeIndexMetaTable,
    TimeIndexTableRef,
    TimeIndexTableUpdater,
    UpdateStatistics,
)
from metatables.updaters.utils import (
    string_freq_to_time_delta,
    string_frequency_to_minutes,
)
from msm.time_index.assets.asset_indexed import (
    AssetIndexedUpdater,
    AssetIndexedUpdaterConfiguration,
)
from msm.time_index.utils.time import normalize_datetime64_ns_utc
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm.storage_instances import (
    INSTANCE_KEY_COMPONENT,
    STORAGE_CONTRACT_COMPONENT,
    normalized_cadence,
)
from msm_portfolios.asset_scope import (
    asset_unique_identifier,
    refuse_scope_calendar,
    require_asset_category_scope,
)
from msm_portfolios.services.calendars import (
    PersistedCalendarSchedule,
    resolve_asset_schedules,
)
from msm_portfolios.time_index.prices.storage import (
    InterpolatedPricesStorage,
    interpolated_prices_instance_key,
)
from msm_portfolios.utils import TIMEDELTA

_ONE_DAY = datetime.timedelta(days=1)


class InterpolatedPricesConfig(AssetIndexedUpdaterConfiguration):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    intraday_bar_interpolation_rule: str
    source_price_instance: Annotated[
        TimeIndexTableUpdater | TimeIndexTableRef,
        Field(
            description=(
                "The source bars (ADR 0066, decision 4): the updater that writes them, when "
                "they come from a graph, or one table referred to by its physical name, "
                "TimeIndexTableRef.from_physical_identity(schema=..., table_name=...)."
            ),
        ),
        WithJsonSchema({"type": "object"}),
    ]
    asset_category_unique_id: str | None = Field(
        default=None,
    )
    upsample_frequency_id: str | None = None
    events_in_price: Literal["adjusted"] | tuple[str, ...] = Field(
        default="adjusted",
        description=(
            "The events the source's prices include (ADR 0065). 'adjusted', the default, "
            "means every event of the asset, so a portfolio needs no lifecycle model for "
            "them; a tuple names exactly the event types they include, () for unadjusted "
            "prices. The updater adjusts nothing: it states the level of the bars it reads, "
            "so the setting changes no row it writes and is not part of its update hash."
        ),
        json_schema_extra={"hash_excluded": True},
    )


def _assert_source_price_instance(
    source_price: TimeIndexTableUpdater | TimeIndexTableRef,
) -> TimeIndexTableUpdater | TimeIndexTableRef:
    if not isinstance(source_price, (TimeIndexTableUpdater, TimeIndexTableRef)):
        raise TypeError(
            "Price sources must be TimeIndexTableUpdater or TimeIndexTableRef instances."
        )
    return source_price


def _source_output_metadata(
    source_price: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    source_context: str,
) -> Any:
    source_price = _assert_source_price_instance(source_price)
    if isinstance(source_price, TimeIndexTableRef):
        output_metadata = source_price.output_table
        if output_metadata is None:
            raise RuntimeError(
                "InterpolatedPrices source_price_instance was a TimeIndexTableRef without "
                "registered output metadata. Build it with "
                "TimeIndexTableRef.from_physical_identity(schema=..., table_name=...)."
            )
        return output_metadata

    try:
        return source_price.output_metadata
    except ValueError as exc:
        raise RuntimeError(
            "InterpolatedPrices source_price_instance must have registered "
            f"output metadata, where interpolation reads the source's table name and cadence: "
            f"{source_context}."
        ) from exc


def _require_output_table_of_configuration(
    output_table: Any,
    *,
    instance_key: str,
    cadence: str,
) -> None:
    """Refuse a table other than the one this configuration produces.

    Rows are keyed only by time and asset, so one table holds one configuration.
    """

    contract = InterpolatedPricesStorage.__markets_authored_identifier__
    identity = getattr(output_table, "__metatable_extra_hash_components__", None) or {}
    bound = (
        identity.get(STORAGE_CONTRACT_COMPONENT),
        identity.get(INSTANCE_KEY_COMPONENT),
        getattr(output_table, "__cadence__", None),
    )
    if bound != (contract, instance_key, cadence):
        raise ValueError(
            "InterpolatedPrices writes only the table its configuration produces: the "
            f"{contract} instance with key {instance_key!r} and cadence {cadence!r}. "
            f"output_table={getattr(output_table, '__name__', output_table)!s} has contract, key "
            f"and cadence {bound!r}. Declare the table with a class statement on "
            f"InterpolatedPricesInstance and the owner's base, with __instance_key__ = "
            f"{instance_key!r} and __cadence__ = {cadence!r}, and migrate it with its owner's "
            "provider."
        )


def _registered_cadence(output_metadata: Any) -> Any:
    profile = getattr(output_metadata, "time_indexed_profile", None)
    cadence = getattr(profile, "cadence", None)
    if cadence in (None, ""):
        cadence = getattr(output_metadata, "cadence", None)
    if cadence in (None, ""):
        contract = getattr(output_metadata, "table_contract", None)
        if isinstance(contract, dict):
            authoring = contract.get("authoring")
            if isinstance(authoring, dict):
                time_indexed = authoring.get("time_indexed")
                if isinstance(time_indexed, dict):
                    cadence = time_indexed.get("cadence")
    return cadence


def _source_time_indexed_profile_cadence(source_metadata: Any) -> str:
    """The cadence the source table is registered with."""

    source_table_name = getattr(source_metadata, "physical_table_name", None)
    cadence = _registered_cadence(source_metadata)
    if cadence in (None, ""):
        raise RuntimeError(
            "InterpolatedPrices requires the source TimeIndexMetaTable to declare "
            "time_indexed_profile.cadence. Register or migrate the source storage "
            f"{source_table_name} with __cadence__ before using it "
            "as a portfolio price source."
        )

    cadence = normalized_cadence(cadence, argument="source cadence")
    if not (cadence.endswith("d") or cadence.endswith("m")):
        raise ValueError(
            "InterpolatedPrices currently supports daily or minute source cadences. "
            f"Source TimeIndexMetaTable {source_table_name} declares "
            f"cadence={cadence!r}."
        )
    return cadence


def _asset_schedule_map(asset_list) -> dict[str, PersistedCalendarSchedule]:
    """The stored trading calendar of every asset in the scope (ADR 0056).

    There is no default calendar. An asset with no ``AssetCalendar`` link fails
    the whole scope, and the error names every such asset.
    """

    assets = list(asset_list)
    for asset in assets:
        refuse_scope_calendar(asset)
    return resolve_asset_schedules(asset_unique_identifier(asset) for asset in assets)


def _session_dates(schedule: pd.DataFrame) -> pd.Series:
    return pd.Series([pd.Timestamp(value).date() for value in schedule.index], index=schedule.index)


def _sessions_between_dates(
    schedule: pd.DataFrame,
    start: datetime.date,
    end: datetime.date,
) -> pd.DataFrame:
    """Sessions whose local date lies between two dates, both included."""

    if schedule.empty:
        return schedule
    dates = _session_dates(schedule)
    return schedule[((dates >= start) & (dates <= end)).to_numpy()]


def _sessions_closing_between(
    schedule: pd.DataFrame,
    first: pd.Timestamp,
    last: pd.Timestamp,
) -> pd.DataFrame:
    """Sessions whose close lies between two instants, both included.

    A session belongs to a window of bars by the instant it closes, not by its
    date: a session that closes at midnight closes on the next date.
    """

    if schedule.empty:
        return schedule
    closes = schedule["market_close"]
    return schedule[((closes >= first) & (closes <= last)).to_numpy()]


def _normalize_time_indexed_frame_ns_utc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    index_names = list(frame.index.names)
    if "time_index" not in index_names:
        return frame

    normalized = frame.reset_index()
    normalized["time_index"] = normalize_datetime64_ns_utc(normalized["time_index"])
    for column_name in ("open_time", "first_trade_time", "last_trade_time"):
        if column_name in normalized.columns:
            normalized[column_name] = normalize_datetime64_ns_utc(normalized[column_name])

    return normalized.set_index(index_names).sort_index()


class UpsampleAndInterpolation:
    """
    Handles upsampling and interpolation of bar data.
    """

    TIMESTAMP_COLS = ["first_trade_time", "last_trade_time", "open_time"]

    def __init__(
        self,
        bar_frequency_id: str,
        upsample_frequency_id: str,
        intraday_bar_interpolation_rule: str,
    ):
        self.bar_frequency_id = bar_frequency_id
        self.upsample_frequency_id = upsample_frequency_id
        self.intraday_bar_interpolation_rule = intraday_bar_interpolation_rule

        rows = string_frequency_to_minutes(
            self.upsample_frequency_id
        ) / string_frequency_to_minutes(self.bar_frequency_id)
        assert rows.is_integer()

        if self.bar_frequency_id.endswith("d"):
            assert (
                bar_frequency_id == self.upsample_frequency_id
            )  # Upsampling for daily bars not implemented

        self.upsample_frequency_td = string_freq_to_time_delta(self.upsample_frequency_id)

    @staticmethod
    def upsample_bars(
        bars_df: pd.DataFrame,
        *,
        interval: datetime.timedelta,
        schedule: pd.DataFrame,
    ) -> pd.DataFrame:
        """Aggregate interpolated bars into one bar per ``interval`` of each session (#117).

        A session's intervals start at its open, one ``interval`` after another; the last
        ends at the session's close and can be shorter. A bar belongs to the interval its
        close falls in: after the interval's start, up to and including its end. A bar that
        closes at or before the open, such as the interpolation's row at the open itself,
        belongs to none.

        Each interval with bars gives one bar stamped at the interval's end, with
        ``open_time`` its start: the first bar's open, the last bar's close, the highest
        high and lowest low, the volume and trade count summed, and the VWAP weighted by
        volume, or the last close when no volume traded. It is ``interpolated`` only when
        every bar in it was filled forward.

        Args:
            bars_df: Interpolated bars of one asset, indexed by their close.
            interval: The target bar length.
            schedule: Sessions of the asset's stored calendar that cover the bars, with
                ``market_open`` and ``market_close`` in UTC.
        """

        closes = pd.DatetimeIndex(bars_df.index)
        out: list[dict[str, Any]] = []
        for session_open, session_close in schedule[["market_open", "market_close"]].itertuples(
            index=False
        ):
            in_session = bars_df[(closes > session_open) & (closes <= session_close)]
            if in_session.empty:
                continue
            elapsed = pd.DatetimeIndex(in_session.index) - session_open
            for number, group in in_session.groupby(np.ceil(elapsed / interval).astype(int)):
                end = min(session_open + number * interval, session_close)
                volume = float(np.nansum(group["volume"].to_numpy(dtype=float)))
                close = group["close"].iloc[-1]
                vwap = close
                if volume > 0 and "vwap" in group.columns:
                    vwap = float(np.nansum((group["vwap"] * group["volume"]).to_numpy(dtype=float)) / volume)
                bar: dict[str, Any] = {
                    "time": end,
                    "open_time": session_open + (number - 1) * interval,
                    "open": group["open"].iloc[0],
                    "high": np.nanmax(group["high"].to_numpy(dtype=float)),
                    "low": np.nanmin(group["low"].to_numpy(dtype=float)),
                    "close": close,
                    "volume": volume,
                    "vwap": vwap,
                }
                if "trade_count" in group.columns:
                    bar["trade_count"] = float(np.nansum(group["trade_count"].to_numpy(dtype=float)))
                if "interpolated" in group.columns:
                    bar["interpolated"] = bool(group["interpolated"].fillna(False).astype(bool).all())
                out.append(bar)
        if not out:
            return pd.DataFrame()
        upsampled = pd.DataFrame(out)
        upsampled[ASSET_IDENTIFIER_DIMENSION] = bars_df[ASSET_IDENTIFIER_DIMENSION].iloc[0]
        return upsampled.set_index("time").sort_index()

    def get_interpolated_upsampled_bars(
        self,
        schedule: pd.DataFrame,
        tmp_df: pd.DataFrame,
        last_observation: None | pd.Series = None,
    ) -> pd.DataFrame:
        """
        Gets interpolated and upsampled bars based on the given parameters.
        First interpolates the data to fill any gaps, then upsamples it to the desired frequency.

        Args:
            schedule (pd.DataFrame): Sessions of the asset's stored calendar that cover the
                bars, with ``market_open`` and ``market_close`` in UTC.
            tmp_df (pd.DataFrame): Dataframe containing the bars to be processed.
            last_observation (Union[None, pd.Series], optional): Last observed data to fill gaps.

        Returns:
            pd.DataFrame: Interpolated and upsampled bars dataframe.
        """
        for col in self.TIMESTAMP_COLS:
            try:
                if col in tmp_df.columns:
                    s = pd.to_numeric(tmp_df[col], errors="coerce")
                    digits = s.dropna().abs().astype("int64").astype(str).str.len()
                    UNIT_BY_MIN_DIGITS = {18: "ns", 15: "us", 12: "ms", 10: "s", 0: "m"}
                    d = int(digits.mode().iat[0])

                    unit = UNIT_BY_MIN_DIGITS[max(k for k in UNIT_BY_MIN_DIGITS if d >= k)]
                    tmp_df[col] = normalize_datetime64_ns_utc(
                        pd.to_datetime(s, unit=unit, utc=True)
                    )

            except Exception as e:
                raise e

        if self.bar_frequency_id.endswith("d"):
            tmp_df = interpolate_daily_bars(
                bars_df=tmp_df.copy(),
                interpolation_rule=self.intraday_bar_interpolation_rule,
                schedule=schedule,
                last_observation=last_observation,
            )
        elif self.bar_frequency_id.endswith("m"):
            bars_frequency_min = string_frequency_to_minutes(self.bar_frequency_id)

            # Interpolation to fill gaps
            tmp_df = interpolate_intraday_bars(
                bars_df=tmp_df.copy(),
                interpolation_rule=self.intraday_bar_interpolation_rule,
                schedule=schedule,
                bars_frequency_min=bars_frequency_min,
                last_observation=last_observation,
            )

        if len(tmp_df) == 0:
            return tmp_df

        assert tmp_df.isnull().sum()[["close", "open"]].sum() == 0

        # Upsample to the correct frequency
        if self.bar_frequency_id.endswith("d"):
            all_columns = self.TIMESTAMP_COLS
            upsampled_df = tmp_df
        else:
            # Source bars per target bar; one is the source frequency itself.
            bars_per_target = (
                string_frequency_to_minutes(self.upsample_frequency_id) // bars_frequency_min
            )
            if bars_per_target > 1:
                upsampled_df = UpsampleAndInterpolation.upsample_bars(
                    tmp_df,
                    interval=self.upsample_frequency_td,
                    schedule=schedule,
                )
            else:
                upsampled_df = tmp_df
            all_columns = self.TIMESTAMP_COLS + ["trade_day"]
        # Keep everything as timezone-aware datetimes.
        for col in all_columns:
            if col in upsampled_df.columns:
                upsampled_df[col] = normalize_datetime64_ns_utc(upsampled_df[col])

        return upsampled_df


def interpolate_daily_bars(
    bars_df: pd.DataFrame,
    interpolation_rule: str,
    schedule: pd.DataFrame,
    last_observation: None | pd.Series = None,  # fix annotation
):
    """Put daily bars on the session closes of the asset's stored calendar.

    A source bar is stamped at its time of observation: the close of its session.
    The output has one row per session close between the first and the last
    source bar, filled forward from the latest source bar at or before it. No row
    is written after the last source bar.
    """

    def rebase_with_forward_fill(bars_df, last_observation):
        try:
            if last_observation is not None:
                if "interpolated" in last_observation.columns:
                    last_observation = last_observation.drop(columns="interpolated")

                bars_df = pd.concat([last_observation, bars_df], axis=0).sort_index()
                if ASSET_IDENTIFIER_DIMENSION in bars_df.columns:
                    bars_df.loc[:, [ASSET_IDENTIFIER_DIMENSION]] = (
                        bars_df[[ASSET_IDENTIFIER_DIMENSION]].bfill().ffill()
                    )

            null_index = bars_df.isnull().any(axis=1)
            bars_df["close"] = bars_df["close"].ffill()
            bars_df["open"] = bars_df["open"].where(~null_index, bars_df["close"])
            try:
                bars_df.volume = bars_df.volume.fillna(0)
            except Exception as e:
                raise e
            if "vwap" in bars_df.columns:
                bars_df.vwap = bars_df.vwap.ffill()
            if "trade_count" in bars_df.columns:
                bars_df.trade_count = bars_df.trade_count.fillna(0)

            if len(null_index) > 0:
                if "high" in bars_df.columns:
                    bars_df["high"] = bars_df["high"].where(~null_index, bars_df["close"])
                    bars_df["low"] = bars_df["low"].where(~null_index, bars_df["close"])

                bars_df["interpolated"] = False
                bars_df.loc[null_index, "interpolated"] = True

            else:
                bars_df["interpolated"] = False

            if last_observation is not None:
                bars_df = bars_df.iloc[1:]
        except Exception as e:
            raise e

        return bars_df

    restricted_schedule = _sessions_closing_between(
        schedule,
        pd.Timestamp(bars_df.index.min()),
        pd.Timestamp(bars_df.index.max()),
    )

    restricted_schedule = restricted_schedule.reset_index()
    market_type = "market_close"

    restricted_schedule = restricted_schedule.set_index(market_type)
    full_index = bars_df.index.union(restricted_schedule.index)

    bars_df = bars_df.reindex(full_index)

    if interpolation_rule == "None":
        pass
    elif interpolation_rule == "ffill":
        bars_df = rebase_with_forward_fill(bars_df, last_observation=last_observation)
        if last_observation is None:
            bars_df = bars_df.bfill()
    else:
        raise Exception

    if len(bars_df):
        last_observation = bars_df.iloc[[-1]]

    if len(bars_df) == 0:
        return pd.DataFrame()

    bars_df = bars_df[bars_df.index.isin(restricted_schedule.index)]

    # Daily source tables may use their time index as the session close and omit
    # an explicit bar-open timestamp. The persisted calendar already supplies
    # the authoritative open for every retained close, so derive the optional
    # InterpolatedPrices field instead of requiring it from every source schema.
    if "open_time" not in bars_df.columns:
        bars_df["open_time"] = pd.Series(
            pd.NaT,
            index=bars_df.index,
            dtype="datetime64[ns, UTC]",
        )
    null_index = bars_df[bars_df["open_time"].isnull()].index
    if len(null_index) > 0:
        # Use the market_open that corresponds to each market_close index
        bars_df.loc[null_index, "open_time"] = restricted_schedule.loc[null_index, "market_open"]

    return bars_df


def interpolate_intraday_bars(
    bars_df: pd.DataFrame,
    interpolation_rule: str,
    bars_frequency_min: int,
    schedule: pd.DataFrame,
    last_observation: None | pd.Series = None,
) -> pd.DataFrame:
    """
    Interpolates intraday bars based on the given parameters. Fills in missing data points in intraday bar data in case of gaps.
    """
    sessions_by_date = {
        session_date: session
        for session_date, session in zip(
            _session_dates(schedule), schedule.to_dict("records"), strict=True
        )
    }

    def build_daily_range_from_schedule(start, end):
        return pd.date_range(start=start, end=end, freq=f"{bars_frequency_min}min")

    def sanitize_today_update(x: pd.DataFrame, date_range, day):
        # normalize to UTC for consistent “today” comparison
        today_utc = datetime.datetime.now(datetime.UTC)

        if day.date() == today_utc.date():
            x.index.name = None
            if len(x.index) > 0:
                last = x.index.max()
                date_range = [i for i in date_range if i <= last]
        return date_range

    def rebase_withoutnan_fill(x, trade_starts, trade_ends):
        date_range = build_daily_range_from_schedule(trade_starts, trade_ends)
        date_range = sanitize_today_update(x=x, date_range=date_range, day=trade_starts)
        x = x.reindex(date_range)
        return x

    def rebase_with_forward_fill(x, trade_starts, trade_ends, last_observation):
        is_start_of_day = False
        if (x.shape[0] == 1) and x.index[0].hour == 0:
            is_start_of_day = True
        x["interpolated"] = False
        if not is_start_of_day:
            date_range = build_daily_range_from_schedule(trade_starts, trade_ends)
            date_range = sanitize_today_update(x=x, date_range=date_range, day=trade_starts)
            try:
                x = x.reindex(date_range)

                if last_observation is not None:
                    if "interpolated" in x.columns:
                        last_observation = last_observation.drop(columns="interpolated")
                    x = pd.concat([last_observation, x], axis=0)

                null_index = x[x["close"].isnull()].index
                x.close = x.close.ffill()
                x.loc[null_index, "open"] = x.loc[null_index, "close"]
                x.volume = x.volume.fillna(0)
                x.vwap = x.vwap.ffill()
                if "trade_count" in x.columns:
                    x.trade_count = x.trade_count.fillna(0)
                x["interpolated"] = False
                if len(null_index) > 0:
                    if "high" in x.columns:
                        x.loc[null_index, "high"] = x.loc[null_index, "close"]
                        x.loc[null_index, "low"] = x.loc[null_index, "close"]

                    x.loc[null_index, "interpolated"] = True

                if last_observation is not None:
                    x = x.iloc[1:]
            except Exception as e:
                raise e

        # interpolate any other columns with 0

        return x

    full_index = bars_df.index

    # The index holds closes, so the last session to add is the one the last bar opened in.
    restricted_schedule = _sessions_between_dates(
        schedule,
        pd.Timestamp(bars_df.index.min()).date(),
        pd.Timestamp(bars_df.iloc[-1]["open_time"]).date(),
    )

    bars_df = bars_df[
        ~bars_df.index.duplicated(keep="first")
    ]  # todo: remove uncessary with indices.

    full_index = bars_df.index.union(restricted_schedule.set_index("market_open").index).union(
        restricted_schedule.set_index("market_close").index
    )

    bars_df = bars_df.reindex(full_index)

    bars_df["trade_day"] = bars_df.index
    bars_df["trade_day"] = pd.to_datetime(bars_df.index, utc=True).normalize()

    groups = bars_df.groupby("trade_day")
    interpolated_data = []

    for day, group_df in groups:
        session = sessions_by_date.get(pd.Timestamp(day).date())
        if session is None:
            continue
        trade_starts = session["market_open"]
        trade_ends = session["market_close"]

        group_df = group_df[group_df.index >= trade_starts]
        group_df = group_df[group_df.index <= trade_ends]

        if group_df.dropna().shape[0] == 0:
            continue

        if trade_starts < day:
            trade_starts = day
        next_day = day + datetime.timedelta(days=1)
        if trade_ends >= next_day:
            trade_ends = next_day - datetime.timedelta(minutes=1)

        if interpolation_rule == "None":
            tmp_df = rebase_withoutnan_fill(
                group_df, trade_starts=trade_starts, trade_ends=trade_ends
            )
        elif interpolation_rule == "ffill":
            tmp_df = rebase_with_forward_fill(
                group_df,
                trade_starts=trade_starts,
                last_observation=last_observation,
                trade_ends=trade_ends,
            )
            if last_observation is None:
                tmp_df = tmp_df.bfill()
        else:
            raise Exception

        if len(tmp_df):
            last_observation = tmp_df.iloc[[-1]]
        interpolated_data.append(tmp_df)

    if len(interpolated_data) == 0:
        return pd.DataFrame()

    interpolated_data = pd.concat(interpolated_data, axis=0)
    interpolated_data["trade_day"] = interpolated_data.index
    interpolated_data["trade_day"] = interpolated_data["trade_day"].apply(
        lambda x: x.replace(hour=0, minute=0, second=0)
    )

    return interpolated_data


BARS_READ_PAGE_SIZE = 10_000
"""Rows per page of the source-bars read: the most a MetaTables page holds.

An asset new to the table reads its bars from ``OFFSET_START``. The pages of one read are
requested one after another under the read's one deadline (60 s), and a page takes about the
same time however many rows it holds, so the deadline limits requests, not rows. At the
default 500 rows a first read of ten new assets ran out of time in Production (#123).
"""

BARS_READ_ROWS = 50_000
"""The most bars one source-bars read is planned to hold (#155).

MetaTables gives one read 100,000 rows, 64 MiB and 60 s by default, all its pages together.
The bars of all the assets can be many times that, so ``_bars_reads`` splits them into reads
of at most this many bars, each with its own budget. The planned count is an upper bound
taken from the source's cadence, and the other half of the row budget covers bars stamped
off the cadence's grid, such as daily closes that move with daylight saving. A read holds at
most five full pages.
"""

BARS_READ_ASSETS = 100
"""The most asset ranges one source-bars read holds: what MetaTables sends in one request.

A read of more ranges makes one request per hundred, all under the read's one deadline, so a
read of a few thousand assets with a bar or two each would run out of time.
"""


def _bars_reads(
    dimension_range_map: list[dict[str, Any]],
    *,
    interval: datetime.timedelta,
    now: datetime.datetime,
) -> list[list[dict[str, Any]]]:
    """Split the source-bars read into reads of at most ``BARS_READ_ROWS`` bars and
    ``BARS_READ_ASSETS`` assets each (#155).

    A table at a cadence holds at most one bar per asset per interval, so an asset has at
    most ``(now - start) // interval + 1`` bars from its range's start. The ranges fill a
    read in order until the next would take it past either limit. An asset with more bars
    than one read holds is read in windows of ``BARS_READ_ROWS - 1`` intervals, each ending
    where the next starts; the last is open-ended, as every unsplit range is. An empty map
    stays one read.
    """
    if not dimension_range_map:
        return [dimension_range_map]

    def most_bars(start: datetime.datetime) -> int:
        return max((now - start) // interval + 1, 0)

    window = interval * (BARS_READ_ROWS - 1)
    reads: list[list[dict[str, Any]]] = [[]]
    bars = 0
    for asset_range in dimension_range_map:
        start = asset_range["start_date"]
        while most_bars(start) > BARS_READ_ROWS:
            end = start + window
            if reads[-1]:
                reads.append([])
            reads[-1].append(
                {**asset_range, "start_date": start, "end_date": end, "end_date_operand": "<"}
            )
            reads.append([])
            bars = 0
            asset_range = {**asset_range, "start_date_operand": ">="}
            start = end
        if reads[-1] and (
            bars + most_bars(start) > BARS_READ_ROWS or len(reads[-1]) == BARS_READ_ASSETS
        ):
            reads.append([])
            bars = 0
        reads[-1].append({**asset_range, "start_date": start})
        bars += most_bars(start)
    return [read for read in reads if read]


class InterpolatedPrices(AssetIndexedUpdater):
    """
    Handles interpolated prices for assets.
    """

    OFFSET_START = datetime.datetime(2017, 7, 20).replace(tzinfo=pytz.utc)

    def __init__(
        self,
        interpolation_config: InterpolatedPricesConfig,
        *args,
        output_table: type[PlatformTimeIndexMetaTable],
        **kwargs,
    ):
        """
        Initializes the InterpolatedPrices object.

        ``output_table`` is the table of this configuration, which its producer declares
        and migrates: the ``InterpolatedPricesTS`` instance whose key
        ``interpolated_prices_instance_key`` computes and whose cadence is the upsample
        frequency (#95). Another table is refused. It is where rows land, and is no part
        of this updater's ``update_hash``.

        With neither ``asset_list`` nor ``asset_category_unique_id``, the assets are the
        source updater's (#145). A source that names no assets, a ``TimeIndexTableRef``
        or an updater that is not asset-indexed, is refused here.
        """
        self.interpolation_config = interpolation_config
        for asset in interpolation_config.asset_list or []:
            refuse_scope_calendar(asset)
        intraday_bar_interpolation_rule = interpolation_config.intraday_bar_interpolation_rule
        asset_category_unique_id = interpolation_config.asset_category_unique_id
        asset_list = interpolation_config.asset_list
        source_prices_ts = _assert_source_price_instance(
            interpolation_config.source_price_instance
        )
        if (
            asset_list is None
            and asset_category_unique_id is None
            and not isinstance(source_prices_ts, AssetIndexedUpdater)
        ):
            raise ValueError(
                "InterpolatedPrices needs asset_list or asset_category_unique_id when its "
                f"source names no assets: {source_prices_ts.__class__.__name__} is not an "
                "asset-indexed updater. Without them, the assets are the source updater's "
                "get_asset_list()."
            )
        source_metadata = _source_output_metadata(
            source_prices_ts, source_context=source_prices_ts.__class__.__name__
        )
        source_cadence = _source_time_indexed_profile_cadence(source_metadata)
        upsample_frequency_id = normalized_cadence(
            interpolation_config.upsample_frequency_id or source_cadence,
            argument="upsample_frequency_id",
        )
        _require_output_table_of_configuration(
            output_table,
            instance_key=interpolated_prices_instance_key(
                source_table_name=source_metadata.physical_table_name,
                source_cadence=source_cadence,
                upsample_frequency_id=upsample_frequency_id,
                intraday_bar_interpolation_rule=intraday_bar_interpolation_rule,
            ),
            cadence=upsample_frequency_id,
        )

        self.asset_category_unique_id = asset_category_unique_id
        self.interpolator = UpsampleAndInterpolation(
            bar_frequency_id=source_cadence,
            upsample_frequency_id=upsample_frequency_id,
            intraday_bar_interpolation_rule=intraday_bar_interpolation_rule,
        )
        self.constructor_asset_list = asset_list
        bars_frequency_min = string_frequency_to_minutes(source_cadence)
        self.maximum_forward_fill = datetime.timedelta(minutes=bars_frequency_min) - TIMEDELTA

        self.intraday_bar_interpolation_rule = intraday_bar_interpolation_rule
        self.bar_frequency_id = source_cadence
        self.upsample_frequency_id = upsample_frequency_id
        self.bars_ts = source_prices_ts

        super().__init__(
            config=interpolation_config,
            output_table=output_table,
            *args,
            **kwargs,
        )
        # Whatever reads this table as a source takes its cadence from the catalog, which
        # follows a corrected class only when its provider's next upgrade runs.
        registered_cadence = _registered_cadence(self.output_metadata)
        if str(registered_cadence or "").strip().lower() != upsample_frequency_id:
            raise ValueError(
                f"InterpolatedPrices output_table {output_table.__table__.name} is registered "
                f"with cadence {registered_cadence!r}, and its configuration needs "
                f"{upsample_frequency_id!r}. Run its provider's `metatables migrations "
                "upgrade`, which registers the cadence the class declares."
            )

    def dependencies(self):
        return {"bars_ts": self.bars_ts}

    @classmethod
    def _required_output_table(cls) -> type[InterpolatedPricesStorage]:
        return InterpolatedPricesStorage

    def get_string_frequency_to_minutes(self):
        return string_frequency_to_minutes(self.bar_frequency_id)

    def run_post_update_routines(self, error_on_last_update):
        if not self.table_update.output_table.protect_from_deletion:
            self.update_manager.protect_from_deletion()

    def _transform_raw_data_to_upsampled_df(
        self,
        raw_data_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Transforms raw data into an upsampled dataframe.
        """
        upsampled_df = []

        dimension_range_map = self.get_asset_dimension_range_map_great_or_equal()
        full_last_observation = self.get_df_between_dates(dimension_range_map=dimension_range_map)
        last_observation_map = {}

        for asset_identifier in raw_data_df[ASSET_IDENTIFIER_DIMENSION].unique():
            if full_last_observation is None or full_last_observation.empty:
                last_observation_map[asset_identifier] = None
                continue

            if (
                asset_identifier
                in full_last_observation.index.get_level_values(
                    ASSET_IDENTIFIER_DIMENSION
                ).to_list()
            ):
                last_obs = full_last_observation.loc[
                    (slice(None), asset_identifier), :
                ].reset_index([ASSET_IDENTIFIER_DIMENSION], drop=True)
                last_obs.index.name = None
                if "open_time" in last_obs.columns:
                    last_obs["open_time"] = pd.to_datetime(last_obs["open_time"], utc=True)
                last_observation_map[asset_identifier] = last_obs
            else:
                last_observation_map[asset_identifier] = None

        schedule_frames = self._schedule_frames(raw_data_df)
        for asset_identifier, df in raw_data_df.groupby(ASSET_IDENTIFIER_DIMENSION):
            if df.shape[0] > 1:
                df = self.interpolator.get_interpolated_upsampled_bars(
                    schedule=schedule_frames[self.asset_schedules[asset_identifier].calendar.uid],
                    tmp_df=df,
                    last_observation=last_observation_map[asset_identifier],
                )
                df[ASSET_IDENTIFIER_DIMENSION] = asset_identifier
                upsampled_df.append(df)

        upsampled_df = [d for d in upsampled_df if len(d) > 0]  # Remove empty dataframes
        if len(upsampled_df) == 0:
            return pd.DataFrame()

        max_value_per_asset = {
            d.index.max(): d[ASSET_IDENTIFIER_DIMENSION].iloc[0] for d in upsampled_df
        }

        min_end_time = min(max_value_per_asset.keys())
        max_end_time = max(max_value_per_asset.keys())
        self.logger.info(
            "Upsampled window aligned: min_end=%s (asset=%s), max_end=%s",
            min_end_time.isoformat(),
            max_value_per_asset[min_end_time],
            max_end_time.isoformat(),
        )
        upsampled_df = pd.concat(upsampled_df, axis=0)
        # upsampled_df = upsampled_df[upsampled_df.index <= min_max]
        upsampled_df.volume = upsampled_df.volume.fillna(0)

        upsampled_df.index.name = "time_index"
        upsampled_df = upsampled_df.set_index(ASSET_IDENTIFIER_DIMENSION, append=True)
        upsampled_df = upsampled_df.sort_index(level=0)

        if upsampled_df.shape[0] == 0:
            upsampled_df = pd.DataFrame()

        return upsampled_df

    def _schedule_frames(self, raw_data_df: pd.DataFrame) -> dict[Any, pd.DataFrame]:
        """Each distinct calendar's sessions for the window of the bars, computed once.

        The window is a day wider at both ends: a session can close on the date
        after its own, and open on the date before it.
        """

        start = (pd.Timestamp(raw_data_df.index.min()) - _ONE_DAY).date()
        end = (pd.Timestamp(raw_data_df.index.max()) + _ONE_DAY).date()
        frames: dict[Any, pd.DataFrame] = {}
        for asset_identifier in raw_data_df[ASSET_IDENTIFIER_DIMENSION].unique():
            schedule = self.asset_schedules[asset_identifier]
            if schedule.calendar.uid not in frames:
                frames[schedule.calendar.uid] = schedule.schedule(start, end)
        return frames

    def get_upsampled_data(self) -> pd.DataFrame:
        """Every asset's new bars, upsampled and interpolated.

        The bars come in as many reads as ``_bars_reads`` plans, each within its own
        MetaTables budget, however many assets are new (#155).
        """
        reads = _bars_reads(
            self.get_asset_dimension_range_map_great_or_equal(),
            interval=datetime.timedelta(minutes=string_frequency_to_minutes(self.bar_frequency_id)),
            now=datetime.datetime.now(datetime.UTC),
        )
        frames = [
            self.bars_ts.get_df_between_dates(
                dimension_range_map=read,
                page_size=BARS_READ_PAGE_SIZE,
            )
            for read in reads
        ]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            self.logger.info("No new data to interpolate")
            return pd.DataFrame()
        raw_data_df = pd.concat(frames) if len(frames) > 1 else frames[0]

        upsampled_df = self._transform_raw_data_to_upsampled_df(
            raw_data_df.reset_index([ASSET_IDENTIFIER_DIMENSION])
        )
        return upsampled_df

    def get_asset_list(self):
        """The assets to interpolate: the configuration's list, its category's assets, or
        else the source updater's (#145).

        An update resolves every asset's trading calendar before it reads a bar, so the
        assets are a list; a source whose own ``get_asset_list()`` is None is refused.
        """
        if self.constructor_asset_list is not None:
            asset_list = self.constructor_asset_list
        elif self.asset_category_unique_id is not None:
            asset_list = require_asset_category_scope(
                asset_list=None,
                asset_category_unique_id=self.asset_category_unique_id,
                context="InterpolatedPrices",
            )
        else:
            asset_list = self.bars_ts.get_asset_list()
            if asset_list is None:
                raise ValueError(
                    "InterpolatedPrices takes its assets from its source when it has no "
                    "asset_list or asset_category_unique_id, and the source "
                    f"{self.bars_ts.__class__.__name__} has none. Give InterpolatedPrices "
                    "an asset_list or asset_category_unique_id, or give the source an "
                    "asset_list."
                )

        return asset_list

    def update(self) -> pd.DataFrame:
        """
        Updates the series from the source based on the latest value.
        """
        us: UpdateStatistics = self.update_statistics

        # Resolved before any bar is read: an asset with no trading calendar fails the run.
        self.asset_schedules = _asset_schedule_map(self.get_update_asset_list() or [])
        prices = self.get_upsampled_data()
        if prices.shape[0] == 0:
            return pd.DataFrame()

        if us.are_all_identities_on_fallback_date:
            TARGET_COLS = ["open", "close", "high", "low", "volume", "open_time"]
            assert prices[[c for c in prices.columns if c in TARGET_COLS]].isnull().sum().sum() == 0

        prices = self.update_statistics.filter_df_by_latest_value(prices)

        duplicates_exist = (
            prices.reset_index().duplicated(subset=["time_index", ASSET_IDENTIFIER_DIMENSION]).any()
        )
        if duplicates_exist:
            raise Exception()

        # adapt to InterpolatedPrices data schema
        if "vwap" not in prices.columns:
            self.logger.warning("vwap not calculated in prices, set to NaN")
            prices["vwap"] = np.nan
        if "trade_count" not in prices.columns:
            self.logger.warning("trade_count not calculated in prices, set to NaN")
            prices["trade_count"] = np.nan

        prices = prices[
            [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
                "interpolated",
            ]
        ]
        return _normalize_time_indexed_frame_ns_utc(prices)
