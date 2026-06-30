# Fixings

Index fixings are observed facts about an index, published by `FixingRatesNode`
and keyed by `IndexTable.unique_identifier`. They are not assets and they are
not a separate `Rate` model.

## Index Fixings

`FixingRatesNode` extends `IndexTimestampedDataNode`, so rows are keyed by
`(time_index, index_identifier)`, where `index_identifier` is
`IndexTable.unique_identifier`.

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| IndexTable                  |<--------------------------------| FixingRatesNode             |
|-----------------------------|        index_identifier          |-----------------------------|
| uid                  PK     |                                  | time_index                  |
| unique_identifier    unique |                                  | index_identifier            |
| index_type                  |                                  | rate                        |
+-----------------------------+                                  +-----------------------------+
```

The fixing DataNode contract is:

```text
FixingRatesNode
  index:   (time_index, index_identifier)
  cadence: 1d
  columns: rate
  FK:      index_identifier -> IndexTable.unique_identifier
```

The EOD pricing storage tables declare `__cadence__ = "1d"` on the
`PlatformTimeIndexMetaTable` storage class. Cadence is first-class
time-indexed table metadata and participates in SDK storage identity, so it
does not belong on `IndexFixingConfiguration`.

## Related Concepts

- [msm_pricing overview](index.md)
- [Market Data Sets](market_data_sets.md)
- [Curves](curves.md)
- [Runtime Resolution](runtime_resolution.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
