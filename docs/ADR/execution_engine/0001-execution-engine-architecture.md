# 0001. Execution Engine Architecture

## Status

Proposed (2026-11-18). Drafted from a design discussion with the owner on 2026-11-18. Nothing
in this ADR is implemented.

- A decision marked (owner) was made by the owner in that discussion. Everything else is the
  proposal that came out of the analysis, and is open to change.
- This is the first ADR of the execution engine. The engine has the highest priority of this
  work because it trades, and its trading path is the most critical path. It is designed first,
  as the contract the rest fits (owner).
- Corrections to the rebalance strategies are not part of this ADR (owner). They are kept in
  "Points Outside The Engine's Architecture" so they can be taken up again.
- It builds on [ADR 0040](../0040-portfolio-temporal-ownership.md) (a rebalance strategy is a
  state machine over declared inputs) and on
  [ADR 0054](../0054-account-exposure-and-sized-fund-targets.md) (account exposure, virtual
  funds and the sync).
- It keeps the boundary of
  [ADR 0042](../0042-position-cash-flow-portfolio-accounting.md): a Portfolio never receives
  broker orders, trades or fills.
- When implemented it amends
  [ADR 0053](../0053-virtual-fund-allocation-routes-and-described-policies.md): see "Fund
  Holdings At A Sync".
- It is implemented together with
  [ADR 0062](../0062-capital-given-to-a-virtual-fund.md), the capital given to a cash fund,
  and [ADR 0063](../0063-a-policy-base-for-portfolios-and-accounts.md), the policies and
  rebalance strategies of portfolios and accounts, as one coordinated implementation (owner,
  2026-11-23). The three are kept in agreement: a change to one is checked against the other
  two.

The facts about existing code were checked on `development` at commit `9ce4b7c2`. The
strategy contract was read again on 2026-11-23, after issues 89 and 90 changed it (ADR 0058).

## Context

### What We Want

A rebalance strategy must be reusable: the same strategy object that a portfolio backtest runs
must decide the trades of a live account (owner). `ImmediateSignal` listening to a signal is
the simplest case: when the signal changes, the strategy decides the rebalance, and that
decision is the same code in the backtest and in live trading.

### What Exists

- **The strategy says when, and its policy says how much.** A `RebalanceStrategyBase` in
  `src/msm_portfolios/rebalance_strategy/base.py` declares its inputs, selects its own events
  and resumes from stored state (ADR 0040). At each target's earliest moment its execution
  policy fixes one order for each asset, on a book of shares and cash, and decides how much of
  each order may trade under its cash rules
  ([ADR 0058](../0058-trade-at-the-next-observed-price.md)). A strategy with its own bars gives
  the slice of each order that a bar allows.
- **The account side has the exposure and the funds.** An account target states exposure to
  portfolios and to assets. Writing an exposure to a portfolio creates the `VirtualFund` of
  that account and portfolio. A sync allocates the account's holdings to the funds and stores
  one line for each owner and asset (ADR 0054).
- **Execution records exist and nothing produces them from a strategy.** `OrderManager`,
  `OrdersTS`, `OrderEventsTS` and `TradesTS` are keyed by account and asset. None carries a
  fund (`src/msm/time_index/execution/storage.py`).
- **A strategy registry exists and is not used.** `RebalanceStrategyMetadata` is keyed by
  `rebalance_strategy_uid` and has a `configuration_json` column. No portfolio code writes it
  and no row points at it.
- **The portfolio ledger cannot be the trading book.** For each event
  `PortfolioAccounting.apply_event_batch` copies frames, hashes the whole state and values the
  portfolio twice (`src/msm_portfolios/accounting/reducer.py`). That is right for a backtest
  and too slow for a stream of fills.

### What Is Missing

- Anything that turns a strategy's decision into orders.
- A book that knows, while trading, which fund owns which units and what each strategy still
  wants.
- A contract that says what a provider implements to connect an exchange or a broker.

### The Owner's Requirements

Business logic (owner):

1. Each execution engine is linked to one account only.
2. The engine gets the account's target allocation, to portfolios or to individual assets.
3. The engine launches an independent rebalance strategy for each virtual fund, the one that
   belongs to the configured portfolio.
4. Each rebalance strategy hands its required buys and sells to the engine.
5. The engine first trades between rebalance strategies when it can. If one strategy buys 100
   AAPL and another sells 100 AAPL, nothing is sent to the market. This is an internal trade.
6. The engine keeps a constantly active book of what each rebalance strategy wants to do.
7. This applies to every rebalance strategy, not only `ImmediateSignal`. Strategies follow one
   strict design and are validated in backtest before they run live. A signal alone can be
   backtested, for example traded by VWAP.

Considerations (owner):

- Trading can happen over websockets at high speed. The ledger is kept locally and does not
  depend on the ms-markets database. This is the hot path.
- Operations are eventually coordinated with ms-markets trades, orders and order managers.
  That is not the hot path.
- ms-markets provides the primitives and the architecture. Each provider implements the
  connection to its exchange.
- ms-markets provides the best logical and architectural design for managing the account book.
- Rebalance strategies get information from signals as soon as possible.

## Decision

1. **One engine, one account** (owner). An account has at most one running engine.
2. **The engine is its own module** (owner), separate from `msm` and `msm_portfolios`. The
   proposed name is `msm_execution`.
3. **The provider imports and extends the engine** (owner). Without a provider the engine
   cannot trade. The provider owns the exchange connection, the prices and the quantization of
   orders (owner). ms-markets still takes no price in its own records, so ADR 0054 stands.
4. **One strategy instance for each virtual fund** (owner). A direct asset row of the target
   names its own strategy. A row that names none uses the engine's strategy for direct rows,
   which the provider sets (owner).
5. **Strategies are named through the registry** (owner). A portfolio and a direct asset row
   name their strategy by `rebalance_strategy_uid`.
6. **A strategy hands the engine the position it wants, in units.** The book derives the buy
   or the sell. This is how requirement 4 is met; see "Why Positions And Not Orders".
7. **The engine keeps the account book in local memory** (owner): what each owner holds, what
   each strategy wants, and what is working at the exchange.
8. **Internal trades come first** (owner), at the first price observed at or after the match
   (owner). By default only what each strategy asked to trade now is matched. Offering the
   whole intent is a setting of the strategy, for strategies that must trade faster (owner).
9. **What is left goes to the exchange as one order request for each asset**, and every fill
   is split back to the owners it was for.
10. **ms-markets is written afterwards** (owner), from the engine's local journal, by a
    recorder that is outside the trading path.
