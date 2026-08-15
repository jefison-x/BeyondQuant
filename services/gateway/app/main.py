from fastapi import FastAPI


SERVICE = "byq-gateway"
VERSION = "0.1.0"
app = FastAPI(title="BeyondQuant Gateway", version=VERSION)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
    }


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
        "dsh_runtime_integration": "not-configured",
    }
