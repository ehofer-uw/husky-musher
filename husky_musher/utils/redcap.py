import functools
import json
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests
from id3c.cli.redcap import Project, is_complete
from injector import Module, inject, provider, singleton
from prometheus_client import Summary
from prometheus_client.registry import CollectorRegistry
from werkzeug.exceptions import BadRequest

from husky_musher.settings import AppSettings
from husky_musher.utils.cache import Cache


class REDCapValue(Enum):
    YES = "1"
    COMPLETE = "2"
    KIOSK_WALK_IN = "4"   # TODO: Not needed?


class REDCapRequestSecondsSummary(Summary):
    pass


class FetchParticipantMetric(REDCapRequestSecondsSummary):
    pass


class RedcapInjectorModule(Module):
    @provider
    @singleton
    def provide_metric_summary(self, registry: CollectorRegistry) -> REDCapRequestSecondsSummary:
        return REDCapRequestSecondsSummary(
            "redcap_request_seconds",
            documentation="Time spent making requests to REDCap",
            labelnames=['function'],
            registry=registry,
        )

    @provider
    @singleton
    def provide_redcap_project(self, settings: AppSettings) -> Project:
        return Project(settings.redcap_api_url, settings.redcap_project_id, token=settings.redcap_api_token)

    @provider
    @singleton
    def provide_prometheus_registry(self) -> CollectorRegistry:
        return CollectorRegistry()

    @provider
    @singleton
    def provide_fetch_participant_metric(
        self, summary: REDCapRequestSecondsSummary
    ) -> FetchParticipantMetric:
        return summary.labels("fetch_participant")


def time_redcap_request(label: Optional[str] = None):
    def decorator(method):
        @functools.wraps(method)
        def inner(*args, **kwargs):
            instance: REDCapClient = args[0]
            with instance.metric_summary.labels(label or method.__name__).time():
                return method(*args, **kwargs)

        return inner

    return decorator


@singleton
class REDCapClient:
    @inject
    def __init__(
        self,
        metric_summary: REDCapRequestSecondsSummary,
        cache: Cache,
        project: Project,
        settings: AppSettings,
        fetch_participant_metric: FetchParticipantMetric,
    ):
        self.fetch_participant_metric = metric_summary.labels("fetch_participant")
        self.cache = cache
        self.project = project
        self.settings = settings
        self.fetch_participant_metric = fetch_participant_metric
        self.metric_summary = metric_summary

    @time_redcap_request("fetch_participant (cached)")
    def fetch_participant(self, user_info: Dict) -> Optional[Dict[str, str]]:
        """
        Exports a REDCap record matching the given *user_info*. Returns None if no
        match is found.

        Raises an :class:`AssertionError` if REDCap returns multiple matches for the
        given *user_info*.
        """
        uw_netid = user_info["uw_netid"]
        record = self.cache.get(uw_netid, load_json=True)

        if not record:
            with self.fetch_participant_metric.time():
                fields = [
                    "uw_netid",
                    "record_id",
                    "enrollment_questions_complete",
#                    "eligibility_screening_complete",
#                    "consent_form_complete",
#                    "enrollment_questionnaire_complete",
                ]

                data = {
                    "token": self.project.api_token,
                    "content": "record",
                    "format": "json",
                    "type": "flat",
                    "csvDelimiter": "",
                    "filterLogic": f'[uw_netid] = "{uw_netid}"',
                    "fields": ",".join(map(str, fields)),
                    "rawOrLabel": "raw",
                    "rawOrLabelHeaders": "raw",
                    "exportCheckboxLabel": "false",
                    "exportSurveyFields": "false",
                    "exportDataAccessGroups": "false",
                    "returnFormat": "json",
                }

                response = requests.post(self.project.api_url, data=data)
                response.raise_for_status()

                records = response.json()

                if not records:
                    return None

                if len(records) > 1:
                    raise BadRequest(
                        f'Multiple records exist with NetID "{uw_netid}": '
                        f'{[r["record_id"] for r in records]}'
                    )

                record = records[0]

            if self.redcap_registration_complete(record):
                self.cache.set(uw_netid, record)

        return record

    @time_redcap_request()
    def register_participant(self, user_info: dict) -> str:
        """
        Returns the REDCap record ID of the participant newly registered with the
        given *user_info*
        """
        # REDCap enforces that we must provide a non-empty record ID. Because we're
        # using `forceAutoNumber` in the POST request, we do not need to provide a
        # real record ID.
        records = [{**user_info, "record_id": "record ID cannot be blank"}]
        data = {
            "token": self.project.api_token,
            "content": "record",
            "format": "json",
            "type": "flat",
            "overwriteBehavior": "normal",
            "forceAutoNumber": "true",
            "data": json.dumps(records),
            "returnContent": "ids",
            "returnFormat": "json",
        }
        response = requests.post(self.project.api_url, data=data)
        response.raise_for_status()
        return response.json()[0]

    @time_redcap_request()
    def generate_survey_link(
        self, record_id: str, event: str, instrument: str, instance: int = None
    ) -> str:
        """
        Returns a generated survey link for the given *instrument* within the
        *event* of the *record_id*.

        Will include the repeat *instance* if provided.
        """
        data = {
            "token": self.project.api_token,
            "content": "surveyLink",
            "format": "json",
            "instrument": instrument,
            "event": event,
            "record": record_id,
            "returnFormat": "json",
        }

        if instance:
            data["repeat_instance"] = str(instance)

        response = requests.post(self.project.api_url, data=data)
        response.raise_for_status()
        return response.text


    def get_the_current_week(self) -> int:
        """
        Returns the current program week to redirect the user to the correct first weekly event
        with the first week starting at 1
        """
        return 1 + (datetime.today() - self.settings.redcap_study_start_date).days // 7

    def redcap_registration_complete(self, redcap_record: dict) -> bool:
        """
        Returns True if a given *redcap_record* shows a participant has completed
        the enrollment surveys. Otherwise, returns False.

        >>> self.redcap_registration_complete(None)
        False

        >>> self.redcap_registration_complete({})
        False

        >>> self.redcap_registration_complete({ \
            'eligibility_screening_complete': '1', \
            'consent_form_complete': '2', \
            'enrollment_questionnaire_complete': '0'})
        False

        >>> self.redcap_registration_complete({ \
            'eligibility_screening_complete': '2', \
            'consent_form_complete': '2', \
            'enrollment_questionnaire_complete': '1'})
        False

        >>> self.redcap_registration_complete({ \
            'eligibility_screening_complete': '2', \
            'consent_form_complete': '2', \
            'enrollment_questionnaire_complete': '2'})
        True
        """
        if not redcap_record:
            return False

        return (
            is_complete("enrollment_questions", redcap_record)
#            is_complete("eligibility_screening", redcap_record)
#            and is_complete("consent_form", redcap_record)
#            and is_complete("enrollment_questionnaire", redcap_record)
        )