11. **The engine always acts on the last signal** (owner). It never goes back to an earlier one.
12. **A signal reaches the engine two ways:** pushed by its producer as soon as it is computed,
    and read from `SignalWeightsTS`, which stays the record.
13. **The same engine runs backtest, paper and live** (owner). Only the venue and the source of
    the inputs change.
14. **Each fund owns its cash in the book** (owner, 2026-11-23), as a portfolio does in the
    backtest. This replaces open question 11. What follows from it is a proposal:

    - A fill, an internal trade and the fund's share of a fee move the fund's cash.
    - A cash fund's size is its holdings plus its cash. A share fund is sized from its share of
      the account, as today (ADR 0062, decisions 1 and 6).
    - The cash obeys the strategy's execution policy, the one `PortfolioRebalance` runs on its
      book ([ADR 0058](../0058-trade-at-the-next-observed-price.md)): sells before buys, a buy
      limited to the cash on hand plus the negative cash the policy allows, too little cash
      shared pro rata, and a buy that cash cannot cover cut and cancelled once the
      rebalance's sells have filled.
    - A live cash fund's cash never goes below zero, whatever that policy allows, unless the
      account's policy says otherwise (ADR 0062, decision 13; ADR 0063, decision 4).
15. **While an engine runs for an account, the account's funds are locked** (owner,
    2026-11-23). Trading is faster than any call to Markets, so Markets' rows about those
    funds are behind the engine's book. An operation on the funds of a locked account must
    pass the lock: it is checked against the book, not against Markets' rows. The lock is the
    engine's lease on the account. By default the operation waits for the engine (owner); see
    "13. An Operation Arrives While The Account Is Locked".
16. **The engine runs the account's rebalance strategy** (owner, 2026-11-23; ADR 0063,
    decisions 6 and 10), in an account runner above the fund runners. It gives each fund its
    size and moves money between the account itself and its funds. It replaces the
    `owner_size` hook.
17. **A live fund trades under its portfolio's execution policy, and its account's policy can
    only restrict it** (owner, 2026-11-23; ADR 0063, decision 9). A fund trades live by the
    rules its backtest used, and the account decides what it allows its funds.
18. **The engine's own choices are settings of the account's policy**, each with a default
    (owner, 2026-11-23; ADR 0063, decisions 1 and 4). They are not questions settled once for every user.

## Vocabulary

| Term | Meaning |
| --- | --- |
| Engine | One running instance of the execution engine, for one account |
| Provider | The application that imports the engine and connects it to an exchange or a broker |
| Venue | The provider's connection to the exchange or broker for this account |
| Owner | Who a unit of the account belongs to in the book: a virtual fund, or the account itself |
| Account line | The owner "the account itself": units that no fund owns. It is the `direct` owner of ADR 0054 |
| Runner | One rebalance strategy instance bound to one owner: a fund, or one asset of the account line for a direct asset row |
| Target | One signal observation as a `RebalanceTarget`: `intent_id`, signal time and weights |
| Intent | One target being executed by one runner |
| Account runner | The account's own rebalance strategy, run by the engine. It moves money between the account itself and its funds (ADR 0063) |
| Fund order | What one fund's strategy wants to trade in one asset for one target, in units. It is fixed once, at the decision (ADR 0058) |
| Wanted now | The position after what may trade now: the whole fund order, or the slice a strategy's bar allows, after the cash rules |
| Wanted at the end | The position once the fund order is filled |
| Working | Units in order requests sent to the venue and not yet filled or cancelled |
| Internal trade | Units that move between two owners of the same account. No order is sent |
| Order request | What the engine asks the venue to trade: one asset and a signed quantity |
| Book unit | The smallest quantity step of an asset, given by the provider. The book stores whole numbers of it |
| Journal | The engine's local, append-only log of everything that changed the book |
| Lock | The engine's lease on its account. While it is held, only the engine changes what the account's funds hold or were given |
| Recorder | The part that copies the journal into ms-markets records |

## Architecture

```text
signal producer --push--+      SignalWeightsTS --read--+       bars / calendar feeds
                        v                              v               |
     +------------------ ExecutionEngine (one account) ----------------+-------+
     |  account runner: the account's strategy moves money between the         |  strategy speed
     |  account itself and its funds, and gives each fund its size             |
     |                                                                         |
     |  runner: fund A      runner: fund B      runner: direct asset row       |
     |  (portfolio A's      (portfolio B's      (the row's strategy, or        |
     |   strategy)           strategy)           the engine's)                 |
     |        +------- wanted positions in units, per intent -------+          |
     |                             v                                           |
     |   ACCOUNT BOOK (memory): held / cash / wanted / working for each owner  |  book speed
     |     1. internal trades between owners                                   |
     |     2. what is left: one order request for each asset                   |
     |     3. fills split back to the owners                                   |
     |                             |                 local journal ------------+--> recorder:
     +-----------------------------+-------------------------------------------+    OrderManager,
                                   v                                                OrdersTS,
                    venue (provider): orders and fills over websockets              OrderEventsTS,
                                                                                    TradesTS,
                                                                                    fund fills
```

### Three Speeds

| Speed | What happens | Where |
| --- | --- | --- |
| Strategy | A strategy is asked only at its own events: a new target, one of its declared inputs, a change of size, a progress report, an expiry | Worker threads; the strategy and its policy, as the backtest runs them |
| Book | Every answer and fill from the venue, every posted position, every match | One task in local memory |
| Record | The journal is copied to ms-markets | The recorder, a separate task or process |

### Rules Of The Hot Path

The book speed is the hot path. On it:

- no call to ms-markets, and no database over the network;
- no pandas and no frames;
- no call to a strategy;
- the only disk write is one append to the local journal;
- the work for one event depends on the owners of one asset, never on the size of the book;
- no wall-clock read: time arrives with each event, so the same code can replay history.

## The Account Book

### Owners And Units

The book has one sub-ledger for each owner:

- one for each virtual fund of the account's target;
- one for the account itself, the account line. It holds what no fund owns, the positions of
  direct asset rows, and any difference found against the venue.

Quantities are whole numbers of the asset's book unit. The provider gives the unit. Whole
numbers make every sum exact: the owners always add up to the account, to the unit.

### State

For each owner and asset:

| Field | Meaning |
| --- | --- |
| `held` | Units the owner holds |
| `wanted_now` | The position the runner wants to reach at this event |
| `wanted_end` | The position at the end of the intent |
| `working` | Signed units of the open order request that are for this owner |
| Intent | `intent_id`, status, and the strategy's stored state for the asset |

