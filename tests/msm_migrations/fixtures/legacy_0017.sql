-- Schema-only fixture: replayed original revisions 0001-0017 from
-- MainSequenceMarkets commit 29dc96b693baa321dd8a0254c885407428378597.
-- No production data, ownership, or privileges are included.
--
-- PostgreSQL database dump
--

-- Dumped from database version 14.15 (Homebrew)
-- Dumped by pg_dump version 14.15 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ms_markets__account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__account (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    account_name character varying(255) NOT NULL,
    is_paper boolean NOT NULL,
    account_is_active boolean NOT NULL,
    account_group_uid uuid,
    holdings_data_node_uid uuid,
    metadata_json json
);


--
-- Name: ms_markets__accountallocationmodel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__accountallocationmodel (
    uid uuid NOT NULL,
    allocation_model_name character varying(100) NOT NULL,
    allocation_model_description text,
    metadata_json json
);


--
-- Name: ms_markets__accountgroup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__accountgroup (
    uid uuid NOT NULL,
    group_name character varying(100),
    group_description text,
    metadata_json json
);


--
-- Name: ms_markets__accountholdingsset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__accountholdingsset (
    uid uuid NOT NULL,
    account_uid uuid NOT NULL,
    time_index timestamp with time zone NOT NULL,
    source_data_node_uid uuid
);


--
-- Name: ms_markets__accountholdingsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__accountholdingsts (
    time_index timestamp with time zone NOT NULL,
    account_uid uuid NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    holdings_set_uid uuid NOT NULL,
    is_trade_snapshot boolean,
    quantity double precision,
    direction smallint NOT NULL,
    target_trade_time timestamp with time zone,
    extra_details jsonb,
    CONSTRAINT ck__ms_markets__accountholdingsts__ck_account_holdin_5ad266251b CHECK ((direction = ANY (ARRAY[1, '-1'::integer])))
);


--
-- Name: ms_markets__accounttargetallocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__accounttargetallocation (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    account_uid uuid NOT NULL,
    account_allocation_model_uid uuid NOT NULL,
    display_name character varying(255),
    is_active boolean NOT NULL,
    source character varying(255),
    metadata_json json
);


--
-- Name: ms_markets__alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: ms_markets__asset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__asset (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    asset_type character varying(64)
);


--
-- Name: ms_markets__assetcategory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assetcategory (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    metadata_json json
);


--
-- Name: ms_markets__assetcategorymembership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assetcategorymembership (
    uid uuid NOT NULL,
    category_uid uuid NOT NULL,
    asset_uid uuid NOT NULL
);


--
-- Name: ms_markets__assetcurrentpricingdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assetcurrentpricingdetails (
    asset_uid uuid NOT NULL,
    instrument_type character varying(128) NOT NULL,
    instrument_dump json NOT NULL,
    pricing_details_date timestamp with time zone NOT NULL,
    serialization_format character varying(128) NOT NULL,
    pricing_package_version character varying(64),
    source character varying(255),
    metadata json
);


--
-- Name: ms_markets__assetpricingdetailsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assetpricingdetailsts (
    time_index timestamp with time zone NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    instrument_dump jsonb NOT NULL,
    instrument_type character varying(128) NOT NULL,
    serialization_format character varying(128) NOT NULL,
    pricing_package_version character varying(64),
    source character varying(255),
    metadata jsonb
);


--
-- Name: ms_markets__assetsnapshotsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assetsnapshotsts (
    time_index timestamp with time zone NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    name character varying,
    ticker character varying,
    exchange_code character varying,
    asset_ticker_group_id character varying
);


--
-- Name: ms_markets__assettype; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__assettype (
    uid uuid NOT NULL,
    asset_type character varying(64) NOT NULL,
    display_name character varying(255),
    description text,
    metadata_json json
);


--
-- Name: ms_markets__bondassetdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__bondassetdetails (
    asset_uid uuid NOT NULL,
    issuer_uid uuid NOT NULL,
    currency_asset_uid uuid NOT NULL,
    issue_date date NOT NULL,
    maturity_date date,
    status character varying(32) NOT NULL
);


--
-- Name: ms_markets__calendar; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__calendar (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    calendar_type character varying(64) NOT NULL,
    timezone character varying(64) NOT NULL,
    source character varying(128),
    source_identifier character varying(255),
    valid_from date NOT NULL,
    valid_to date NOT NULL,
    metadata_json json
);


--
-- Name: ms_markets__calendardate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__calendardate (
    uid uuid NOT NULL,
    calendar_uid uuid NOT NULL,
    local_date date NOT NULL,
    is_business_day boolean NOT NULL,
    is_holiday boolean NOT NULL,
    is_weekend boolean NOT NULL,
    is_early_close boolean NOT NULL,
    holiday_name character varying(255),
    metadata_json json
);


--
-- Name: ms_markets__calendarevent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__calendarevent (
    uid uuid NOT NULL,
    calendar_uid uuid NOT NULL,
    event_date date,
    event_time timestamp with time zone,
    event_type character varying(64) NOT NULL,
    event_label character varying(255) NOT NULL,
    target_type character varying(64) NOT NULL,
    target_uid uuid,
    target_identifier character varying(255) NOT NULL,
    metadata_json json
);


--
-- Name: ms_markets__calendarsession; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__calendarsession (
    uid uuid NOT NULL,
    calendar_uid uuid NOT NULL,
    local_date date NOT NULL,
    session_label character varying(64) NOT NULL,
    opens_at timestamp with time zone,
    closes_at timestamp with time zone,
    timezone character varying(64) NOT NULL,
    is_primary boolean NOT NULL,
    metadata_json json
);


--
-- Name: ms_markets__currencyspotassetdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__currencyspotassetdetails (
    asset_uid uuid NOT NULL,
    base_currency_uid uuid NOT NULL,
    quote_currency_uid uuid NOT NULL
);


--
-- Name: ms_markets__curve; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__curve (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    curve_type character varying(64) NOT NULL,
    interpolation_method character varying(64),
    compounding character varying(64),
    source character varying(255),
    metadata json,
    currency_code character varying(16),
    quote_side character varying(32),
    status character varying(32) NOT NULL
);


--
-- Name: ms_markets__curvebuildingdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__curvebuildingdetails (
    curve_uid uuid NOT NULL,
    builder_type character varying(64) NOT NULL,
    quote_convention character varying(64) NOT NULL,
    rate_unit character varying(32) NOT NULL,
    day_counter_code character varying(64) NOT NULL,
    calendar_code character varying(64) NOT NULL,
    interpolation_method character varying(64) NOT NULL,
    compounding character varying(64) NOT NULL,
    compounding_frequency character varying(64),
    extrapolation_policy character varying(64) NOT NULL,
    bootstrap_method character varying(64),
    builder_payload json,
    source character varying(255),
    metadata json
);


--
-- Name: ms_markets__discountcurvests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__discountcurvests (
    time_index timestamp with time zone NOT NULL,
    curve_identifier character varying(255) NOT NULL,
    curve character varying NOT NULL,
    key_nodes text,
    metadata_json jsonb
);


--
-- Name: ms_markets__externalpricests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__externalpricests (
    time_index timestamp with time zone NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    open_time timestamp with time zone,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    trade_count double precision,
    vwap double precision,
    interpolated boolean
);


--
-- Name: ms_markets__futureassetdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__futureassetdetails (
    asset_uid uuid NOT NULL,
    kind character varying(32) NOT NULL,
    underlying_index_uid uuid NOT NULL,
    quote_unit character varying(64) NOT NULL,
    settlement_asset uuid NOT NULL,
    margin_asset uuid NOT NULL,
    settlement_model character varying(32) NOT NULL,
    settlement_method character varying(32) NOT NULL,
    contract_size numeric(38,18) NOT NULL,
    contract_unit character varying(64) NOT NULL,
    expires_at timestamp with time zone,
    settles_at timestamp with time zone,
    metadata json
);


--
-- Name: ms_markets__index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__index (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    index_type character varying(64) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    metadata_json json,
    calculation_method character varying(16) NOT NULL,
    value_format character varying(16) NOT NULL,
    value_suffix character varying(32),
    CONSTRAINT ck__ms_markets__index__index_calculation_method_valid CHECK (((calculation_method)::text = ANY ((ARRAY['formula'::character varying, 'custom'::character varying])::text[]))),
    CONSTRAINT ck__ms_markets__index__index_value_format_valid CHECK (((value_format)::text = ANY ((ARRAY['decimal'::character varying, 'percent'::character varying])::text[])))
);


--
-- Name: ms_markets__indexconventiondetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexconventiondetails (
    index_uid uuid NOT NULL,
    index_family character varying(64) NOT NULL,
    convention_dump json NOT NULL,
    serialization_format character varying(128) NOT NULL,
    source character varying(255),
    metadata json
);


--
-- Name: ms_markets__indexdatasetavailability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexdatasetavailability (
    uid uuid NOT NULL,
    index_uid uuid NOT NULL,
    meta_table_uid character varying(255) NOT NULL,
    cadence character varying(32) NOT NULL,
    population_state character varying(32) NOT NULL,
    row_count integer,
    earliest_time_index timestamp with time zone,
    latest_time_index timestamp with time zone,
    reconciled_at timestamp with time zone NOT NULL,
    error_code character varying(128),
    error_message character varying(1024),
    CONSTRAINT ck__ms_markets__indexdatasetavailability__dataset_po_13c13b29a7 CHECK (((((population_state)::text = 'populated'::text) AND (row_count > 0) AND (error_code IS NULL) AND (error_message IS NULL)) OR (((population_state)::text = 'compatible_empty'::text) AND (row_count = 0) AND (earliest_time_index IS NULL) AND (latest_time_index IS NULL) AND (error_code IS NULL) AND (error_message IS NULL)) OR (((population_state)::text = 'unavailable'::text) AND (row_count IS NULL) AND (earliest_time_index IS NULL) AND (latest_time_index IS NULL))))
);


--
-- Name: ms_markets__indexfixingsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexfixingsts (
    time_index timestamp with time zone NOT NULL,
    index_identifier character varying(255) NOT NULL,
    rate double precision
);


--
-- Name: ms_markets__indexformuladefinition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexformuladefinition (
    uid uuid NOT NULL,
    index_uid uuid NOT NULL,
    version integer NOT NULL,
    status character varying(32) NOT NULL,
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    formula text NOT NULL,
    alignment_policy character varying(16) NOT NULL,
    alignment_parameters_json json,
    missing_data_policy character varying(16) NOT NULL,
    definition_hash character varying(64) NOT NULL,
    metadata_json json,
    CONSTRAINT ck__ms_markets__indexformuladefinition__formula_alig_8887da6f81 CHECK (((alignment_policy)::text = ANY ((ARRAY['exact'::character varying, 'asof'::character varying])::text[]))),
    CONSTRAINT ck__ms_markets__indexformuladefinition__formula_miss_d7f6e121c1 CHECK (((missing_data_policy)::text = ANY ((ARRAY['drop'::character varying, 'fail'::character varying])::text[]))),
    CONSTRAINT ck__ms_markets__indexformuladefinition__formula_status_valid CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'retired'::character varying])::text[]))),
    CONSTRAINT ck__ms_markets__indexformuladefinition__formula_vali_65436db46f CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT ck__ms_markets__indexformuladefinition__formula_vers_6b9a2e4d17 CHECK ((version > 0))
);


