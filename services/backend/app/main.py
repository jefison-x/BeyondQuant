from fastapi import FastAPI
from fastapi import HTTPException

from .data_provider import (
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderRateLimited,
    TushareProvider,
)


SERVICE = "byq-backend"
VERSION = "0.1.0"

app = FastAPI(title="BeyondQuant Backend", version=VERSION)
data_provider = TushareProvider.from_env()


def _health_payload() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return _health_payload()


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return _health_payload()


@app.get("/v1/data/daily")
def daily_data(
    ts_code: str | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, object]:
    try:
        request = DailyRequest(
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        ).normalized()
        result = data_provider.fetch_daily(
            request
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ProviderCredentialsMissing as error:
        raise HTTPException(status_code=503, detail="data provider is unavailable") from error
    except ProviderAuthorizationError as error:
        raise HTTPException(status_code=503, detail="data provider is unavailable") from error
    except ProviderRateLimited as error:
        raise HTTPException(status_code=429, detail="data provider is rate limited") from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail="data provider request failed") from error

    return {
        "data": [bar.as_dict() for bar in result.bars],
        "provenance": result.provenance.as_dict(),
    }