An owner whose runner has no opinion on an asset has no wanted values for it.

For each owner and currency:

| Field | Meaning |
| --- | --- |
| `cash` | The owner's cash in that currency (decision 14; ADR 0062, decisions 8 to 10) |

For each asset:

- the instrument facts from the provider: book unit, order step, minimum order, contract
  multiplier, quote asset;
- the last observed price and its time;
- the open order request, at most one, with its split between owners.

### What The Book Derives

```text
left_end = wanted_end - held - working
left_now = wanted_now - held - working, limited to the side and the size of left_end
```

- `left_now` is what the runner wants traded now. It is what goes to the market.
- `left_end` is what the runner wants traded before the intent ends.
- The limit matters after an internal trade that put an owner ahead of its schedule. The owner
  then holds more than `wanted_now`. That is not a reason to sell: `left_now` is zero.
- A fund's value is its holdings at the provider's prices plus its cash.

### Why Positions And Not Orders

Requirement 4 says each strategy hands its buys and sells to the engine. The proposal is that
the runner hands the position it wants, and the book derives the buy or the sell. The
information is the same. The difference is what happens when things repeat or arrive late:

- **A repeated message changes nothing.** The same wanted position gives the same `left`.
- **A decision that arrives after a fill is still right.** The decision was computed off the
  book's task and can be late; `left` is computed from what is held at that moment.
- **Every fill updates what is left** without the runner doing anything.

This table of held, wanted, working and left is the constantly active book of requirement 6.

### Units Are Fixed At The Decision

A fund order's units are fixed once, at the decision, as in the backtest (ADR 0058, decision
6a). A price move alone never changes a wanted position and never creates an order. Only a new
target, or a new size given by the account's strategy, sizes again.

### Invariants

Checked for the touched asset on every change:

1. The `held` of all owners add up to the account's position in the book.
2. The split of an open order request adds up to its quantity, and the filled split to its
   filled quantity.
3. An owner's `working` is the unfilled part of its split.
4. The legs of an internal trade add up to zero.
5. The `cash` of all owners adds up to the account's cash, in each currency. The account
   itself can be below zero, which is how a shortfall shows. A cash fund cannot, by default
   (ADR 0062, decision 13).

A failed invariant stops routing for that asset and raises an alert. The engine never repairs
the book silently.

### The Journal

Every change of the book is first appended to the journal, then applied.

| Event | Written when |
| --- | --- |
| Target received | A new target arrives from a feed |
| Position posted | A runner posts wanted positions and its stored state |
| Internal trade matched | Owners are matched; the quantities move |
| Internal trade priced | The first price at or after the match is observed |
| Order requested, replaced, cancel requested | Before the request leaves for the venue |
| Venue event | Accepted, rejected, fill, cancelled, expired |
| Fill split | A fill is divided between owners |
| Adjustment | A difference with the venue goes to the account line |
| Money moved | The account's strategy moves cash or units between the account itself and a fund, or refuses an operation |
| Intent expired, runner stopped | A signal passes its lifetime; a runner is halted |
| Checkpoint | The whole book is saved |

Rules:

- **The journal stores results, not inputs.** A restart applies the recorded matches and
  splits. It does not run a strategy or a match again.
- **An order request leaves only after its record is safe on disk.** A fill can be read again
  from the venue. A split between owners cannot: only the engine knows it.
- **Other events can be written in groups.** If the last group is lost in a crash, those
  events did not happen, and the runners decide again.
- **The journal is local.** The proposed default is an SQLite file in write-ahead mode: it is
  in the standard library, safe on a crash, and the recorder can read it with a cursor. A
  provider can replace it.

A checkpoint saves the book, the open order request of each asset and each runner's stored
state. A restart loads the last checkpoint and applies the journal after it.

## The Processes

### 1. Start

1. Take the account's lock in ms-markets. Refuse to start when another application holds
   it. An engine restarted by the application that holds the lock keeps it.
2. Read the configuration: the account's active `AccountTargetAllocation`, its latest
   `PositionSet` and rows, the virtual funds, each strategy from the registry, the engine's
   strategy for direct rows, and the account's own strategy and policy (ADR 0063).
3. Build the owners and the assets. Ask the provider for the instrument facts of each asset.
4. Restore the book from the last checkpoint and the journal. See "12. Restart After A Crash".
5. Connect the venue and the market data. Read the fills since the last one known, then the
   positions and the open orders, and reconcile.
6. Start the account runner, then the fund runners. Each fund runner takes the last signal
   of its portfolio and its stored state, and decides.
7. Accept events.

### 2. A Signal Arrives

1. A feed delivers a complete target: every weight of one signal time. A target cannot arrive
   asset by asset, because `intent_id` is a hash of the time, the signal and all the weights.
2. The engine drops a target whose `intent_id` it has already seen. The push and the table
   deliver the same target with the same id.
3. The target is journaled and handed to every runner of that `signal_uid`.

### 3. A Runner Decides

A fund runner is asked at these events: a new target, an observation of one of the
strategy's declared inputs, a new size for the fund, a progress report from the book, an
expiry. It runs what `PortfolioRebalance` runs in the backtest: the strategy, and its
execution policy on the fund's shares and cash (ADR 0058).

1. Take the last target. Never an earlier one (owner). A target past the strategy's lifetime
   is not acted on.
2. Find the target's earliest moment, as the strategy and its calendar say.
3. At the decision, fix one fund order for each asset: the target weight times the fund's
   size, divided by the price times the contract multiplier, less the units held, then the
   provider's quantization. The size comes from the account's strategy (process 14). An asset
   with no fresh price is not sized and waits. The other assets go ahead.
4. Work out how much of each fund order may trade now: all of it, or the slice the
   strategy's bar allows. Then apply the policy's cash rules to the fund's cash: sells before
   buys, a buy limited to the cash on hand, too little cash shared pro rata, and a buy that
   cash cannot cover cut and cancelled once the sells have filled.
5. Post `wanted_end`, the position once the fund orders are filled, and `wanted_now`, the
   position after what may trade now, with the stored state, as one event.

The runner decides and the venue fills. In the backtest the same step also books the fill, at
the next observed price or at the bar. Live, the fill is the venue's: its price and its
quantity change the fund's shares and cash, and the runner is asked again with what happened
(owner; ADR 0063, decision 7).

The decision runs off the book's task. Strategies work on frames and can take milliseconds;
the book must not wait for them.

### 4. Internal Trades

Run for an asset whenever its row of the book changes:

1. Take each owner's matchable quantity: `left_now`, or `left_end` when the owner's strategy
   offers its whole intent (owner).