--
-- Name: ms_markets__indexformulainput; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexformulainput (
    uid uuid NOT NULL,
    definition_uid uuid NOT NULL,
    asset_uid uuid,
    component_index_uid uuid,
    meta_table_uid uuid NOT NULL,
    observable character varying(255) NOT NULL,
    CONSTRAINT ck__ms_markets__indexformulainput__formula_input_sou_276417d9a7 CHECK (((
CASE
    WHEN (asset_uid IS NOT NULL) THEN 1
    ELSE 0
END +
CASE
    WHEN (component_index_uid IS NOT NULL) THEN 1
    ELSE 0
END) = 1))
);


--
-- Name: ms_markets__indextype; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indextype (
    uid uuid NOT NULL,
    index_type character varying(64) NOT NULL,
    display_name character varying(255),
    description text,
    metadata_json json
);


--
-- Name: ms_markets__indexvaluests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__indexvaluests (
    time_index timestamp with time zone NOT NULL,
    index_identifier character varying(255) NOT NULL,
    value double precision NOT NULL,
    definition_uid uuid,
    observation_status character varying(32),
    source_as_of timestamp with time zone,
    metadata_json json
);


--
-- Name: ms_markets__interpolatedpricests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__interpolatedpricests (
    time_index timestamp with time zone NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    open_time timestamp with time zone,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    trade_count double precision,
    vwap double precision,
    interpolated boolean
);


--
-- Name: ms_markets__issuer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__issuer (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    metadata_json json
);


--
-- Name: ms_markets__openfigiassetdetails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__openfigiassetdetails (
    asset_uid uuid NOT NULL,
    figi character varying(12),
    composite character varying(12),
    share_class character varying(12),
    isin character varying(12),
    ticker character varying(50),
    name character varying(255),
    exchange_code character varying(50),
    security_type character varying(50),
    security_type_2 character varying(50),
    security_market_sector character varying(50),
    security_description character varying(255),
    unique_id character varying(255),
    unique_id_fut_opt character varying(255),
    metadata text,
    raw_payload json
);


--
-- Name: ms_markets__ordereventsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__ordereventsts (
    event_time timestamp with time zone NOT NULL,
    order_identifier character varying NOT NULL,
    order_status character varying,
    event_metadata jsonb
);


--
-- Name: ms_markets__ordermanager; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__ordermanager (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    target_account_uid uuid NOT NULL,
    target_time timestamp with time zone NOT NULL,
    order_received_time timestamp with time zone,
    execution_end timestamp with time zone,
    status character varying(64),
    metadata_json json
);


--
-- Name: ms_markets__ordersts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__ordersts (
    order_time timestamp with time zone NOT NULL,
    order_identifier character varying NOT NULL,
    account_identifier character varying NOT NULL,
    order_manager_identifier character varying,
    asset_identifier character varying NOT NULL,
    order_remote_id character varying,
    client_order_id character varying,
    order_type character varying,
    order_side bigint,
    quantity double precision,
    status character varying,
    filled_quantity double precision,
    filled_price double precision,
    expires_time timestamp with time zone,
    limit_price double precision,
    time_in_force character varying,
    comments character varying,
    venue_metadata jsonb
);


--
-- Name: ms_markets__portfolio; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfolio (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    calendar_uid uuid NOT NULL,
    published_index_uid uuid,
    portfolio_weights_data_node_uid uuid,
    signal_weights_data_node_uid uuid,
    portfolio_data_node_uid uuid,
    backtest_table_price_column_name character varying(20) NOT NULL,
    signal_uid character varying(255)
);


--
-- Name: ms_markets__portfolioanalyticsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfolioanalyticsts (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    analysis_identifier character varying(255) NOT NULL,
    close double precision,
    return double precision,
    source_time_index timestamp with time zone NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL
);


--
-- Name: ms_markets__portfoliocalendareventsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliocalendareventsts (
    time_index timestamp with time zone NOT NULL,
    calendar_identifier character varying(255) NOT NULL,
    session_label character varying(64) NOT NULL,
    event_type character varying(32) NOT NULL,
    local_date character varying(10) NOT NULL
);


--
-- Name: ms_markets__portfoliocashflowsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliocashflowsts (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    cash_flow_identifier character varying(64) NOT NULL,
    ledger_state_identifier character varying(64) NOT NULL,
    event_identifier character varying(64) NOT NULL,
    cash_flow_type character varying(64) NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    amount double precision NOT NULL,
    valuation_amount double precision,
    valuation_asset_identifier character varying(255)
);


--
-- Name: ms_markets__portfolioeventledgerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfolioeventledgerts (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    event_identifier character varying(64) NOT NULL,
    event_revision character varying(64) NOT NULL,
    record_identifier character varying(64) NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    event_type character varying(64) NOT NULL,
    event_status character varying(32) NOT NULL,
    phase character varying(32) NOT NULL,
    event_sequence bigint NOT NULL,
    record_sequence bigint NOT NULL,
    event_record_count integer NOT NULL,
    event_digest character varying(64) NOT NULL,
    source_identifier character varying(255) NOT NULL,
    source_revision character varying(255) NOT NULL,
    model_identifier character varying(255) NOT NULL,
    model_version character varying(64) NOT NULL,
    supersedes_event_revision character varying(64),
    causal_event_identifiers text,
    input_state_identifier character varying(64) NOT NULL,
    ledger_state_identifier character varying(64) NOT NULL,
    terms_version character varying(255),
    valuation_references text NOT NULL,
    record_kind character varying(32) NOT NULL,
    position_identifier character varying(255),
    obligation_identifier character varying(255),
    state_identifier character varying(255),
    asset_identifier character varying(255),
    balance_role character varying(64),
    quantity_delta double precision,
    quantity_unit character varying(64),
    amount_delta double precision,
    amount_asset_identifier character varying(255),
    price double precision,
    price_asset_identifier character varying(255),
    eligible_quantity double precision,
    recognized_pnl double precision,
    nav_before double precision,
    nav_after double precision,
    valuation_asset_identifier character varying(255),
    state_schema_version integer,
    extension_payload text
);


--
-- Name: ms_markets__portfoliogroup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliogroup (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    metadata_json json
);


--
-- Name: ms_markets__portfoliogroupmembership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliogroupmembership (
    uid uuid NOT NULL,
    portfolio_group_uid uuid NOT NULL,
    portfolio_uid uuid NOT NULL
);


--
-- Name: ms_markets__portfoliometadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliometadata (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    description text
);


--
-- Name: ms_markets__portfoliorebalancestatets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliorebalancestatets (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    rebalance_intent_id character varying(64) NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    target_signal_time_index timestamp with time zone NOT NULL,
    event_source character varying(255) NOT NULL,
    execution_status character varying(32) NOT NULL,
    target_weight double precision NOT NULL,
    weight_before double precision NOT NULL,
    weight_after double precision NOT NULL,
    executed_weight_delta double precision NOT NULL,
    remaining_weight_delta double precision NOT NULL,
    execution_price double precision,
    executed_quantity double precision,
    executed_notional double precision,
    observed_volume double precision,
    observed_available_liquidity double precision,
    strategy_state text NOT NULL
);


--
-- Name: ms_markets__portfoliostatets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliostatets (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    state_identifier character varying(255) NOT NULL,
    ledger_state_identifier character varying(64) NOT NULL,
    originating_event_identifier character varying(64) NOT NULL,
    state_kind character varying(32) NOT NULL,
    asset_identifier character varying(255),
    balance_role character varying(64),
    quantity double precision,
    quantity_unit character varying(64),
    value double precision,
    valuation_asset_identifier character varying(255),
    is_closed boolean NOT NULL,
    extension_payload text
);


--
-- Name: ms_markets__portfoliosts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfoliosts (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying(255) NOT NULL,
    close double precision,
    return double precision,
    calculated_close double precision,
    close_time timestamp with time zone
);


--
-- Name: ms_markets__portfolioweightsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__portfolioweightsts (
    time_index timestamp with time zone NOT NULL,
    portfolio_identifier character varying NOT NULL,
    asset_identifier character varying NOT NULL,
    weight double precision,
    weight_before double precision,
    price_current double precision,
    price_before double precision,
    volume_current double precision,
    volume_before double precision
);


--
-- Name: ms_markets__positionset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__positionset (
    uid uuid NOT NULL,
    account_target_allocation_uid uuid NOT NULL,
    position_set_time timestamp with time zone NOT NULL,
    source character varying(255),
    metadata_json json
);


--
-- Name: ms_markets__pricingmarketdataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__pricingmarketdataset (
    uid uuid NOT NULL,
    set_key character varying(64) NOT NULL,
    display_name character varying(255) NOT NULL,
    description text,
    status character varying(32) NOT NULL,
    metadata json
);


--
-- Name: ms_markets__pricingmarketdatasetbinding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__pricingmarketdatasetbinding (
    uid uuid NOT NULL,
    market_data_set_uid uuid NOT NULL,
    concept_key character varying(128) NOT NULL,
    data_node_uid uuid NOT NULL,
    storage_table_identifier character varying(255),
    source character varying(255),
    metadata json
);


--
-- Name: ms_markets__pricingmarketdatasetcurvebinding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__pricingmarketdatasetcurvebinding (
    uid uuid NOT NULL,
    market_data_set_uid uuid NOT NULL,
    binding_key character varying(255) NOT NULL,
    role_key character varying(64) NOT NULL,
    selector_type character varying(64) NOT NULL,
    selector_key character varying(255) NOT NULL,
    quote_side character varying(32),
    curve_uid uuid NOT NULL,
    source character varying(255),
    priority integer NOT NULL,
    status character varying(32) NOT NULL,
    metadata json
);


--
-- Name: ms_markets__rebalancestrategymetadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__rebalancestrategymetadata (
    uid uuid NOT NULL,
    rebalance_strategy_uid character varying(255) NOT NULL,
    rebalance_strategy_description text,
    configuration_json json
);


--
-- Name: ms_markets__signalmetadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__signalmetadata (
    uid uuid NOT NULL,
    signal_uid character varying(255) NOT NULL,
    signal_description text
);


--
-- Name: ms_markets__signalweightsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__signalweightsts (
    time_index timestamp with time zone NOT NULL,
    signal_uid character varying(255) NOT NULL,
    asset_identifier character varying NOT NULL,
    signal_weight double precision
);


