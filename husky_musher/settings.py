import os
from datetime import datetime

from injector import singleton


@singleton
class AppSettings:
    flask_env = os.environ.get('FLASK_ENV')
    cache = os.environ.get("CACHE")
    version = os.environ.get('APP_VERSION')
    deployment_id = os.environ.get('DEPLOYMENT_ID')
    redcap_api_url = os.environ.get("REDCAP_API_URL")
    redcap_api_token = os.environ.get("REDCAP_API_TOKEN")
    redcap_project_id = os.environ.get('REDCAP_PROJECT_ID')
    redcap_event_id = os.environ.get('REDCAP_EVENT_ID')
    redcap_study_start_date = datetime.strptime(
        os.environ.get('REDCAP_STUDY_START_DATE', '1970-01-01'),
        '%Y-%m-%d'
    )

    @property
    def in_development(self):
        return self.flask_env == 'development'