2. Buyers are the owners with a positive quantity, sellers those with a negative one. The
   matched quantity is the smaller of the two totals.
3. The smaller side is matched in full. The larger side is matched in proportion to each
   owner's quantity. Remainders of a unit go to the largest remainders first; ties go by a
   fixed order of the owners. The result is always the same for the same input.
4. The quantities move at once: `held` changes for each matched owner, so what is left goes
   to routing without waiting.
5. The price is the first one observed at or after the match (owner). It is stamped on the
   internal trade when it arrives.
6. Each matched owner gets a fund fill marked internal.

Only quantity that has not been sent to the venue is matched. Pulling back a working order to
match it internally is left for later; see "Open Questions".

### 5. Routing What Is Left

1. Add up `left_now` over the owners. After the internal trades it has one side.
2. Compare it with the asset's open order request:
   - none open: request the total;
   - one open on the same side: replace it with the new total;
   - the total is on the other side: reduce or cancel the open request first, then request
     what remains.
3. Record the split: how much of the request is for each owner.
4. Apply the account's own cash settings to the account's cash at the venue (owner; ADR
   0063, decision 4). Sells are sent before buys. When the account's cash cannot pay for every buy,
   the buys share it pro rata and the rest is cut. Each fund is already limited to its own
   cash, so this matters only when the account itself is short, for example after a
   shortfall on its own line.
5. Call the provider's check. It can refuse or reduce the request.
6. Write the request to the journal, make it safe on disk, then send it.

The request says which asset and how much. How it is worked at the exchange, market or limit,
in one order or several, is the provider's. The request can carry two hints from the strategy:
a reference price and a time after which it should not trade.

### 6. Venue Events

- **Accepted.** The request is live. Nothing else changes.
- **Fill.** Drop it when its trade id was already seen. Otherwise split it between the owners
  in proportion to the unfilled part of each one's split, with the same remainder rule as
  internal trades. Fees are split the same way. `held` and `working` change. Each owner gets a
  fund fill marked market.
- **Rejected, cancelled by the venue, expired.** `working` is released. The asset is held
  back: the engine does not send the same request again by itself. The runners are told, and
  routing resumes when one of them posts again. What to do with unfilled volume is the
  strategy's rule, never the engine's (owner).

After a fill the book sends each affected runner one progress report: what was filled against
what it wanted. Reports are merged, so a runner never has more than one waiting.

### 7. A Signal Passes Its Lifetime

1. The engine sets a timer at the signal's time plus the strategy's lifetime.
2. At that time the runner's wanted positions are withdrawn: `left` becomes zero.
3. Its share of the open order request is cancelled.
4. The intent ends as `expired`. The owner keeps what it holds (owner).

### 8. The Target Changes

A new `PositionSet` is read off the hot path.

- **A new portfolio row:** a runner starts for its fund. The fund already exists, because
  writing the exposure created it (ADR 0054).
- **A changed share:** the account's strategy gives the fund its new size (process 14), and
  its runner is asked again.
- **A removed row:** the runner stops, its wanted positions are withdrawn and its share of
  open requests is cancelled. Its holdings are not sold. What the records say about them is an
  open question.

### 9. Reconciliation

On a timer, and after every reconnection:

1. Read the fills since the last one known and apply the ones that are missing.
2. Compare the venue's positions with the book.
3. A difference goes to the account line as an adjustment, with an alert. The funds keep what
   their fills say. The account line can go negative (owner).
4. An order at the venue that the engine did not send is left alone.

### 10. Recording

1. The recorder reads the journal from its own cursor.
2. It writes ms-markets records in batches. Every record has an identifier built from the
   journal, so writing it twice changes nothing.
3. It moves its cursor only after a batch is written.

If ms-markets cannot be reached, trading continues and the journal grows. The recorder's lag
is measured. The provider can set a lag above which the engine takes no new target.

### 11. Stop And Kill Switch

- **Stop:** take no new target, cancel or leave the open requests as the provider chooses,
  wait for the venue's answers, write a checkpoint, let the recorder finish, release the lock.
  The lock is released only after the recorder has caught up, so Markets' rows are current
  when operations go back to Markets.
- **Kill switch:** stop routing now and cancel every open request. The book stays as it is.
  Trading resumes only when a person says so.

### 12. Restart After A Crash

1. Load the last checkpoint and apply the journal after it.
2. For each order request in the journal with no answer from the venue, ask the venue by its
   id. If it exists, take it back. If it does not, it was never sent, and what was left shows
   again.
3. Read the fills since the last one known, then reconcile the positions.

When there is no local state, for example on a new machine, the book is built from ms-markets:
each owner's holdings from the fund fills the recorder wrote. What was never recorded shows as
a difference on the account line.

A crash does not release the lock. Markets' rows are still behind the book then, so the
account stays locked until the engine has restarted and stopped cleanly. Otherwise the
application that manages the account, or an Organization admin, releases it (owner).

### 13. An Operation Arrives While The Account Is Locked

The lock covers every write that changes what a fund of the account holds or was given: the
capital allocations of ADR 0062, and the fund holdings a sync writes. Markets never calls a
provider's code ([ADR 0060](../0060-producers-publish-markets-reads-only-its-own-tables.md)),
so the operation reaches the engine through Markets' own rows:

1. A person sends the operation to Markets, as ADR 0062 says.
2. Markets sees that the account is locked. It checks only what the book cannot change: the
   fund is a cash fund of the account, and the currency is one its portfolio allows. It keeps
   the operation as waiting. It does not check cash or units.
3. The account runner reads the waiting operations off the hot path, as the engine reads a
   new target. It checks each one against the book, under the account's policy (ADR 0063):
   the fund's cash or units now, and the account's available cash now.
4. An accepted operation is journaled and applied to the book: cash or units move between the
   account line and the fund. A refused one is journaled with its reason.
5. The recorder publishes the result in journal order, after the fills that came before it.
   Markets turns the waiting operation into the capital allocation, or marks it refused.

Fund B has 50,000 in cash and the engine spends it. A person then asks to move 50,000 away
from fund B. Markets' rows still show the cash, because the recorder has not written those
fills. Without the lock Markets would accept, and fund B's cash would go to -50,000, which
ADR 0062 forbids (decision 13). With the lock the engine answers from its book and refuses.

- **Waiting or refusing is a setting of the account's policy.** An engine that runs all day
  needs operations to wait for it. A user who stops the engine to move money can have them
  refused instead. The default is to wait (owner; ADR 0063, decision 4).
