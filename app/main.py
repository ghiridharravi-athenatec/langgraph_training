from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import router as router
from app.core import config
from app.core.bootstrap import seed_defaults


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_defaults()
    yield


app = FastAPI(title="My FastAPI App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/")
def root():
    return {"message": "FastAPI is running"}