--
-- Name: ms_markets__targetpositionsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__targetpositionsts (
    time_index timestamp with time zone NOT NULL,
    position_set_uid uuid NOT NULL,
    target_type character varying(32) NOT NULL,
    target_uid uuid NOT NULL,
    asset_uid uuid,
    portfolio_uid uuid,
    weight_notional_exposure double precision,
    constant_notional_exposure double precision,
    single_asset_quantity double precision,
    metadata_json jsonb,
    CONSTRAINT ck__ms_markets__targetpositionsts__ck_target_positio_3daf2e6c82 CHECK (((target_type)::text = ANY ((ARRAY['asset'::character varying, 'portfolio'::character varying])::text[]))),
    CONSTRAINT ck__ms_markets__targetpositionsts__ck_target_positio_76b533764b CHECK ((((
CASE
    WHEN (weight_notional_exposure IS NOT NULL) THEN 1
    ELSE 0
END +
CASE
    WHEN (constant_notional_exposure IS NOT NULL) THEN 1
    ELSE 0
END) +
CASE
    WHEN (single_asset_quantity IS NOT NULL) THEN 1
    ELSE 0
END) = 1)),
    CONSTRAINT ck__ms_markets__targetpositionsts__ck_target_positio_804f77878f CHECK (((((target_type)::text = 'asset'::text) AND (asset_uid IS NOT NULL) AND (portfolio_uid IS NULL) AND (target_uid = asset_uid)) OR (((target_type)::text = 'portfolio'::text) AND (portfolio_uid IS NOT NULL) AND (asset_uid IS NULL) AND (target_uid = portfolio_uid))))
);


--
-- Name: ms_markets__tradests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__tradests (
    trade_time timestamp with time zone NOT NULL,
    trade_identifier character varying NOT NULL,
    account_identifier character varying NOT NULL,
    order_identifier character varying,
    asset_identifier character varying NOT NULL,
    trade_side bigint,
    quantity double precision,
    price double precision,
    commission double precision,
    commission_asset_identifier character varying,
    settlement_cost double precision,
    settlement_asset_identifier character varying,
    comments character varying,
    venue_metadata jsonb
);


--
-- Name: ms_markets__virtualfund; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__virtualfund (
    uid uuid NOT NULL,
    unique_identifier character varying(255) NOT NULL,
    account_uid uuid NOT NULL,
    target_portfolio_uid uuid NOT NULL
);


--
-- Name: ms_markets__virtualfundholdingsset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__virtualfundholdingsset (
    uid uuid NOT NULL,
    virtual_fund_uid uuid NOT NULL,
    source_account_holdings_set_uid uuid NOT NULL,
    time_index timestamp with time zone NOT NULL
);


--
-- Name: ms_markets__virtualfundholdingsts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ms_markets__virtualfundholdingsts (
    time_index timestamp with time zone NOT NULL,
    virtual_fund_uid uuid NOT NULL,
    asset_identifier character varying(255) NOT NULL,
    virtual_fund_holdings_set_uid uuid NOT NULL,
    source_account_holdings_set_uid uuid NOT NULL,
    allocated_quantity double precision NOT NULL,
    allocation_strategy character varying(64) NOT NULL,
    direction smallint NOT NULL,
    target_trade_time timestamp with time zone,
    extra_details jsonb,
    CONSTRAINT ck__ms_markets__virtualfundholdingsts__ck_virtual_fu_0baf4f8e22 CHECK ((direction = ANY (ARRAY[1, '-1'::integer])))
);


--
-- Name: ms_markets__alembic_version ms_markets__alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__alembic_version
    ADD CONSTRAINT ms_markets__alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: ms_markets__account pk__ms_markets__account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__account
    ADD CONSTRAINT pk__ms_markets__account PRIMARY KEY (uid);


--
-- Name: ms_markets__accountallocationmodel pk__ms_markets__accountallocationmodel; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountallocationmodel
    ADD CONSTRAINT pk__ms_markets__accountallocationmodel PRIMARY KEY (uid);


--
-- Name: ms_markets__accountgroup pk__ms_markets__accountgroup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountgroup
    ADD CONSTRAINT pk__ms_markets__accountgroup PRIMARY KEY (uid);


--
-- Name: ms_markets__accountholdingsset pk__ms_markets__accountholdingsset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountholdingsset
    ADD CONSTRAINT pk__ms_markets__accountholdingsset PRIMARY KEY (uid);


--
-- Name: ms_markets__accounttargetallocation pk__ms_markets__accounttargetallocation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accounttargetallocation
    ADD CONSTRAINT pk__ms_markets__accounttargetallocation PRIMARY KEY (uid);


--
-- Name: ms_markets__asset pk__ms_markets__asset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__asset
    ADD CONSTRAINT pk__ms_markets__asset PRIMARY KEY (uid);


--
-- Name: ms_markets__assetcategory pk__ms_markets__assetcategory; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcategory
    ADD CONSTRAINT pk__ms_markets__assetcategory PRIMARY KEY (uid);


--
-- Name: ms_markets__assetcategorymembership pk__ms_markets__assetcategorymembership; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcategorymembership
    ADD CONSTRAINT pk__ms_markets__assetcategorymembership PRIMARY KEY (uid);


--
-- Name: ms_markets__assetcurrentpricingdetails pk__ms_markets__assetcurrentpricingdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcurrentpricingdetails
    ADD CONSTRAINT pk__ms_markets__assetcurrentpricingdetails PRIMARY KEY (asset_uid);


--
-- Name: ms_markets__assettype pk__ms_markets__assettype; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assettype
    ADD CONSTRAINT pk__ms_markets__assettype PRIMARY KEY (uid);


--
-- Name: ms_markets__bondassetdetails pk__ms_markets__bondassetdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__bondassetdetails
    ADD CONSTRAINT pk__ms_markets__bondassetdetails PRIMARY KEY (asset_uid);


--
-- Name: ms_markets__calendar pk__ms_markets__calendar; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendar
    ADD CONSTRAINT pk__ms_markets__calendar PRIMARY KEY (uid);


--
-- Name: ms_markets__calendardate pk__ms_markets__calendardate; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendardate
    ADD CONSTRAINT pk__ms_markets__calendardate PRIMARY KEY (uid);


--
-- Name: ms_markets__calendarevent pk__ms_markets__calendarevent; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendarevent
    ADD CONSTRAINT pk__ms_markets__calendarevent PRIMARY KEY (uid);


--
-- Name: ms_markets__calendarsession pk__ms_markets__calendarsession; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendarsession
    ADD CONSTRAINT pk__ms_markets__calendarsession PRIMARY KEY (uid);


--
-- Name: ms_markets__currencyspotassetdetails pk__ms_markets__currencyspotassetdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__currencyspotassetdetails
    ADD CONSTRAINT pk__ms_markets__currencyspotassetdetails PRIMARY KEY (asset_uid);


--
-- Name: ms_markets__curve pk__ms_markets__curve; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__curve
    ADD CONSTRAINT pk__ms_markets__curve PRIMARY KEY (uid);


--
-- Name: ms_markets__curvebuildingdetails pk__ms_markets__curvebuildingdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__curvebuildingdetails
    ADD CONSTRAINT pk__ms_markets__curvebuildingdetails PRIMARY KEY (curve_uid);


--
-- Name: ms_markets__futureassetdetails pk__ms_markets__futureassetdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__futureassetdetails
    ADD CONSTRAINT pk__ms_markets__futureassetdetails PRIMARY KEY (asset_uid);


--
-- Name: ms_markets__index pk__ms_markets__index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__index
    ADD CONSTRAINT pk__ms_markets__index PRIMARY KEY (uid);


--
-- Name: ms_markets__indexconventiondetails pk__ms_markets__indexconventiondetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexconventiondetails
    ADD CONSTRAINT pk__ms_markets__indexconventiondetails PRIMARY KEY (index_uid);


--
-- Name: ms_markets__indexdatasetavailability pk__ms_markets__indexdatasetavailability; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexdatasetavailability
    ADD CONSTRAINT pk__ms_markets__indexdatasetavailability PRIMARY KEY (uid);


--
-- Name: ms_markets__indexformuladefinition pk__ms_markets__indexformuladefinition; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformuladefinition
    ADD CONSTRAINT pk__ms_markets__indexformuladefinition PRIMARY KEY (uid);


--
-- Name: ms_markets__indexformulainput pk__ms_markets__indexformulainput; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformulainput
    ADD CONSTRAINT pk__ms_markets__indexformulainput PRIMARY KEY (uid);


--
-- Name: ms_markets__indextype pk__ms_markets__indextype; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indextype
    ADD CONSTRAINT pk__ms_markets__indextype PRIMARY KEY (uid);


--
-- Name: ms_markets__issuer pk__ms_markets__issuer; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__issuer
    ADD CONSTRAINT pk__ms_markets__issuer PRIMARY KEY (uid);


--
-- Name: ms_markets__openfigiassetdetails pk__ms_markets__openfigiassetdetails; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__openfigiassetdetails
    ADD CONSTRAINT pk__ms_markets__openfigiassetdetails PRIMARY KEY (asset_uid);


--
-- Name: ms_markets__ordermanager pk__ms_markets__ordermanager; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__ordermanager
    ADD CONSTRAINT pk__ms_markets__ordermanager PRIMARY KEY (uid);


--
-- Name: ms_markets__portfolio pk__ms_markets__portfolio; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolio
    ADD CONSTRAINT pk__ms_markets__portfolio PRIMARY KEY (uid);


--
-- Name: ms_markets__portfoliogroup pk__ms_markets__portfoliogroup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliogroup
    ADD CONSTRAINT pk__ms_markets__portfoliogroup PRIMARY KEY (uid);


--
-- Name: ms_markets__portfoliogroupmembership pk__ms_markets__portfoliogroupmembership; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliogroupmembership
    ADD CONSTRAINT pk__ms_markets__portfoliogroupmembership PRIMARY KEY (uid);


--
-- Name: ms_markets__portfoliometadata pk__ms_markets__portfoliometadata; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliometadata
    ADD CONSTRAINT pk__ms_markets__portfoliometadata PRIMARY KEY (uid);


--
-- Name: ms_markets__positionset pk__ms_markets__positionset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__positionset
    ADD CONSTRAINT pk__ms_markets__positionset PRIMARY KEY (uid);


--
-- Name: ms_markets__pricingmarketdataset pk__ms_markets__pricingmarketdataset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdataset
    ADD CONSTRAINT pk__ms_markets__pricingmarketdataset PRIMARY KEY (uid);


--
-- Name: ms_markets__pricingmarketdatasetbinding pk__ms_markets__pricingmarketdatasetbinding; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdatasetbinding
    ADD CONSTRAINT pk__ms_markets__pricingmarketdatasetbinding PRIMARY KEY (uid);


