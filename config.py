from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI 
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.4"
    LLM_TEMPERATURE: float = 0.1

    # MCP server
    MCP_SERVER_URL: str = "http://localhost:8000/mcp"
    MCP_TRANSPORT: str = "http"

    # Tool-use loop
    MAX_TOOL_TURNS: int = 8
    REQUEST_TIMEOUT_SECONDS: int = 120

    # Datawrapper
    DATAWRAPPER_API_KEY: str = ""

    # Django
    DJANGO_SECRET_KEY: str = "insecure-dev-secret-change-in-production"
    DJANGO_DEBUG: bool = True
    ALLOWED_HOSTS: str = "*"
    CORS_ALLOWED_ORIGINS: str = "*"
    CSRF_TRUSTED_ORIGINS: str = ""


settings = Settings()
