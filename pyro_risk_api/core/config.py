from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "pyro-risk-api"
    version: str = "0.1.0"

    api_username: str = ""
    api_password: str = ""

    pyro_api_host: str = "https://alertapi.pyronear.org/"
    pyro_api_username: str = ""
    pyro_api_password: str = ""

    cameras_refresh_cron_hour: int = 2
    cameras_refresh_cron_minute: int = 0
    cameras_refresh_timezone: str = "UTC"

    database_url: str = "sqlite:///./data/pyro_risk.db"


settings = Settings()