--
-- Name: ms_markets__pricingmarketdatasetcurvebinding pk__ms_markets__pricingmarketdatasetcurvebinding; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdatasetcurvebinding
    ADD CONSTRAINT pk__ms_markets__pricingmarketdatasetcurvebinding PRIMARY KEY (uid);


--
-- Name: ms_markets__rebalancestrategymetadata pk__ms_markets__rebalancestrategymetadata; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__rebalancestrategymetadata
    ADD CONSTRAINT pk__ms_markets__rebalancestrategymetadata PRIMARY KEY (uid);


--
-- Name: ms_markets__signalmetadata pk__ms_markets__signalmetadata; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__signalmetadata
    ADD CONSTRAINT pk__ms_markets__signalmetadata PRIMARY KEY (uid);


--
-- Name: ms_markets__virtualfund pk__ms_markets__virtualfund; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfund
    ADD CONSTRAINT pk__ms_markets__virtualfund PRIMARY KEY (uid);


--
-- Name: ms_markets__virtualfundholdingsset pk__ms_markets__virtualfundholdingsset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsset
    ADD CONSTRAINT pk__ms_markets__virtualfundholdingsset PRIMARY KEY (uid);


--
-- Name: ms_markets__portfolioeventledgerts uq__ms_markets__portfolioeventledgerts__portfolio_id_256b1e63f2; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT uq__ms_markets__portfolioeventledgerts__portfolio_id_256b1e63f2 UNIQUE (portfolio_identifier, event_identifier, event_revision, record_identifier);


--
-- Name: ix__ms_markets__account__account_group_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__account__account_group_uid ON public.ms_markets__account USING btree (account_group_uid);


--
-- Name: ix__ms_markets__account__account_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__account__account_is_active ON public.ms_markets__account USING btree (account_is_active);


--
-- Name: ix__ms_markets__account__account_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__account__account_name ON public.ms_markets__account USING btree (account_name);


--
-- Name: ix__ms_markets__accountholdingsset__account_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__accountholdingsset__account_uid ON public.ms_markets__accountholdingsset USING btree (account_uid);


--
-- Name: ix__ms_markets__accountholdingsset__time_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__accountholdingsset__time_index ON public.ms_markets__accountholdingsset USING btree (time_index);


--
-- Name: ix__ms_markets__accounttargetallocation__account_all_f241db4002; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__accounttargetallocation__account_all_f241db4002 ON public.ms_markets__accounttargetallocation USING btree (account_allocation_model_uid);


--
-- Name: ix__ms_markets__accounttargetallocation__account_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__accounttargetallocation__account_uid ON public.ms_markets__accounttargetallocation USING btree (account_uid);


--
-- Name: ix__ms_markets__accounttargetallocation__is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__accounttargetallocation__is_active ON public.ms_markets__accounttargetallocation USING btree (is_active);


--
-- Name: ix__ms_markets__asset__asset_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__asset__asset_type ON public.ms_markets__asset USING btree (asset_type);


--
-- Name: ix__ms_markets__assetcategory__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__assetcategory__display_name ON public.ms_markets__assetcategory USING btree (display_name);


--
-- Name: ix__ms_markets__assetcategorymembership__asset_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__assetcategorymembership__asset_uid ON public.ms_markets__assetcategorymembership USING btree (asset_uid);


--
-- Name: ix__ms_markets__assetcurrentpricingdetails__instrument_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__assetcurrentpricingdetails__instrument_type ON public.ms_markets__assetcurrentpricingdetails USING btree (instrument_type);


--
-- Name: ix__ms_markets__assetcurrentpricingdetails__pricing_dc942ad94f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__assetcurrentpricingdetails__pricing_dc942ad94f ON public.ms_markets__assetcurrentpricingdetails USING btree (pricing_details_date);


--
-- Name: ix__ms_markets__assettype__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__assettype__display_name ON public.ms_markets__assettype USING btree (display_name);


--
-- Name: ix__ms_markets__bondassetdetails__currency_asset_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__bondassetdetails__currency_asset_uid ON public.ms_markets__bondassetdetails USING btree (currency_asset_uid);


--
-- Name: ix__ms_markets__bondassetdetails__issuer_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__bondassetdetails__issuer_uid ON public.ms_markets__bondassetdetails USING btree (issuer_uid);


--
-- Name: ix__ms_markets__bondassetdetails__maturity_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__bondassetdetails__maturity_date ON public.ms_markets__bondassetdetails USING btree (maturity_date);


--
-- Name: ix__ms_markets__bondassetdetails__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__bondassetdetails__status ON public.ms_markets__bondassetdetails USING btree (status);


--
-- Name: ix__ms_markets__calendar__calendar_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendar__calendar_type ON public.ms_markets__calendar USING btree (calendar_type);


--
-- Name: ix__ms_markets__calendar__source__source_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendar__source__source_identifier ON public.ms_markets__calendar USING btree (source, source_identifier);


--
-- Name: ix__ms_markets__calendardate__calendar_uid__is_business_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendardate__calendar_uid__is_business_day ON public.ms_markets__calendardate USING btree (calendar_uid, is_business_day);


--
-- Name: ix__ms_markets__calendardate__local_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendardate__local_date ON public.ms_markets__calendardate USING btree (local_date);


--
-- Name: ix__ms_markets__calendarevent__calendar_uid__event_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendarevent__calendar_uid__event_date ON public.ms_markets__calendarevent USING btree (calendar_uid, event_date);


--
-- Name: ix__ms_markets__calendarevent__event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendarevent__event_type ON public.ms_markets__calendarevent USING btree (event_type);


--
-- Name: ix__ms_markets__calendarevent__target_type__target_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendarevent__target_type__target_uid ON public.ms_markets__calendarevent USING btree (target_type, target_uid);


--
-- Name: ix__ms_markets__calendarsession__calendar_uid__is_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendarsession__calendar_uid__is_primary ON public.ms_markets__calendarsession USING btree (calendar_uid, is_primary);


--
-- Name: ix__ms_markets__calendarsession__local_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__calendarsession__local_date ON public.ms_markets__calendarsession USING btree (local_date);


--
-- Name: ix__ms_markets__currencyspotassetdetails__base_currency_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__currencyspotassetdetails__base_currency_uid ON public.ms_markets__currencyspotassetdetails USING btree (base_currency_uid);


--
-- Name: ix__ms_markets__currencyspotassetdetails__quote_currency_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__currencyspotassetdetails__quote_currency_uid ON public.ms_markets__currencyspotassetdetails USING btree (quote_currency_uid);


--
-- Name: ix__ms_markets__curve__currency_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curve__currency_code ON public.ms_markets__curve USING btree (currency_code);


--
-- Name: ix__ms_markets__curve__curve_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curve__curve_type ON public.ms_markets__curve USING btree (curve_type);


--
-- Name: ix__ms_markets__curve__quote_side; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curve__quote_side ON public.ms_markets__curve USING btree (quote_side);


--
-- Name: ix__ms_markets__curve__source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curve__source ON public.ms_markets__curve USING btree (source);


--
-- Name: ix__ms_markets__curve__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curve__status ON public.ms_markets__curve USING btree (status);


--
-- Name: ix__ms_markets__curvebuildingdetails__builder_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curvebuildingdetails__builder_type ON public.ms_markets__curvebuildingdetails USING btree (builder_type);


--
-- Name: ix__ms_markets__curvebuildingdetails__quote_convention; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curvebuildingdetails__quote_convention ON public.ms_markets__curvebuildingdetails USING btree (quote_convention);


--
-- Name: ix__ms_markets__curvebuildingdetails__source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__curvebuildingdetails__source ON public.ms_markets__curvebuildingdetails USING btree (source);


--
-- Name: ix__ms_markets__futureassetdetails__expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__futureassetdetails__expires_at ON public.ms_markets__futureassetdetails USING btree (expires_at);


--
-- Name: ix__ms_markets__futureassetdetails__margin_asset; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__futureassetdetails__margin_asset ON public.ms_markets__futureassetdetails USING btree (margin_asset);


--
-- Name: ix__ms_markets__futureassetdetails__settlement_asset; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__futureassetdetails__settlement_asset ON public.ms_markets__futureassetdetails USING btree (settlement_asset);


--
-- Name: ix__ms_markets__futureassetdetails__underlying_index_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__futureassetdetails__underlying_index_uid ON public.ms_markets__futureassetdetails USING btree (underlying_index_uid);


--
-- Name: ix__ms_markets__index__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__index__display_name ON public.ms_markets__index USING btree (display_name);


--
-- Name: ix__ms_markets__index__index_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__index__index_type ON public.ms_markets__index USING btree (index_type);


--
-- Name: ix__ms_markets__indexconventiondetails__index_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexconventiondetails__index_family ON public.ms_markets__indexconventiondetails USING btree (index_family);


--
-- Name: ix__ms_markets__indexconventiondetails__source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexconventiondetails__source ON public.ms_markets__indexconventiondetails USING btree (source);


--
-- Name: ix__ms_markets__indexdatasetavailability__index_uid_3ff71269ef; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexdatasetavailability__index_uid_3ff71269ef ON public.ms_markets__indexdatasetavailability USING btree (index_uid, population_state, cadence);


--
-- Name: ix__ms_markets__indexdatasetavailability__population_149bb7907d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexdatasetavailability__population_149bb7907d ON public.ms_markets__indexdatasetavailability USING btree (population_state, cadence, index_uid);


--
-- Name: ix__ms_markets__indexformuladefinition__index_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformuladefinition__index_uid ON public.ms_markets__indexformuladefinition USING btree (index_uid);


--
-- Name: ix__ms_markets__indexformuladefinition__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformuladefinition__status ON public.ms_markets__indexformuladefinition USING btree (status);


--
-- Name: ix__ms_markets__indexformuladefinition__valid_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformuladefinition__valid_from ON public.ms_markets__indexformuladefinition USING btree (valid_from);


--
-- Name: ix__ms_markets__indexformulainput__asset_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformulainput__asset_uid ON public.ms_markets__indexformulainput USING btree (asset_uid);


--
-- Name: ix__ms_markets__indexformulainput__component_index_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformulainput__component_index_uid ON public.ms_markets__indexformulainput USING btree (component_index_uid);


--
-- Name: ix__ms_markets__indexformulainput__definition_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformulainput__definition_uid ON public.ms_markets__indexformulainput USING btree (definition_uid);


--
-- Name: ix__ms_markets__indexformulainput__meta_table_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexformulainput__meta_table_uid ON public.ms_markets__indexformulainput USING btree (meta_table_uid);


--
-- Name: ix__ms_markets__indextype__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indextype__display_name ON public.ms_markets__indextype USING btree (display_name);


--
-- Name: ix__ms_markets__indexvaluests__definition_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexvaluests__definition_uid ON public.ms_markets__indexvaluests USING btree (definition_uid);


