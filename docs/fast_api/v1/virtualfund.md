# Virtual Fund Routes

The `apps/v1` virtual-fund routes expose account-owned virtual-fund allocation
views from core `msm`.

Virtual funds are not assets, custody accounts, or portfolio construction
objects. They are account allocation views over real account holdings and point
to a target portfolio.

## Runtime Sources

- Virtual-fund identity uses `msm.api.virtual_funds.VirtualFund`.
- Holdings sets use `msm.api.virtual_funds.VirtualFundHoldingsSet`.
- Holdings rows use
  `msm.data_nodes.accounts.virtual_funds.storage.VirtualFundHoldingsStorage`.
- Holdings row asset labels use `AssetSnapshotsStorage`; OpenFIGI is not used.

The frontend filter `portfolio_uid` maps to:

```text
VirtualFundTable.target_portfolio_uid
```

## List Virtual Funds

```text
GET /api/v1/virtualfund/?response_format=frontend_list&search=&account_uid=&portfolio_uid=&limit=25&offset=0
```

Returns `PaginatedResponse[VirtualFund]`:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "virtual-fund-uid",
      "unique_identifier": "account-alpha__portfolio-sleeve",
      "account_uid": "account-uid",
      "target_portfolio_uid": "portfolio-uid"
    }
  ]
}
```

## Virtual Fund Detail

```text
GET /api/v1/virtualfund/{uid}/
```

Returns the core virtual-fund row plus detail-page links:

```json
{
  "virtual_fund": {
    "uid": "virtual-fund-uid",
    "unique_identifier": "account-alpha__portfolio-sleeve",
    "account_uid": "account-uid",
    "target_portfolio_uid": "portfolio-uid"
  },
  "tabs": [
    {
      "key": "latest_holdings",
      "label": "Latest Holdings",
      "url": "/api/v1/virtualfund/virtual-fund-uid/holdings/?order=desc&limit=1&include_asset_detail=true"
    }
  ],
  "links": {
    "summary": "/api/v1/virtualfund/virtual-fund-uid/summary/",
    "latest_holdings": "/api/v1/virtualfund/virtual-fund-uid/holdings/",
    "account": "/api/v1/account/account-uid/summary/",
    "portfolio": "/api/v1/portfolio/portfolio-uid/"
  }
}
```

## Virtual Fund Summary

```text
GET /api/v1/virtualfund/{uid}/summary/
```

Returns the shared `FrontEndDetailSummary` contract. The summary `entity.id`
is the virtual-fund `uid` string.

## Latest Virtual Fund Holdings

```text
GET /api/v1/virtualfund/{uid}/holdings/?order=desc&limit=1&include_asset_detail=true
```

Returns one `VirtualFundHoldingsSnapshotResponse`:

```json
{
  "virtual_fund_uid": "virtual-fund-uid",
  "virtual_fund_unique_identifier": "account-alpha__portfolio-sleeve",
  "holdings_set_uid": "virtual-fund-holdings-set-uid",
  "source_account_holdings_set_uid": "account-holdings-set-uid",
  "holdings_date": "2026-06-08T10:30:00Z",
  "holdings": [
    {
      "time_index": "2026-06-08T10:30:00Z",
      "asset_identifier": "example-asset-btc",
      "virtual_fund_holdings_set_uid": "virtual-fund-holdings-set-uid",
      "source_account_holdings_set_uid": "account-holdings-set-uid",
      "quantity": "5.0",
      "direction": -1,
      "signed_quantity": "-5.0",
      "target_trade_time": null,
      "extra_details": {},
      "asset": {
        "uid": "asset-uid",
        "asset_identifier": "example-asset-btc",
        "current_snapshot": {
          "name": "Bitcoin",
          "ticker": "BTC"
        }
      }
    }
  ]
}
```

## Virtual Fund Holdings By Date

```text
GET /api/v1/virtualfund/{uid}/holdings/?holdings_date=2026-06-08T10:30:00Z&include_asset_detail=true
```

`holdings_date` selects the exact
`VirtualFundHoldingsSetTable.time_index` / `VirtualFundHoldingsStorage.time_index`
snapshot and takes precedence over `order`.

If the virtual fund exists but no rows exist for the requested timestamp, the
response is 200 with an empty `holdings` list:

```json
{
  "virtual_fund_uid": "virtual-fund-uid",
  "virtual_fund_unique_identifier": "account-alpha__portfolio-sleeve",
  "holdings_set_uid": null,
  "source_account_holdings_set_uid": null,
  "holdings_date": null,
  "holdings": []
}
```

## Non-Goals

The first virtual-fund API route does not create, update, or apply allocation
plans. Virtual-fund creation and holdings publication remain owned by the
account virtual-fund allocation workflow.
