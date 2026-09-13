"""Application settings.

Every value is read from environment variables (optionally via a local ``.env``
file). No secrets are hardcoded anywhere in this project — see ``.env.example``
for the full list of supported variables.
"""

from functools import lru_cache
from typing import List, Optional, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Environments in which an unset ``API_KEY`` is tolerated (local demo only).
UNSECURED_ENVIRONMENTS = frozenset({"development", "test"})

#: Browser origins allowed to call the API. Declared as a union on purpose:
#: pydantic-settings JSON-decodes a plain ``List[str]`` read from the
#: environment, so a comma separated ``CORS_ORIGINS=a,b`` would fail at startup
#: before the validator below could run. A union makes the JSON decode
#: best-effort, so both forms work and the attribute is always a list.
CorsOrigins = Union[List[str], str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_name: str = "supply-chain-agent-backend"
    environment: str = "development"
    debug: bool = False
    #: Create tables and load the seed data on startup when the DB is empty.
    auto_seed: bool = True

    # --- Server ------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: CorsOrigins = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./supply_chain.db"
    sql_echo: bool = False

    # --- Agent -------------------------------------------------------------
    #: Groq model used when the LLM explainer is configured. Ignored otherwise.
    #: ``openai/gpt-oss-120b`` is Groq's recommended replacement for the
    #: retired ``llama-3.3-70b-versatile``.
    agent_explainer_model: str = "openai/gpt-oss-120b"
    #: Seconds before a single explainer call gives up. Small because the call
    #: is a nicety: if it is slow, the deterministic template takes over.
    agent_explainer_timeout: float = 30.0
    #: Token budget for one explainer call. This has to clear the reasoning
    #: tokens a reasoning model spends before it writes a single word: on this
    #: trace ``gpt-oss-120b`` burned ~700, so a 700 budget returned an empty
    #: completion (``finish_reason=length``) and fell back to the template.
    agent_explainer_max_tokens: int = 2048
    #: How much thinking a reasoning model may spend on a summary. "low" keeps a
    #: live demo responsive (measured ~1 s against ~3-40 s unbounded) without
    #: hurting the prose. Empty sends nothing, for models that reject the field.
    agent_explainer_reasoning_effort: str = "low"

    # --- Rate limiting -----------------------------------------------------
    #: Set false to disable the limiter entirely (the test suite does this).
    rate_limit_enabled: bool = True
    #: Applied to every endpoint.
    rate_limit_default: str = "200/minute"
    #: Applied to the agent trigger, which can spend real money per call.
    rate_limit_agent: str = "10/minute"
    #: Applied to the optimizer, which is cheap but still caller-driven work.
    rate_limit_optimize: str = "60/minute"

    # --- Secrets (optional; injected from the environment, never committed) --
    #: Guards every state-changing endpoint (``X-API-Key`` header). Required
    #: whenever ``ENVIRONMENT`` is not development/test.
    api_key: Optional[str] = None
    #: When set, the agent's explanation is written by a Groq-hosted model and
    #: checked against the reasoning trace before it is returned. Unset -> the
    #: deterministic template explainer is used instead.
    groq_api_key: Optional[str] = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept either a JSON list or a comma separated string."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value  # let pydantic parse the JSON list
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_cors(cls, value: List[str]) -> List[str]:
        """Refuse ``*``.

        The browser would reject a wildcard combined with credentials anyway,
        and an explicit origin list is what keeps another site from driving the
        dashboard's session.
        """
        if any(origin.strip() == "*" for origin in value):
            raise ValueError(
                "CORS_ORIGINS must list the frontend origins explicitly; '*' is not allowed"
            )
        return value

    @model_validator(mode="after")
    def _require_api_key_outside_development(self) -> "Settings":
        """Fail closed: a non-development deployment must be authenticated."""
        if self.environment.lower() not in UNSECURED_ENVIRONMENTS and not self.api_key:
            raise ValueError(
                f"API_KEY must be set when ENVIRONMENT is {self.environment!r}; "
                "only development and test may run with writes unauthenticated"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