--
-- Name: ix__ms_markets__indexvaluests__index_identifier__time_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexvaluests__index_identifier__time_index ON public.ms_markets__indexvaluests USING btree (index_identifier, time_index);


--
-- Name: ix__ms_markets__indexvaluests__observation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__indexvaluests__observation_status ON public.ms_markets__indexvaluests USING btree (observation_status);


--
-- Name: ix__ms_markets__issuer__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__issuer__display_name ON public.ms_markets__issuer USING btree (display_name);


--
-- Name: ix__ms_markets__openfigiassetdetails__figi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__openfigiassetdetails__figi ON public.ms_markets__openfigiassetdetails USING btree (figi);


--
-- Name: ix__ms_markets__openfigiassetdetails__isin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__openfigiassetdetails__isin ON public.ms_markets__openfigiassetdetails USING btree (isin);


--
-- Name: ix__ms_markets__openfigiassetdetails__ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__openfigiassetdetails__ticker ON public.ms_markets__openfigiassetdetails USING btree (ticker);


--
-- Name: ix__ms_markets__ordermanager__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__ordermanager__status ON public.ms_markets__ordermanager USING btree (status);


--
-- Name: ix__ms_markets__ordermanager__target_account_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__ordermanager__target_account_uid ON public.ms_markets__ordermanager USING btree (target_account_uid);


--
-- Name: ix__ms_markets__portfolio__calendar_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfolio__calendar_uid ON public.ms_markets__portfolio USING btree (calendar_uid);


--
-- Name: ix__ms_markets__portfolio__published_index_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfolio__published_index_uid ON public.ms_markets__portfolio USING btree (published_index_uid);


--
-- Name: ix__ms_markets__portfolio__signal_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfolio__signal_uid ON public.ms_markets__portfolio USING btree (signal_uid);


--
-- Name: ix__ms_markets__portfoliogroup__display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfoliogroup__display_name ON public.ms_markets__portfoliogroup USING btree (display_name);


--
-- Name: ix__ms_markets__portfoliogroupmembership__portfolio_group_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfoliogroupmembership__portfolio_group_uid ON public.ms_markets__portfoliogroupmembership USING btree (portfolio_group_uid);


--
-- Name: ix__ms_markets__portfoliogroupmembership__portfolio_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__portfoliogroupmembership__portfolio_uid ON public.ms_markets__portfoliogroupmembership USING btree (portfolio_uid);


--
-- Name: ix__ms_markets__positionset__account_target_allocation_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__positionset__account_target_allocation_uid ON public.ms_markets__positionset USING btree (account_target_allocation_uid);


--
-- Name: ix__ms_markets__positionset__position_set_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__positionset__position_set_time ON public.ms_markets__positionset USING btree (position_set_time);


--
-- Name: ix__ms_markets__pricingmarketdataset__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdataset__status ON public.ms_markets__pricingmarketdataset USING btree (status);


--
-- Name: ix__ms_markets__pricingmarketdatasetbinding__concept_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetbinding__concept_key ON public.ms_markets__pricingmarketdatasetbinding USING btree (concept_key);


--
-- Name: ix__ms_markets__pricingmarketdatasetbinding__data_node_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetbinding__data_node_uid ON public.ms_markets__pricingmarketdatasetbinding USING btree (data_node_uid);


--
-- Name: ix__ms_markets__pricingmarketdatasetcurvebinding__curve_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetcurvebinding__curve_uid ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (curve_uid);


--
-- Name: ix__ms_markets__pricingmarketdatasetcurvebinding__quote_side; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetcurvebinding__quote_side ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (quote_side);


--
-- Name: ix__ms_markets__pricingmarketdatasetcurvebinding__role_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetcurvebinding__role_key ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (role_key);


--
-- Name: ix__ms_markets__pricingmarketdatasetcurvebinding__se_c122951238; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetcurvebinding__se_c122951238 ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (selector_type, selector_key);


--
-- Name: ix__ms_markets__pricingmarketdatasetcurvebinding__status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__pricingmarketdatasetcurvebinding__status ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (status);


--
-- Name: ix__ms_markets__targetpositionsts__asset_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__targetpositionsts__asset_uid ON public.ms_markets__targetpositionsts USING btree (asset_uid);


--
-- Name: ix__ms_markets__targetpositionsts__portfolio_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__targetpositionsts__portfolio_uid ON public.ms_markets__targetpositionsts USING btree (portfolio_uid);


--
-- Name: ix__ms_markets__targetpositionsts__position_set_uid_e12d130813; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__targetpositionsts__position_set_uid_e12d130813 ON public.ms_markets__targetpositionsts USING btree (position_set_uid, target_type, target_uid);


--
-- Name: ix__ms_markets__virtualfund__account_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__virtualfund__account_uid ON public.ms_markets__virtualfund USING btree (account_uid);


--
-- Name: ix__ms_markets__virtualfund__target_portfolio_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__virtualfund__target_portfolio_uid ON public.ms_markets__virtualfund USING btree (target_portfolio_uid);


--
-- Name: ix__ms_markets__virtualfundholdingsset__source_accou_06924f9c22; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__virtualfundholdingsset__source_accou_06924f9c22 ON public.ms_markets__virtualfundholdingsset USING btree (source_account_holdings_set_uid);


--
-- Name: ix__ms_markets__virtualfundholdingsset__virtual_fund_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix__ms_markets__virtualfundholdingsset__virtual_fund_uid ON public.ms_markets__virtualfundholdingsset USING btree (virtual_fund_uid);


--
-- Name: uix__ms_markets__account__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__account__unique_identifier ON public.ms_markets__account USING btree (unique_identifier);


--
-- Name: uix__ms_markets__accountallocationmodel__allocation_model_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__accountallocationmodel__allocation_model_name ON public.ms_markets__accountallocationmodel USING btree (allocation_model_name);


--
-- Name: uix__ms_markets__accountgroup__group_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__accountgroup__group_name ON public.ms_markets__accountgroup USING btree (group_name);


--
-- Name: uix__ms_markets__accountholdingsset__account_uid__time_index; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__accountholdingsset__account_uid__time_index ON public.ms_markets__accountholdingsset USING btree (account_uid, time_index);


--
-- Name: uix__ms_markets__accountholdingsts__time_index__acco_dc2e0ec020; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__accountholdingsts__time_index__acco_dc2e0ec020 ON public.ms_markets__accountholdingsts USING btree (time_index, account_uid, asset_identifier);


--
-- Name: uix__ms_markets__accounttargetallocation__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__accounttargetallocation__unique_identifier ON public.ms_markets__accounttargetallocation USING btree (unique_identifier);


--
-- Name: uix__ms_markets__asset__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__asset__unique_identifier ON public.ms_markets__asset USING btree (unique_identifier);


--
-- Name: uix__ms_markets__assetcategory__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__assetcategory__unique_identifier ON public.ms_markets__assetcategory USING btree (unique_identifier);


--
-- Name: uix__ms_markets__assetcategorymembership__category_u_0c42bc3572; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__assetcategorymembership__category_u_0c42bc3572 ON public.ms_markets__assetcategorymembership USING btree (category_uid, asset_uid);


--
-- Name: uix__ms_markets__assetpricingdetailsts__time_index_affb4cd407; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__assetpricingdetailsts__time_index_affb4cd407 ON public.ms_markets__assetpricingdetailsts USING btree (time_index, asset_identifier);


--
-- Name: uix__ms_markets__assetsnapshotsts__time_index__asset_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__assetsnapshotsts__time_index__asset_identifier ON public.ms_markets__assetsnapshotsts USING btree (time_index, asset_identifier);


--
-- Name: uix__ms_markets__assettype__asset_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__assettype__asset_type ON public.ms_markets__assettype USING btree (asset_type);


--
-- Name: uix__ms_markets__calendar__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__calendar__unique_identifier ON public.ms_markets__calendar USING btree (unique_identifier);


--
-- Name: uix__ms_markets__calendardate__calendar_uid__local_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__calendardate__calendar_uid__local_date ON public.ms_markets__calendardate USING btree (calendar_uid, local_date);


--
-- Name: uix__ms_markets__calendarevent__calendar_uid__event_5ff36d9c47; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__calendarevent__calendar_uid__event_5ff36d9c47 ON public.ms_markets__calendarevent USING btree (calendar_uid, event_date, event_type, event_label, target_type, target_identifier);


--
-- Name: uix__ms_markets__calendarsession__calendar_uid__loca_30b16604ba; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__calendarsession__calendar_uid__loca_30b16604ba ON public.ms_markets__calendarsession USING btree (calendar_uid, local_date, session_label);


--
-- Name: uix__ms_markets__currencyspotassetdetails__base_curr_c8929e9103; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__currencyspotassetdetails__base_curr_c8929e9103 ON public.ms_markets__currencyspotassetdetails USING btree (base_currency_uid, quote_currency_uid);


--
-- Name: uix__ms_markets__curve__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__curve__unique_identifier ON public.ms_markets__curve USING btree (unique_identifier);


--
-- Name: uix__ms_markets__discountcurvests__time_index__curve_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__discountcurvests__time_index__curve_identifier ON public.ms_markets__discountcurvests USING btree (time_index, curve_identifier);


--
-- Name: uix__ms_markets__externalpricests__time_index__asset_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__externalpricests__time_index__asset_identifier ON public.ms_markets__externalpricests USING btree (time_index, asset_identifier);


--
-- Name: uix__ms_markets__index__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__index__unique_identifier ON public.ms_markets__index USING btree (unique_identifier);


--
-- Name: uix__ms_markets__indexdatasetavailability__index_uid_d9e5880cd2; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexdatasetavailability__index_uid_d9e5880cd2 ON public.ms_markets__indexdatasetavailability USING btree (index_uid, meta_table_uid);


--
-- Name: uix__ms_markets__indexfixingsts__time_index__index_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexfixingsts__time_index__index_identifier ON public.ms_markets__indexfixingsts USING btree (time_index, index_identifier);


--
-- Name: uix__ms_markets__indexformuladefinition__index_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexformuladefinition__index_uid ON public.ms_markets__indexformuladefinition USING btree (index_uid) WHERE ((status)::text = 'active'::text);


--
-- Name: uix__ms_markets__indexformuladefinition__index_uid_2e9e563e08; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexformuladefinition__index_uid_2e9e563e08 ON public.ms_markets__indexformuladefinition USING btree (index_uid, definition_hash);


--
-- Name: uix__ms_markets__indexformuladefinition__index_uid__version; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexformuladefinition__index_uid__version ON public.ms_markets__indexformuladefinition USING btree (index_uid, version);


--
-- Name: uix__ms_markets__indexformulainput__definition_uid_2c392a239a; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexformulainput__definition_uid_2c392a239a ON public.ms_markets__indexformulainput USING btree (definition_uid, component_index_uid, observable) WHERE (component_index_uid IS NOT NULL);