- **A sync of a locked account** is written by the engine's recorder only, from its
  checkpoints.
- **With no engine running,** ADR 0062 works as written: Markets checks its own rows and
  writes in one transaction.

### 14. The Account's Strategy Moves Money

The account has a rebalance strategy of its own (ADR 0063, decision 6). The engine runs it in
the account runner. It decides how big each fund is and when money moves between the account
itself and a fund. It sends no order: a move changes owners in the book, as an internal trade
does.

| The row's strategy | A fund's size | When money moves |
| --- | --- | --- |
| To the target at every sync | Its share of the account's value, as today | At a sync, to bring the fund back to its share |
| Manual | Its own value: its holdings plus its cash | Only when a person's operation passes the lock (process 13) |

- **A row may name its strategy.** A row that names none uses the account's. An account that
  names none keeps today's behaviour: to the target at every sync for a row that states a
  share, manual for a row that states none (owner; ADR 0063, decision 11).
- **A user's strategy** is another class on the same base, for example back to the target
  every month. The engine runs it the same way.
- **A move is journaled** before it is applied, and the fund's runner is asked again with its
  new size.
- **With no engine** nothing runs an account's strategy. A manual move is a Markets
  operation, and a fund at a share is sized by the provider's sync, as today.

### Where Each Part Runs

| Part | Runs as | Why |
| --- | --- | --- |
| The book: internal trades, routing, fill split | One task. It is the only writer | No locks. The order of the journal is the truth, so it can be replayed exactly |
| Venue and market data connections | The provider's tasks or threads. They put events on the book's queue | Websocket traffic never blocks the book |
| Runners | Worker threads, one decision at a time for each runner | Strategies work on frames |
| Journal | The book's task | It is written before the change is applied |
| Recorder | Its own task or process, reading the journal | A slow or missing database does not touch trading |
| Reconciliation, the lock, waiting operations, checkpoints | Timers | They are not on the hot path |

## What A Provider Implements

The provider imports the engine, gives it the parts below and runs it in its own process
(owner). The names and signatures are a sketch, not a final API.

### How It Is Hooked

```python
class MyEngine(ExecutionEngine):
    """The provider's engine: the hooks it wants to change."""

    def quantize(self, asset_identifier: str, raw_units: float) -> int:
        ...  # the provider's rounding to book units


engine = MyEngine(
    account_uid=account_uid,
    venue=MyVenue(...),                # required
    market_data=MyMarketData(...),     # required
    signal_feeds=[PushSignalFeed(...), TableSignalFeed(client)],
    journal=SqliteJournal(path),
    recorder=MarketsRecorder(client),
    direct_row_strategy_uid="...",     # the strategy for direct rows that name none
)
await engine.run()
```

### Required: The Venue

```python
class Venue(Protocol):
    async def submit(self, request: OrderRequest) -> None: ...
    async def replace(self, order_id: str, *, quantity: int) -> None: ...
    async def cancel(self, order_id: str) -> None: ...

    def events(self) -> AsyncIterator[VenueEvent]: ...     # accepted, rejected, fill, ...

    async def order(self, order_id: str) -> OrderSnapshot | None: ...
    async def open_orders(self) -> list[OrderSnapshot]: ...
    async def positions(self) -> dict[str, int]: ...       # asset_identifier -> book units
    async def fills_since(self, cursor: str | None) -> list[Fill]: ...
```

What the venue must guarantee:

| The provider must | Why |
| --- | --- |
| Carry the engine's order id to the exchange, or keep its own safe map to it | After a crash the engine asks for a request by this id to learn whether it was sent |
| Give every fill a trade id that is unique for the account | Events repeat after a reconnection. The book drops a fill it has seen |
| Report every event with the engine's order id | The fill is split with the split of that request |
| Report quantities in book units and the exchange's time on every event | The book uses whole units. Records use the time of the trade, not of the engine |
| Answer `order`, `open_orders`, `positions` and `fills_since` | Restart and reconciliation depend on them |
| Map `asset_identifier` to its own symbols | The engine knows only ms-markets assets |

### Required: Market Data

```python
class MarketData(Protocol):
    def prices(self) -> AsyncIterator[Price]: ...           # asset_identifier, price, time
    async def instrument(self, asset_identifier: str) -> Instrument: ...
```

`Instrument` carries the book unit, the order step, the minimum order, the contract multiplier
and the quote asset. The backtest needs the same facts: `InstrumentExecutionSpec` in
`src/msm_portfolios/rebalance_strategy/accounting.py` already has the quantity step, the
multiplier and the price asset. One instrument description should serve both.

The engine uses a price for three things: sizing a decision, valuing an owner's holdings for
the strategy's view, and stamping an internal trade.

### Optional: Feeds

ms-markets gives two signal feeds: one that reads `SignalWeightsTS`, and one that takes a
target handed to it in the same process. A provider adds its own when the signal producer runs
elsewhere, over whatever transport it uses. The strategy's other inputs, such as bars and
calendar events, arrive the same way: the names in `declared_dependencies()` are the list of
what a runner subscribes to.

### Hooks With A Default

| Hook | Default | Owner of the rule |
| --- | --- | --- |
| `quantize` | Round toward zero to the book unit, as the backtest does | The provider (owner) |
| `check_order` | Accept | The provider: buying power, limits, price bands |
| Strategy for direct rows | None. A direct row that names no strategy is refused when none is set | The provider (owner) |
| Journal safety | Order requests are safe on disk before they leave | The provider |

A fund's size is not a hook. The account's rebalance strategy gives it (process 14).

### Choices Are Settings

A rule that different users may reasonably want differently is a setting with a default, not a
fixed behaviour of the engine (ADR 0063, decision 1). The engine reads them in three places:

| Where | What it chooses |
| --- | --- |
| The fund's portfolio strategy and its `ExecutionPolicy` | How the fund trades: the seven settings of ADR 0058, the signal's lifetime, and whether its whole intent is offered to internal trades |
| The account's policy, for its funds | What the account allows a fund: cash in, cash out, cash below zero, a removed portfolio, units that no record explains |
| The account's policy, for the engine | An operation while the account is locked, how a fill is split between owners, a request the venue rejects, a strategy that raises, pulling back a working order for an internal trade, and the recorder's lag |

- **A fund trades under its portfolio's policy.** The account's policy can only restrict it
  (decision 17).
- **The account's own seven settings** rule the account's cash at the venue, in routing
  (process 5).

### Who Builds What

