# Phase 70 Chrome DevTools MCP review

- Date: 2026-08-29
- Frontend: isolated Compose `http://127.0.0.1:32769`
- Gateway: isolated Compose `http://127.0.0.1:32768`
- Identity: isolated bootstrap administrator

## Desktop catalogue

The Stock Pool creation dialog returned exactly six canonical Product identities:
上证50、沪深300、科创50、中证1000、中证500和创业板指. With all six exact
evidence rows present, every item was enabled and displayed its member count and
latest snapshot date. The Data Center synchronization tab reported `6/6 可用`.

Backend and Gateway were restarted, returned healthy, and an authenticated browser
reload still reported `6/6 可用`; the catalogue therefore recovered from PostgreSQL
rather than browser or process memory.

## Waiting state and responsive view

One `market_index_weight_snapshots` row was removed only from the disposable Phase 70
database to simulate incomplete evidence. Raw index weights remained intact. The Data
Center then reported `5/6 可用`, while the selector still showed all six candidates and
rendered 创业板指 as disabled with `等待可信数据同步`. The same dialog was reviewed at
390×844 and remained usable without exposing a hidden/provider action.

## Boundary diagnostics

- Captured fetch/XHR traffic remained on `http://127.0.0.1:32769` and used only
  `/api/auth`, `/api/product` and normalized `/v1` Gateway routes.
- There were no external origins and no 5xx responses.
- Chrome reported zero console warning/error messages. It recorded one transient label
  autofill issue during navigation; a settled-DOM scan found zero `label[for]` elements
  without a matching id.

## Captures

- `chrome-index-selector.png`: all six exact snapshots ready.
- `chrome-data-center.png`: Data Center `6/6` projection.
- `chrome-index-selector-waiting.png`: five enabled identities and one disabled candidate.
- `chrome-index-selector-mobile.png`: 390×844 responsive waiting-state review.