--
-- Name: uix__ms_markets__indexformulainput__definition_uid_bcfdf0c865; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexformulainput__definition_uid_bcfdf0c865 ON public.ms_markets__indexformulainput USING btree (definition_uid, asset_uid, observable) WHERE (asset_uid IS NOT NULL);


--
-- Name: uix__ms_markets__indextype__index_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indextype__index_type ON public.ms_markets__indextype USING btree (index_type);


--
-- Name: uix__ms_markets__indexvaluests__time_index__index_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__indexvaluests__time_index__index_identifier ON public.ms_markets__indexvaluests USING btree (time_index, index_identifier);


--
-- Name: uix__ms_markets__interpolatedpricests__time_index__a_303e840ea7; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__interpolatedpricests__time_index__a_303e840ea7 ON public.ms_markets__interpolatedpricests USING btree (time_index, asset_identifier);


--
-- Name: uix__ms_markets__issuer__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__issuer__unique_identifier ON public.ms_markets__issuer USING btree (unique_identifier);


--
-- Name: uix__ms_markets__ordereventsts__event_time__order_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__ordereventsts__event_time__order_identifier ON public.ms_markets__ordereventsts USING btree (event_time, order_identifier);


--
-- Name: uix__ms_markets__ordermanager__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__ordermanager__unique_identifier ON public.ms_markets__ordermanager USING btree (unique_identifier);


--
-- Name: uix__ms_markets__ordersts__order_time__order_identif_20c686be5c; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__ordersts__order_time__order_identif_20c686be5c ON public.ms_markets__ordersts USING btree (order_time, order_identifier, account_identifier, asset_identifier);


--
-- Name: uix__ms_markets__portfolio__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfolio__unique_identifier ON public.ms_markets__portfolio USING btree (unique_identifier);


--
-- Name: uix__ms_markets__portfolioanalyticsts__time_index__p_3663c63f31; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfolioanalyticsts__time_index__p_3663c63f31 ON public.ms_markets__portfolioanalyticsts USING btree (time_index, portfolio_identifier, analysis_identifier);


--
-- Name: uix__ms_markets__portfoliocalendareventsts__time_ind_8f8f40360d; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliocalendareventsts__time_ind_8f8f40360d ON public.ms_markets__portfoliocalendareventsts USING btree (time_index, calendar_identifier, session_label, event_type);


--
-- Name: uix__ms_markets__portfoliocashflowsts__time_index__p_e4e66e3ed6; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliocashflowsts__time_index__p_e4e66e3ed6 ON public.ms_markets__portfoliocashflowsts USING btree (time_index, portfolio_identifier, cash_flow_identifier);


--
-- Name: uix__ms_markets__portfolioeventledgerts__time_index_2c8bf183e0; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfolioeventledgerts__time_index_2c8bf183e0 ON public.ms_markets__portfolioeventledgerts USING btree (time_index, portfolio_identifier, event_identifier, event_revision, record_identifier);


--
-- Name: uix__ms_markets__portfoliogroup__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliogroup__unique_identifier ON public.ms_markets__portfoliogroup USING btree (unique_identifier);


--
-- Name: uix__ms_markets__portfoliogroupmembership__portfolio_68dd4661b0; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliogroupmembership__portfolio_68dd4661b0 ON public.ms_markets__portfoliogroupmembership USING btree (portfolio_group_uid, portfolio_uid);


--
-- Name: uix__ms_markets__portfoliometadata__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliometadata__unique_identifier ON public.ms_markets__portfoliometadata USING btree (unique_identifier);


--
-- Name: uix__ms_markets__portfoliorebalancestatets__time_ind_14224b91e7; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliorebalancestatets__time_ind_14224b91e7 ON public.ms_markets__portfoliorebalancestatets USING btree (time_index, portfolio_identifier, rebalance_intent_id, asset_identifier);


--
-- Name: uix__ms_markets__portfoliostatets__time_index__portf_7089b41a16; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliostatets__time_index__portf_7089b41a16 ON public.ms_markets__portfoliostatets USING btree (time_index, portfolio_identifier, state_identifier);


--
-- Name: uix__ms_markets__portfoliosts__time_index__portfolio_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfoliosts__time_index__portfolio_identifier ON public.ms_markets__portfoliosts USING btree (time_index, portfolio_identifier);


--
-- Name: uix__ms_markets__portfolioweightsts__time_index__por_d92475bae0; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__portfolioweightsts__time_index__por_d92475bae0 ON public.ms_markets__portfolioweightsts USING btree (time_index, portfolio_identifier, asset_identifier);


--
-- Name: uix__ms_markets__positionset__account_target_allocat_655208003c; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__positionset__account_target_allocat_655208003c ON public.ms_markets__positionset USING btree (account_target_allocation_uid, position_set_time);


--
-- Name: uix__ms_markets__pricingmarketdataset__set_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__pricingmarketdataset__set_key ON public.ms_markets__pricingmarketdataset USING btree (set_key);


--
-- Name: uix__ms_markets__pricingmarketdatasetbinding__market_7fb160d6c7; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__pricingmarketdatasetbinding__market_7fb160d6c7 ON public.ms_markets__pricingmarketdatasetbinding USING btree (market_data_set_uid, concept_key);


--
-- Name: uix__ms_markets__pricingmarketdatasetcurvebinding__m_a4fd2dc807; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__pricingmarketdatasetcurvebinding__m_a4fd2dc807 ON public.ms_markets__pricingmarketdatasetcurvebinding USING btree (market_data_set_uid, binding_key);


--
-- Name: uix__ms_markets__rebalancestrategymetadata__rebalanc_a097a6f535; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__rebalancestrategymetadata__rebalanc_a097a6f535 ON public.ms_markets__rebalancestrategymetadata USING btree (rebalance_strategy_uid);


--
-- Name: uix__ms_markets__signalmetadata__signal_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__signalmetadata__signal_uid ON public.ms_markets__signalmetadata USING btree (signal_uid);


--
-- Name: uix__ms_markets__signalweightsts__time_index__signal_94cdab9295; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__signalweightsts__time_index__signal_94cdab9295 ON public.ms_markets__signalweightsts USING btree (time_index, signal_uid, asset_identifier);


--
-- Name: uix__ms_markets__targetpositionsts__time_index__posi_d64428cc34; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__targetpositionsts__time_index__posi_d64428cc34 ON public.ms_markets__targetpositionsts USING btree (time_index, position_set_uid, target_type, target_uid);


--
-- Name: uix__ms_markets__tradests__trade_time__trade_identif_4ad9fea888; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__tradests__trade_time__trade_identif_4ad9fea888 ON public.ms_markets__tradests USING btree (trade_time, trade_identifier, account_identifier, asset_identifier);


--
-- Name: uix__ms_markets__virtualfund__unique_identifier; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__virtualfund__unique_identifier ON public.ms_markets__virtualfund USING btree (unique_identifier);


--
-- Name: uix__ms_markets__virtualfundholdingsset__virtual_fun_dff1425c83; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__virtualfundholdingsset__virtual_fun_dff1425c83 ON public.ms_markets__virtualfundholdingsset USING btree (virtual_fund_uid, source_account_holdings_set_uid);


--
-- Name: uix__ms_markets__virtualfundholdingsts__time_index_3dd71cda5c; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix__ms_markets__virtualfundholdingsts__time_index_3dd71cda5c ON public.ms_markets__virtualfundholdingsts USING btree (time_index, virtual_fund_uid, asset_identifier);


--
-- Name: ms_markets__account fk__ms_markets__account__account_group_uid__ms_marke_6e57748f82; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__account
    ADD CONSTRAINT fk__ms_markets__account__account_group_uid__ms_marke_6e57748f82 FOREIGN KEY (account_group_uid) REFERENCES public.ms_markets__accountgroup(uid) ON DELETE SET NULL;


