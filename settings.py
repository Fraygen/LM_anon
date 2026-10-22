from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str
    REDIS_URL: str
    TIMEZONE: str = "Europe/Moscow"
    ADMIN_IDS: str

    @property
    def admin_id_list(self) -> list[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


config = Settings()