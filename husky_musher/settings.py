import os
from datetime import datetime

from injector import singleton


@singleton
class AppSettings:
    app_name = os.environ.get('APP_NAME', 'husky_musher')
    flask_env = os.environ.get('FLASK_ENV')
    version = os.environ.get('APP_VERSION')
    deployment_id = os.environ.get('DEPLOYMENT_ID')
    use_mock_idp = bool(os.environ.get('USE_MOCK_IDP'))
    redcap_api_url = os.environ.get("REDCAP_API_URL")
    redcap_api_token = os.environ.get("REDCAP_API_TOKEN")
    redcap_project_id = os.environ.get('REDCAP_PROJECT_ID')
    redcap_event_id = os.environ.get('REDCAP_EVENT_ID')
    redcap_study_start_date = datetime.strptime(
        os.environ.get('REDCAP_STUDY_START_DATE', '1970-01-01'),
        '%Y-%m-%d'
    )
    saml_acs_path = os.environ.get('SAML_ACS_PATH')
    saml_entity_id = os.environ.get('SAML_ENTITY_ID')

    # If redis_host is defined, it will be used. Otherwise,
    # a mock redis client will be created.
    redis_host = os.environ.get('REDIS_HOST')
    redis_port = os.environ.get('REDIS_PORT', 6379)
    redis_password = os.environ.get('REDIS_PASSWORD')

    @property
    def in_development(self):
        return self.flask_env == 'development'