--
-- Name: ms_markets__accountholdingsset fk__ms_markets__accountholdingsset__account_uid__ms_e2a71b318d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountholdingsset
    ADD CONSTRAINT fk__ms_markets__accountholdingsset__account_uid__ms_e2a71b318d FOREIGN KEY (account_uid) REFERENCES public.ms_markets__account(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__accountholdingsts fk__ms_markets__accountholdingsts__account_uid__ms_m_16e561105a; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountholdingsts
    ADD CONSTRAINT fk__ms_markets__accountholdingsts__account_uid__ms_m_16e561105a FOREIGN KEY (account_uid) REFERENCES public.ms_markets__account(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__accountholdingsts fk__ms_markets__accountholdingsts__asset_identifier_59e659b7be; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountholdingsts
    ADD CONSTRAINT fk__ms_markets__accountholdingsts__asset_identifier_59e659b7be FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__accountholdingsts fk__ms_markets__accountholdingsts__holdings_set_uid_b7de9105a4; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accountholdingsts
    ADD CONSTRAINT fk__ms_markets__accountholdingsts__holdings_set_uid_b7de9105a4 FOREIGN KEY (holdings_set_uid) REFERENCES public.ms_markets__accountholdingsset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__accounttargetallocation fk__ms_markets__accounttargetallocation__account_all_3ad225212e; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accounttargetallocation
    ADD CONSTRAINT fk__ms_markets__accounttargetallocation__account_all_3ad225212e FOREIGN KEY (account_allocation_model_uid) REFERENCES public.ms_markets__accountallocationmodel(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__accounttargetallocation fk__ms_markets__accounttargetallocation__account_uid_39a0fc4ade; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__accounttargetallocation
    ADD CONSTRAINT fk__ms_markets__accounttargetallocation__account_uid_39a0fc4ade FOREIGN KEY (account_uid) REFERENCES public.ms_markets__account(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__assetcategorymembership fk__ms_markets__assetcategorymembership__asset_uid_5f2895c7b9; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcategorymembership
    ADD CONSTRAINT fk__ms_markets__assetcategorymembership__asset_uid_5f2895c7b9 FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__assetcategorymembership fk__ms_markets__assetcategorymembership__category_ui_38bb05de48; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcategorymembership
    ADD CONSTRAINT fk__ms_markets__assetcategorymembership__category_ui_38bb05de48 FOREIGN KEY (category_uid) REFERENCES public.ms_markets__assetcategory(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__assetcurrentpricingdetails fk__ms_markets__assetcurrentpricingdetails__asset_ui_1c2887baef; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetcurrentpricingdetails
    ADD CONSTRAINT fk__ms_markets__assetcurrentpricingdetails__asset_ui_1c2887baef FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__assetpricingdetailsts fk__ms_markets__assetpricingdetailsts__asset_identif_f006fec295; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetpricingdetailsts
    ADD CONSTRAINT fk__ms_markets__assetpricingdetailsts__asset_identif_f006fec295 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__assetsnapshotsts fk__ms_markets__assetsnapshotsts__asset_identifier_dbde28e44f; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__assetsnapshotsts
    ADD CONSTRAINT fk__ms_markets__assetsnapshotsts__asset_identifier_dbde28e44f FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__bondassetdetails fk__ms_markets__bondassetdetails__asset_uid__ms_mark_b546a4682d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__bondassetdetails
    ADD CONSTRAINT fk__ms_markets__bondassetdetails__asset_uid__ms_mark_b546a4682d FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__bondassetdetails fk__ms_markets__bondassetdetails__currency_asset_uid_ea9b01c897; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__bondassetdetails
    ADD CONSTRAINT fk__ms_markets__bondassetdetails__currency_asset_uid_ea9b01c897 FOREIGN KEY (currency_asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__bondassetdetails fk__ms_markets__bondassetdetails__issuer_uid__ms_mar_8fe31913aa; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__bondassetdetails
    ADD CONSTRAINT fk__ms_markets__bondassetdetails__issuer_uid__ms_mar_8fe31913aa FOREIGN KEY (issuer_uid) REFERENCES public.ms_markets__issuer(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__calendardate fk__ms_markets__calendardate__calendar_uid__ms_marke_d1ea943953; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendardate
    ADD CONSTRAINT fk__ms_markets__calendardate__calendar_uid__ms_marke_d1ea943953 FOREIGN KEY (calendar_uid) REFERENCES public.ms_markets__calendar(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__calendarevent fk__ms_markets__calendarevent__calendar_uid__ms_mark_82f9e66428; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendarevent
    ADD CONSTRAINT fk__ms_markets__calendarevent__calendar_uid__ms_mark_82f9e66428 FOREIGN KEY (calendar_uid) REFERENCES public.ms_markets__calendar(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__calendarsession fk__ms_markets__calendarsession__calendar_uid__ms_ma_1b8e1a05d3; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__calendarsession
    ADD CONSTRAINT fk__ms_markets__calendarsession__calendar_uid__ms_ma_1b8e1a05d3 FOREIGN KEY (calendar_uid) REFERENCES public.ms_markets__calendar(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__currencyspotassetdetails fk__ms_markets__currencyspotassetdetails__asset_uid_14d1916f45; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__currencyspotassetdetails
    ADD CONSTRAINT fk__ms_markets__currencyspotassetdetails__asset_uid_14d1916f45 FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__currencyspotassetdetails fk__ms_markets__currencyspotassetdetails__base_curre_f7fc7a4996; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__currencyspotassetdetails
    ADD CONSTRAINT fk__ms_markets__currencyspotassetdetails__base_curre_f7fc7a4996 FOREIGN KEY (base_currency_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__currencyspotassetdetails fk__ms_markets__currencyspotassetdetails__quote_curr_12d82159e5; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__currencyspotassetdetails
    ADD CONSTRAINT fk__ms_markets__currencyspotassetdetails__quote_curr_12d82159e5 FOREIGN KEY (quote_currency_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__curvebuildingdetails fk__ms_markets__curvebuildingdetails__curve_uid__ms_8b16d2f8b7; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__curvebuildingdetails
    ADD CONSTRAINT fk__ms_markets__curvebuildingdetails__curve_uid__ms_8b16d2f8b7 FOREIGN KEY (curve_uid) REFERENCES public.ms_markets__curve(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__discountcurvests fk__ms_markets__discountcurvests__curve_identifier_0413caaa5f; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__discountcurvests
    ADD CONSTRAINT fk__ms_markets__discountcurvests__curve_identifier_0413caaa5f FOREIGN KEY (curve_identifier) REFERENCES public.ms_markets__curve(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__externalpricests fk__ms_markets__externalpricests__asset_identifier_1e0967f48c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__externalpricests
    ADD CONSTRAINT fk__ms_markets__externalpricests__asset_identifier_1e0967f48c FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__futureassetdetails fk__ms_markets__futureassetdetails__asset_uid__ms_ma_9a160ba3da; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__futureassetdetails
    ADD CONSTRAINT fk__ms_markets__futureassetdetails__asset_uid__ms_ma_9a160ba3da FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__futureassetdetails fk__ms_markets__futureassetdetails__margin_asset__ms_beef65882d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__futureassetdetails
    ADD CONSTRAINT fk__ms_markets__futureassetdetails__margin_asset__ms_beef65882d FOREIGN KEY (margin_asset) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__futureassetdetails fk__ms_markets__futureassetdetails__settlement_asset_7b263cb41b; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__futureassetdetails
    ADD CONSTRAINT fk__ms_markets__futureassetdetails__settlement_asset_7b263cb41b FOREIGN KEY (settlement_asset) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__futureassetdetails fk__ms_markets__futureassetdetails__underlying_index_a3b279700b; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__futureassetdetails
    ADD CONSTRAINT fk__ms_markets__futureassetdetails__underlying_index_a3b279700b FOREIGN KEY (underlying_index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__indexconventiondetails fk__ms_markets__indexconventiondetails__index_uid__m_b3b3091742; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexconventiondetails
    ADD CONSTRAINT fk__ms_markets__indexconventiondetails__index_uid__m_b3b3091742 FOREIGN KEY (index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__indexdatasetavailability fk__ms_markets__indexdatasetavailability__index_uid_064eaeecbc; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexdatasetavailability
    ADD CONSTRAINT fk__ms_markets__indexdatasetavailability__index_uid_064eaeecbc FOREIGN KEY (index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__indexfixingsts fk__ms_markets__indexfixingsts__index_identifier__ms_011a6aef3b; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexfixingsts
    ADD CONSTRAINT fk__ms_markets__indexfixingsts__index_identifier__ms_011a6aef3b FOREIGN KEY (index_identifier) REFERENCES public.ms_markets__index(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__indexformuladefinition fk__ms_markets__indexformuladefinition__index_uid__m_13d9e1ae56; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformuladefinition
    ADD CONSTRAINT fk__ms_markets__indexformuladefinition__index_uid__m_13d9e1ae56 FOREIGN KEY (index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__indexformulainput fk__ms_markets__indexformulainput__asset_uid__ms_mar_be7c95b321; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformulainput
    ADD CONSTRAINT fk__ms_markets__indexformulainput__asset_uid__ms_mar_be7c95b321 FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__indexformulainput fk__ms_markets__indexformulainput__component_index_u_80609d9ccb; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformulainput
    ADD CONSTRAINT fk__ms_markets__indexformulainput__component_index_u_80609d9ccb FOREIGN KEY (component_index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__indexformulainput fk__ms_markets__indexformulainput__definition_uid__m_029026c1a6; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexformulainput
    ADD CONSTRAINT fk__ms_markets__indexformulainput__definition_uid__m_029026c1a6 FOREIGN KEY (definition_uid) REFERENCES public.ms_markets__indexformuladefinition(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__indexvaluests fk__ms_markets__indexvaluests__definition_uid__ms_ma_e41abab9ce; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexvaluests
    ADD CONSTRAINT fk__ms_markets__indexvaluests__definition_uid__ms_ma_e41abab9ce FOREIGN KEY (definition_uid) REFERENCES public.ms_markets__indexformuladefinition(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__indexvaluests fk__ms_markets__indexvaluests__index_identifier__ms_dc817632b8; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__indexvaluests
    ADD CONSTRAINT fk__ms_markets__indexvaluests__index_identifier__ms_dc817632b8 FOREIGN KEY (index_identifier) REFERENCES public.ms_markets__index(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__interpolatedpricests fk__ms_markets__interpolatedpricests__asset_identifi_2eaa30fd5d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__interpolatedpricests
    ADD CONSTRAINT fk__ms_markets__interpolatedpricests__asset_identifi_2eaa30fd5d FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__openfigiassetdetails fk__ms_markets__openfigiassetdetails__asset_uid__ms_71f6ffefab; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__openfigiassetdetails
    ADD CONSTRAINT fk__ms_markets__openfigiassetdetails__asset_uid__ms_71f6ffefab FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__ordermanager fk__ms_markets__ordermanager__target_account_uid__ms_54bb7bca6f; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__ordermanager
    ADD CONSTRAINT fk__ms_markets__ordermanager__target_account_uid__ms_54bb7bca6f FOREIGN KEY (target_account_uid) REFERENCES public.ms_markets__account(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__ordersts fk__ms_markets__ordersts__account_identifier__ms_mar_dc1a18e044; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__ordersts
    ADD CONSTRAINT fk__ms_markets__ordersts__account_identifier__ms_mar_dc1a18e044 FOREIGN KEY (account_identifier) REFERENCES public.ms_markets__account(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__ordersts fk__ms_markets__ordersts__asset_identifier__ms_marke_e41085088a; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__ordersts
    ADD CONSTRAINT fk__ms_markets__ordersts__asset_identifier__ms_marke_e41085088a FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__ordersts fk__ms_markets__ordersts__order_manager_identifier_b80dd3d684; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__ordersts
    ADD CONSTRAINT fk__ms_markets__ordersts__order_manager_identifier_b80dd3d684 FOREIGN KEY (order_manager_identifier) REFERENCES public.ms_markets__ordermanager(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolio fk__ms_markets__portfolio__calendar_uid__ms_markets_38b74ba255; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolio
    ADD CONSTRAINT fk__ms_markets__portfolio__calendar_uid__ms_markets_38b74ba255 FOREIGN KEY (calendar_uid) REFERENCES public.ms_markets__calendar(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolio fk__ms_markets__portfolio__published_index_uid__ms_m_55735b6fcf; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolio
    ADD CONSTRAINT fk__ms_markets__portfolio__published_index_uid__ms_m_55735b6fcf FOREIGN KEY (published_index_uid) REFERENCES public.ms_markets__index(uid) ON DELETE SET NULL;


--
-- Name: ms_markets__portfolio fk__ms_markets__portfolio__signal_uid__signalmetadata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolio
    ADD CONSTRAINT fk__ms_markets__portfolio__signal_uid__signalmetadata FOREIGN KEY (signal_uid) REFERENCES public.ms_markets__signalmetadata(signal_uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioanalyticsts fk__ms_markets__portfolioanalyticsts__portfolio_iden_428f008ec7; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioanalyticsts
    ADD CONSTRAINT fk__ms_markets__portfolioanalyticsts__portfolio_iden_428f008ec7 FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliocalendareventsts fk__ms_markets__portfoliocalendareventsts__calendar_85f2c7285c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliocalendareventsts
    ADD CONSTRAINT fk__ms_markets__portfoliocalendareventsts__calendar_85f2c7285c FOREIGN KEY (calendar_identifier) REFERENCES public.ms_markets__calendar(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliocashflowsts fk__ms_markets__portfoliocashflowsts__asset_identifi_ccd9c15c47; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliocashflowsts
    ADD CONSTRAINT fk__ms_markets__portfoliocashflowsts__asset_identifi_ccd9c15c47 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliocashflowsts fk__ms_markets__portfoliocashflowsts__portfolio_iden_1aa3ff9f1e; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliocashflowsts
    ADD CONSTRAINT fk__ms_markets__portfoliocashflowsts__portfolio_iden_1aa3ff9f1e FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliocashflowsts fk__ms_markets__portfoliocashflowsts__valuation_asse_ca078ce47d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliocashflowsts
    ADD CONSTRAINT fk__ms_markets__portfoliocashflowsts__valuation_asse_ca078ce47d FOREIGN KEY (valuation_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioeventledgerts fk__ms_markets__portfolioeventledgerts__amount_asset_8007a31a3a; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT fk__ms_markets__portfolioeventledgerts__amount_asset_8007a31a3a FOREIGN KEY (amount_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioeventledgerts fk__ms_markets__portfolioeventledgerts__asset_identi_687949c5aa; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT fk__ms_markets__portfolioeventledgerts__asset_identi_687949c5aa FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioeventledgerts fk__ms_markets__portfolioeventledgerts__portfolio_id_2d298ef7c8; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT fk__ms_markets__portfolioeventledgerts__portfolio_id_2d298ef7c8 FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioeventledgerts fk__ms_markets__portfolioeventledgerts__price_asset_e86d478e61; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT fk__ms_markets__portfolioeventledgerts__price_asset_e86d478e61 FOREIGN KEY (price_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioeventledgerts fk__ms_markets__portfolioeventledgerts__valuation_as_22afd4739f; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioeventledgerts
    ADD CONSTRAINT fk__ms_markets__portfolioeventledgerts__valuation_as_22afd4739f FOREIGN KEY (valuation_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliogroupmembership fk__ms_markets__portfoliogroupmembership__portfolio_21b0da4ce6; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliogroupmembership
    ADD CONSTRAINT fk__ms_markets__portfoliogroupmembership__portfolio_21b0da4ce6 FOREIGN KEY (portfolio_group_uid) REFERENCES public.ms_markets__portfoliogroup(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__portfoliogroupmembership fk__ms_markets__portfoliogroupmembership__portfolio_4016df5ffb; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliogroupmembership
    ADD CONSTRAINT fk__ms_markets__portfoliogroupmembership__portfolio_4016df5ffb FOREIGN KEY (portfolio_uid) REFERENCES public.ms_markets__portfolio(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__portfoliorebalancestatets fk__ms_markets__portfoliorebalancestatets__asset_ide_892cf6805c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliorebalancestatets
    ADD CONSTRAINT fk__ms_markets__portfoliorebalancestatets__asset_ide_892cf6805c FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliorebalancestatets fk__ms_markets__portfoliorebalancestatets__portfolio_e297b1a89f; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliorebalancestatets
    ADD CONSTRAINT fk__ms_markets__portfoliorebalancestatets__portfolio_e297b1a89f FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliostatets fk__ms_markets__portfoliostatets__asset_identifier_08fe4310f7; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliostatets
    ADD CONSTRAINT fk__ms_markets__portfoliostatets__asset_identifier_08fe4310f7 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliostatets fk__ms_markets__portfoliostatets__portfolio_identifi_bdf8b70f4b; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliostatets
    ADD CONSTRAINT fk__ms_markets__portfoliostatets__portfolio_identifi_bdf8b70f4b FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliostatets fk__ms_markets__portfoliostatets__valuation_asset_id_e7977ed80d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliostatets
    ADD CONSTRAINT fk__ms_markets__portfoliostatets__valuation_asset_id_e7977ed80d FOREIGN KEY (valuation_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfoliosts fk__ms_markets__portfoliosts__portfolio_identifier_b1074f8062; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfoliosts
    ADD CONSTRAINT fk__ms_markets__portfoliosts__portfolio_identifier_b1074f8062 FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioweightsts fk__ms_markets__portfolioweightsts__asset_identifier_589cee70db; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioweightsts
    ADD CONSTRAINT fk__ms_markets__portfolioweightsts__asset_identifier_589cee70db FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__portfolioweightsts fk__ms_markets__portfolioweightsts__portfolio_identi_2d183320e0; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__portfolioweightsts
    ADD CONSTRAINT fk__ms_markets__portfolioweightsts__portfolio_identi_2d183320e0 FOREIGN KEY (portfolio_identifier) REFERENCES public.ms_markets__portfolio(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__positionset fk__ms_markets__positionset__account_target_allocati_ce4417ded1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__positionset
    ADD CONSTRAINT fk__ms_markets__positionset__account_target_allocati_ce4417ded1 FOREIGN KEY (account_target_allocation_uid) REFERENCES public.ms_markets__accounttargetallocation(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__pricingmarketdatasetbinding fk__ms_markets__pricingmarketdatasetbinding__market_905593db9d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdatasetbinding
    ADD CONSTRAINT fk__ms_markets__pricingmarketdatasetbinding__market_905593db9d FOREIGN KEY (market_data_set_uid) REFERENCES public.ms_markets__pricingmarketdataset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__pricingmarketdatasetcurvebinding fk__ms_markets__pricingmarketdatasetcurvebinding__cu_5fe237c524; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdatasetcurvebinding
    ADD CONSTRAINT fk__ms_markets__pricingmarketdatasetcurvebinding__cu_5fe237c524 FOREIGN KEY (curve_uid) REFERENCES public.ms_markets__curve(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__pricingmarketdatasetcurvebinding fk__ms_markets__pricingmarketdatasetcurvebinding__ma_3e1d491d04; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__pricingmarketdatasetcurvebinding
    ADD CONSTRAINT fk__ms_markets__pricingmarketdatasetcurvebinding__ma_3e1d491d04 FOREIGN KEY (market_data_set_uid) REFERENCES public.ms_markets__pricingmarketdataset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__signalweightsts fk__ms_markets__signalweightsts__asset_identifier__m_5ab737e205; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__signalweightsts
    ADD CONSTRAINT fk__ms_markets__signalweightsts__asset_identifier__m_5ab737e205 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__signalweightsts fk__ms_markets__signalweightsts__signal_uid__ms_mark_5e17963320; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__signalweightsts
    ADD CONSTRAINT fk__ms_markets__signalweightsts__signal_uid__ms_mark_5e17963320 FOREIGN KEY (signal_uid) REFERENCES public.ms_markets__signalmetadata(signal_uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__targetpositionsts fk__ms_markets__targetpositionsts__asset_uid__ms_mar_d18c80b341; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__targetpositionsts
    ADD CONSTRAINT fk__ms_markets__targetpositionsts__asset_uid__ms_mar_d18c80b341 FOREIGN KEY (asset_uid) REFERENCES public.ms_markets__asset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__targetpositionsts fk__ms_markets__targetpositionsts__portfolio_uid__ms_fc069f94cf; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__targetpositionsts
    ADD CONSTRAINT fk__ms_markets__targetpositionsts__portfolio_uid__ms_fc069f94cf FOREIGN KEY (portfolio_uid) REFERENCES public.ms_markets__portfolio(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__targetpositionsts fk__ms_markets__targetpositionsts__position_set_uid_ba3522b914; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__targetpositionsts
    ADD CONSTRAINT fk__ms_markets__targetpositionsts__position_set_uid_ba3522b914 FOREIGN KEY (position_set_uid) REFERENCES public.ms_markets__positionset(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__tradests fk__ms_markets__tradests__account_identifier__ms_mar_30086c4426; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__tradests
    ADD CONSTRAINT fk__ms_markets__tradests__account_identifier__ms_mar_30086c4426 FOREIGN KEY (account_identifier) REFERENCES public.ms_markets__account(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__tradests fk__ms_markets__tradests__asset_identifier__ms_marke_a480feaac0; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__tradests
    ADD CONSTRAINT fk__ms_markets__tradests__asset_identifier__ms_marke_a480feaac0 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__tradests fk__ms_markets__tradests__commission_asset_identifie_d3e610dd3a; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__tradests
    ADD CONSTRAINT fk__ms_markets__tradests__commission_asset_identifie_d3e610dd3a FOREIGN KEY (commission_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__tradests fk__ms_markets__tradests__settlement_asset_identifie_7d43f1681c; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__tradests
    ADD CONSTRAINT fk__ms_markets__tradests__settlement_asset_identifie_7d43f1681c FOREIGN KEY (settlement_asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__virtualfund fk__ms_markets__virtualfund__account_uid__ms_markets_aff139259e; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfund
    ADD CONSTRAINT fk__ms_markets__virtualfund__account_uid__ms_markets_aff139259e FOREIGN KEY (account_uid) REFERENCES public.ms_markets__account(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__virtualfund fk__ms_markets__virtualfund__target_portfolio_uid__m_829c99c153; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfund
    ADD CONSTRAINT fk__ms_markets__virtualfund__target_portfolio_uid__m_829c99c153 FOREIGN KEY (target_portfolio_uid) REFERENCES public.ms_markets__portfolio(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__virtualfundholdingsset fk__ms_markets__virtualfundholdingsset__source_accou_8cda520909; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsset
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsset__source_accou_8cda520909 FOREIGN KEY (source_account_holdings_set_uid) REFERENCES public.ms_markets__accountholdingsset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__virtualfundholdingsset fk__ms_markets__virtualfundholdingsset__virtual_fund_6d3a9e95bb; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsset
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsset__virtual_fund_6d3a9e95bb FOREIGN KEY (virtual_fund_uid) REFERENCES public.ms_markets__virtualfund(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__virtualfundholdingsts fk__ms_markets__virtualfundholdingsts__asset_identif_9a6a629329; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsts
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsts__asset_identif_9a6a629329 FOREIGN KEY (asset_identifier) REFERENCES public.ms_markets__asset(unique_identifier) ON DELETE RESTRICT;


--
-- Name: ms_markets__virtualfundholdingsts fk__ms_markets__virtualfundholdingsts__source_accoun_f80c80eed8; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsts
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsts__source_accoun_f80c80eed8 FOREIGN KEY (source_account_holdings_set_uid) REFERENCES public.ms_markets__accountholdingsset(uid) ON DELETE RESTRICT;


--
-- Name: ms_markets__virtualfundholdingsts fk__ms_markets__virtualfundholdingsts__virtual_fund_611277f0e0; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsts
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsts__virtual_fund_611277f0e0 FOREIGN KEY (virtual_fund_uid) REFERENCES public.ms_markets__virtualfund(uid) ON DELETE CASCADE;


--
-- Name: ms_markets__virtualfundholdingsts fk__ms_markets__virtualfundholdingsts__virtual_fund_8833b421bd; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ms_markets__virtualfundholdingsts
    ADD CONSTRAINT fk__ms_markets__virtualfundholdingsts__virtual_fund_8833b421bd FOREIGN KEY (virtual_fund_holdings_set_uid) REFERENCES public.ms_markets__virtualfundholdingsset(uid) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