| ms-markets ships | The provider implements |
| --- | --- |
| The strategies, their policies and the account runner | The venue: orders, the event stream, the four reads |
| The account book: internal trades, routing, fill split, invariants | Market data: prices and instrument facts |
| The journal, the checkpoint and the restart | A signal transport, when the producer is not in the same process |
| A simulated venue, and the backtest and paper wirings | The hooks it wants to change |
| The feed interfaces and the two signal feeds | The process, its credentials and its limits |
| The recorder to ms-markets | |
| Tests a venue must pass | |

The tests for a venue run against the exchange's test environment. They check that a request
sent twice with the same id trades once, that a request can be found after a disconnection,
that fills replayed after a reconnection carry the same trade ids, and that the four reads
agree with the event stream.

## Records In ms-markets

Written by the recorder, never on the hot path.

| From the journal | ms-markets record | Exists today |
| --- | --- | --- |
| One round of routing | `OrderManager` | Yes |
| Order requests | `OrdersTS`, linked by `order_manager_identifier` | Yes |
| Accepted, rejected, cancelled, expired | `OrderEventsTS` | Yes |
| Fills | `TradesTS` | Yes |
| Fill splits and internal trades | Fund fills | No |
| Wanted positions and status of each owner | Rebalance state for each owner | No |
| Checkpoint positions | `AccountHoldingsSet` and `AccountHoldingsStorage` | Yes |
| Start, stop and heartbeat of the engine | Engine session and lock | No |
| The answer to an operation that waited for the engine | The capital allocation of ADR 0062, or its refusal | No |

### Fund Fills

`TradesTS` has one row for each trade of the account with the market and no fund. Two things
have nowhere to go today:

- which owner a market trade was for, and how a trade for two owners was divided;
- internal trades, where the account traded nothing with the market.

A fund fill is one row for each owner and fill:

| Column | Meaning |
| --- | --- |
| `time_index` | The time of the fill, or of the match for an internal trade |
| `fill_identifier` | Built from the trade or the internal trade, and the owner |
| `owner_type`, `owner_uid` | A fund, or the account itself, as in `AccountAllocationLinesStorage` |
| `asset_identifier` | The asset |
| `quantity`, `direction` | Units and side |
| `price` | The fill's price, or the internal trade's price |
| `source` | `market` or `internal` |
| `trade_identifier` | The `TradesTS` row, for a market fill |
| `internal_trade_identifier` | Shared by both sides of an internal trade |
| `rebalance_intent_id` | The intent the fill served |
| `fee`, `fee_asset_identifier` | The owner's share of the fee |
| `settlement_asset_identifier` | The currency the fill settled in, as in `TradesTS`, so it moves the owner's cash in that currency (ADR 0062, decision 7) |

An owner's holdings are the sum of its fund fills.

ADR 0062 makes fund fills a Markets record that whoever trades for a fund writes: the engine's
recorder, or a provider that trades for its funds without the engine (decision 7).

### Rebalance State For Each Owner

The stored history of the active book: for each owner, intent and asset, the wanted positions,
what was held, what was working and the status. `PortfolioRebalanceStateTS` stores the same
thing in weights for a backtest portfolio. It cannot be reused: a portfolio never receives
real fills (ADR 0042), and one portfolio is followed by many accounts, each with its own
progress.

### Fund Holdings At A Sync

Today a sync splits the account's holdings between the funds with a rule, in proportion to
their targets. With an engine, the fund fills are an extra layer of information, and they take
precedence (owner):

1. Each fund first keeps the units its own fills gave it.
2. The units of the account that no fill explains go through the existing rule, among the
   share funds that still want more. A cash fund gets none (owner; ADR 0062, decision 5).
3. What no fund takes stays with the account.
4. When the account holds fewer units than the fills add up to, the funds keep what their
   fills say and the account's own line shows the shortfall as a negative (owner).

Funds A and B are share funds. Fund A has a target of 500 MSFT and bought all of it through
the engine. Fund B has a target of 375 and has bought 100. The account holds 800, because 200
were transferred in:

| MSFT | From its own fills | From the rule, on the 200 left | Stored holding |
| --- | --- | --- | --- |
| Fund A | 500 | 0, its target is reached | 500 |
| Fund B | 100 | 200, it still wants 275 | 300 |
| The account itself | | 0 | 0 |
| Total | 600 | 200 | 800 |

The rule itself does not change. `proportional_attribution` is given the units left after the
fills, and each share fund's target minus what it already owns. An account with no engine
has no fills, so everything goes to the rule, as today. While an engine runs, only its
recorder writes the fund holdings of its account (decision 15).

## Backtest, Paper And Live

| | Signals and inputs | Venue | Runners and book |
| --- | --- | --- | --- |
| Backtest | Tables, replayed in time order | Simulated, shipped by ms-markets | Same |
| Paper (`Account.is_paper`) | Live feeds | Simulated | Same |
| Live | Live feeds | The provider's | Same |

- **A signal alone can be backtested** (owner): a signal, a strategy, bars and a size run one
  runner against the simulated venue. No portfolio, account or storage is needed.
- **A whole account can be backtested:** all its runners go through the same book. This is the
  only backtest that exercises internal trades.
- **The simulated venue decides the fill price,** for example the next observed price, or the
  VWAP of the bar.
- **Proposed gate to go live.** A strategy qualifies when it declares every input, reads no
  clock and no storage in its decision, gives the same decisions when a recorded live journal
  is replayed in the backtest wiring, and gives the same decisions after a restart in the
  middle of an intent.

## Failure Behaviour

| What fails | What the engine does |
| --- | --- |
| ms-markets cannot be reached | Trading continues. The journal grows. Above the provider's lag limit, no new target is taken |
| The venue disconnects | Routing stops. On reconnection: fills since the last known, then reconciliation, then routing resumes |
| No fresh price for an asset | That asset is not sized and its internal trades are not priced. The others go on |
| The engine crashes | Restart from the checkpoint and the journal, then the venue's answers. The account stays locked |
| A person changes a fund while the engine trades | The operation waits for the engine, which answers from its book (decision 15) |
| A venue event arrives twice | Dropped by its trade id or by the state of its request |
| The venue's position differs from the book | The difference goes to the account line, with an alert. Funds are not changed |
| A second engine starts for the account | It finds the lock taken by another application and refuses |
| A strategy raises | That runner stops: its wanted positions are withdrawn and its share of requests cancelled. The others go on |
| An invariant fails | Routing stops for that asset, with an alert |
| A push feed misses a target | The table feed delivers it |

## Worked Example

