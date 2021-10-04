import os
from datetime import datetime

from injector import singleton


@singleton
class AppSettings:
    env = os.environ.get("FLASK_ENV", "production")
    redcap_api_url = os.environ.get("REDCAP_API_URL")
    cache = os.environ.get("CACHE")
    version = os.environ.get('HUSKY_MUSHER_APP_VERSION', '0.0.1')

    @property
    def in_development(self) -> bool:
        return self.env == "development"

    @property
    def project_id(self) -> int:
        if self.in_development:
            return 24515
        return 45

    @property
    def event_id(self) -> int:
        if self.in_development:
            return 743558
        return 129

    @property
    def study_start_date(self) -> datetime:
        if self.in_development:
            return datetime(2020, 9, 24)
        return datetime(2021, 9, 9)
