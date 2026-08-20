"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(
    title="Zhizhi AI Agent",
    description="Python + LangChain/LangGraph Agent platform (job-ready portfolio)",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