Portfolio A holds AAPL and MSFT. Portfolio B holds MSFT and JNJ. The account also holds TSLA,
which is in no fund. Prices are AAPL 200, MSFT 400, JNJ 150 and TSLA 250.

The account target:

| Row | Exposure | Strategy |
| --- | --- | --- |
| Portfolio A | 40% of the account's value | Portfolio A's, `ImmediateSignal` |
| Portfolio B | 30% of the account's value | Portfolio B's, `ImmediateSignal` |
| TSLA, a direct asset row | 5% of the account's value | Named on the row: a participation strategy |

The book at the start. The account is worth 1,000,000, so fund A's size is 400,000 and fund
B's is 300,000:

| Owner | AAPL | MSFT | JNJ | TSLA |
| --- | --- | --- | --- | --- |
| Fund A | 1,200 | 400 | | |
| Fund B | | 375 | 1,000 | |
| The account itself | | | | 1,200 |
| Account total | 1,200 | 775 | 1,000 | 1,200 |

Both signals change at the same moment, in session. Signal A goes to 70% AAPL and 30% MSFT.
Signal B goes to 60% MSFT and 40% JNJ. The TSLA row wants 200 at the end, and its strategy
asks for 50 now.

| Owner | Asset | Held | Wanted now | Wanted at the end | Left now |
| --- | --- | --- | --- | --- | --- |
| Fund A | AAPL | 1,200 | 1,400 | 1,400 | +200 |
| Fund A | MSFT | 400 | 300 | 300 | -100 |
| Fund B | MSFT | 375 | 450 | 450 | +75 |
| Fund B | JNJ | 1,000 | 800 | 800 | -200 |
| The account itself | TSLA | 1,200 | 1,150 | 200 | -50 |

Internal trades, then routing:

| Asset | Internal trade | Order request | Split |
| --- | --- | --- | --- |
| AAPL | | buy 200 | fund A 200 |
| MSFT | 75 from fund A to fund B | sell 25 | fund A 25 |
| JNJ | | sell 200 | fund B 200 |
| TSLA | | sell 50 | the account itself 50 |

Cash is left out of these tables. Each fund's sells pay for its buys, and with the default
policy a buy leaves only as its fund's cash arrives.

The next MSFT price observed is 400.10, so the internal trade is stamped 400.10. The four
requests fill. The book afterwards:

| Owner | AAPL | MSFT | JNJ | TSLA |
| --- | --- | --- | --- | --- |
| Fund A | 1,400 | 300 | | |
| Fund B | | 450 | 800 | |
| The account itself | | | | 1,150 |
| Account total | 1,400 | 750 | 800 | 1,150 |

What the recorder writes: one `OrderManager` row, four `OrdersTS` rows, four `TradesTS` rows,
and six fund fills:

| Owner | Asset | Quantity | Source |
| --- | --- | --- | --- |
| Fund A | AAPL | +200 | market |
| Fund A | MSFT | -75 | internal |
| Fund B | MSFT | +75 | internal |
| Fund A | MSFT | -25 | market |
| Fund B | JNJ | -200 | market |
| The account itself | TSLA | -50 | market |

### A Fill For Two Owners

Later both funds buy MSFT: fund A 60 and fund B 40. The engine sends one request, buy 100, with
the split 60 and 40. It fills in two parts:

| Fill | Fund A | Fund B | How |
| --- | --- | --- | --- |
| 33 | 20 | 13 | In proportion, 19.8 and 13.2. The spare unit goes to the larger remainder |
| 67 | 40 | 27 | What each still had unfilled |
| Total | 60 | 40 | |

## Consequences

- One strategy object decides in backtest, paper and live. The engine adds no second copy of a
  strategy's rules.
- The engine knows which owner holds which units at every moment, from fills. ms-markets gets
  that knowledge afterwards as fund fills.
- Trading does not depend on ms-markets being reachable. The price is a local journal that
  must be kept safe, and a recorder whose lag must be watched.
- A provider has a small, fixed list to implement, and tests that say when it is right.
- Two engines on one account would double every order. The lock is therefore part of
  starting, and an engine that cannot check it does not start.
- While an engine runs, a person's operation on a fund is answered by the engine, not by
  Markets at once. Operations on an account with no engine are unchanged.
- The book's task is the only writer. A slow strategy, a slow database or a slow connection
  cannot block it, and none of them can change the book directly.
- New records are needed in ms-markets: fund fills, the rebalance state for each owner, and the
  engine session.
- The allocation at a sync changes for accounts run by an engine (ADR 0053).
- The wheel gains a package. `pyproject.toml` lists the packages it ships, and the new one has
  to be added there.

## Suggested Order Of Work

1. **The book alone.** State, internal trades, routing, fill split, invariants, journal,
   checkpoint and restart, against the simulated venue. Tests replay random streams of events
   and check the invariants, and that a restart gives the same book.
2. **The provider contracts and the tests a venue must pass.**
3. **The runner,** calling the strategies as they are today, `ImmediateSignal` first.
4. **The recorder, the new records and the lock.**
5. **The feeds:** the table feed, then the push feed.
6. **A paper account, end to end.**
7. **A first provider, live,** with one fund, then with two funds that share an asset.

The corrections to the strategies listed below proceed separately. They do not block steps 1
and 2.

## Points Outside The Engine's Architecture

These came up in the discussion. They are kept here so they can be taken up again.

### Decided By The Owner On 2026-11-18

