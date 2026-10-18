from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# read BE_PROJ/.env (GEMINI_API_KEY, ALERT_SLACK_WEBHOOK, SMTP_*, ...) without overriding real env vars
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app import alerts_engine  # noqa: E402
from app.routers.alerts import router as alerts_router  # noqa: E402
from app.routers.chat import router as chat_router  # noqa: E402
from app.routers.dashboard import router as dashboard_router  # noqa: E402
from app.routers.insights import router as insights_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    alerts_engine.start_scheduler()  # first evaluation runs a few seconds after startup
    yield
    alerts_engine.stop_scheduler()


app = FastAPI(title="BE_PROJ Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")


@app.get("/")
def root():
    return {"message": "BE_PROJ Backend running ✅"}