- **Signal lifetime.** It is a field on `RebalanceStrategyBase`, so every strategy has it and
  backtest and live apply the same rule. A signal older than the lifetime is disregarded; the
  owner's examples were 30 minutes and 20 days. It is part of the strategy's hash: a different
  lifetime is a different portfolio. Not set means a signal never expires. The last signal is
  the only candidate; there is no fallback to an earlier one. When the lifetime passes on a
  partly executed intent, it stops and keeps what it holds, under a new `expired` status.
  Done on 2026-11-22 for the backtest path
  ([#114](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/114)):
  `RebalanceStrategyBase.signal_lifetime`, a `timedelta`, `None` by default. The decision
  does not name the clock; the implementation infers it from step 1 of "7. A Signal
  Passes Its Lifetime" (the signal's time plus the lifetime) and measures economic time,
  never the job's: an event at `t` acts on the latest signal, which is too old when
  `t - time_index > signal_lifetime`, so a signal exactly that old is still valid. A
  target too old at its earliest moment, or at its first bar, never trades. A running
  intent stops at its next event (the first instant an order has an eligible price, or
  its next bar), and each unfinished order writes an `expired` row with no price; the
  ledger records it as progress. The proposed engine's timer would end the intent at the
  signal's time plus the lifetime; the backtest has no event there and ends it at the
  next one, with the same fills. A strategy without a lifetime keeps its revision, its
  portfolio configuration hash and its update hashes.
- **Unfilled volume.** What happens when volume does not fill is the rebalance strategy's
  rule, never the engine's.
- **Size.** The size is never a constant in the strategy. It is given by whoever runs it: the
  fund in live, the portfolio in a backtest. It is always set, and a run without it raises.
  The default of 50,000,000 in `VolumeParticipation`, `LiquidityConstrained` and
  `TrailingAverageDailyVolumeParticipation` is wrong and goes. Done on 2026-11-22
  ([#113](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/113)):
  `total_notional` is required there.
- **Strategy registry.** Portfolios and direct asset rows name their strategy through
  `RebalanceStrategyMetadata`, by `rebalance_strategy_uid`.
- **Internal matching** of the whole intent is a setting of the strategy.
- **Order quantization** is the provider's.
- **Existing portfolio identities** are not a concern now: there are no real portfolios yet.

### Known Gaps In The Rebalance Strategies

The owner said not to worry about these for now.

- `RebalanceStrategyBase` has two loops that call `apply_event`, `build_transitions` and
  `build_accounting_schedule` with `simulate_accounting_event`, and the choice of the target
  is copied in both. The engine needs one entry that decides one event. Since #89 and
  [#90](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/90)
  (2026-11-22) `apply_event` and the schedule are gone; `build_transitions` still has two
  loops, one at the next observed price and one at a strategy's own bars, both running the
  execution policy on a book. The bar loop asks the strategy for each bar's slice
  (`bar_slices`).
- The weights-only loop treats `weight_after` as executed. In the engine it is only what the
  strategy wants.
- Deciding and filling are one step in the backtest: the policy works out how much may trade
  and books the fill together. The engine needs the first without the second (ADR 0063,
  decision 7).
- `TrailingAverageDailyVolumeParticipation` adds the notional it intends to trade to its
  consumed capacity. Live it must add what was traded. Since #90 the backtest adds what
  filled in the book, after the cash rules; live, it is still what the venue fills.
- `TimeWeighted` advances by elapsed time and assumes each slice filled. `ImmediateSignal`
  asks for everything at once. Neither has a rule for a part that does not fill. Since
  #90 both run the execution policy: a buy short of cash waits for the rebalance's sells
  and is then cut, and `TimeWeighted`'s next slice is what its schedule is still short
  of, so a part that did not fill is asked for again at the next bar.
- A ledger portfolio has two sizes today: `initial_nav`, which is required, and the strategy's
  own 50,000,000, which the strategy uses. Since #113 and #90 the strategy's size is
  `total_notional`, required, and it is the unit of the strategy's book; the ledger trades
  the same fraction of its own orders, sized at `initial_nav`. The two can still differ
  (ADR 0059, "Implementation Notes").
- A weights-only portfolio has no size in its configuration.
- A `Portfolio` row has a `signal_uid` and no strategy uid, and nothing writes the registry.
- There is no VWAP strategy. The price bars carry a `vwap` column.
- `apply_event` works on pandas frames. That is fine for decisions every few seconds or
  slower. Signals many times a second would need a lighter entry.
- [Issue 89](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/89) changes
  the same loop. When this ADR was written, its calendar part was uncommitted on another
  branch and its fill part, each asset at its next observed price and a ledger that books the
  recorded fills, was not in that change.

### Other Points

- **No database change capture is needed.** `SignalWeightsTS` is appended in time order and
  has an index on `signal_uid` and `time_index`, so it is its own log. The MetaTables client
  calls `run_post_update_routines` after a run is recorded as finished; a signal can push from
  there.
- **The ledger reducer keeps its role** for portfolio backtests. It is not used by the book.
- **A paper account** is the same engine with the simulated venue.

## Open Questions

Proposals in this ADR that the owner has not decided:

1. The module's name, `msm_execution`. `msm.time_index.execution` and `msm.models.execution`
   already hold the execution records.
2. One open order request for each asset, changed by replace, instead of several at once.
3. Decided on 2026-11-23, as a setting of the account's policy (decision 18): a fill is
   split between owners in proportion by default, so they get the same average price.
4. Decided, as a setting: a request the venue rejects or cancels is held back until a runner
   posts again, by default.
5. Decided, as a setting: a runner whose strategy raises stops alone by default, and the
   others go on.
6. What the records say about the holdings of a fund whose row was removed from the target,
   or whose portfolio was retired ([ADR 0049](../0049-portfolio-lifecycle-and-account-history.md)).
   Answered for a cash fund: it keeps what it holds and stops rebalancing (owner; ADR 0062,
   decision 12). A share fund is as today.
7. The journal's default, an SQLite file, and its default safety.
8. `OrderManager` as one round of routing.
9. Where the new tables are declared. Their migrations belong to ms-markets either way.
10. Decided, as a setting: a working order is not pulled back to match it internally, by
    default.
11. Decided on 2026-11-23: each fund owns its cash in the book. See decision 14.
12. Decided, as a setting: the recorder's lag stops no new target by default, and trading
    continues.
13. A direct asset row has no signal. Whether the lifetime of its strategy applies to the time
    of its `PositionSet`.
14. An internal trade moves its quantities at the match and gets its price at the next
    observed one. Between the two, the fund fills have no price.
15. Answered by ADR 0062 and ADR 0063: the account's rebalance strategy moves the money. A
    share fund goes to its share at every sync, as today. A cash fund changes only by a
    capital allocation a person records.
16. Decided on 2026-11-23: an operation waits for the engine by default, and Markets keeps it
    as waiting until the engine's answer is published (decision 15).
17. Decided on 2026-11-23: after a crash the lock is released by the application that manages
    the account, or by an Organization admin, as for `managed_by` (ADR 0060, decision 4).
18. Decided on 2026-11-23: the account runner, and the account's strategy in place of the
    `owner_size` hook (decision 16).
19. Decided on 2026-11-23: a live fund trades under its portfolio's policy, restricted by its
    account's (decision 17).
20. Decided on 2026-11-23: the account's seven settings rule the account's cash at the venue
    (process 5).

## Not Verified

- Nothing was run or measured. The speed of the book is design reasoning.
- That a strategy can be rebuilt from the `configuration_json` of the registry.
- That MetaTables has no way to subscribe to a table: this comes from a search of the pinned
  documentation and of the installed client.
- Whether a hosted resource of the platform can run a permanent process that holds websocket
  connections.
- The quantities in the examples were computed by hand.
