from pathlib import Path

import prometheus_flask_exporter
from flask import Flask, Request, jsonify, redirect, render_template
from flask_injector import FlaskInjector
from injector import Injector
from prometheus_flask_exporter.multiprocess import MultiprocessPrometheusMetrics
from werkzeug.exceptions import InternalServerError

from husky_musher import configure_logger
from husky_musher.utils.redcap import *
from husky_musher.utils.shibboleth import *


def create_app():
    app = Flask(__name__)
    injector = Injector(modules=[RedcapInjectorModule])
    FlaskInjector(app, injector=injector)
    logging_config_file = os.path.join(os.environ.get('PWD'), "logging.yaml")
    configure_logger(logging_config_file)

    # Setup Prometheus metrics collector.
    if "prometheus_multiproc_dir" in os.environ:
        metrics = MultiprocessPrometheusMetrics(
            app,
            defaults_prefix=prometheus_flask_exporter.NO_PREFIX,
            default_latency_as_histogram=False,
            excluded_paths=["^/static/"],
        )

        metrics.register_endpoint("/metrics")

    class InvalidNetId(BadRequest):
        detail = "Invalid NetID"
        code = 400

    # Always include a Cache-Control: no-store header in the response so browsers
    # or intervening caches don't save pages across auth'd users.  Unlikely, but
    # possible.  This is also appropriate so that users always get a fresh REDCap
    # lookup.
    @app.after_request
    def set_cache_control(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("page_not_found.html"), 404

    @app.errorhandler(InvalidNetId)
    def handle_bad_request(error):
        netid = error.description
        error.description = "[redacted]"
        app.logger.error(f"Invalid NetID", exc_info=error)
        return render_template("invalid_netid.html", netid=netid), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error(f"Unexpected error occurred: {error}", exc_info=error)
        return render_template("something_went_wrong.html"), 500

    @app.route('/status')
    def status(settings: AppSettings):
        return jsonify(
            {'version': settings.version}
        )

    @app.route("/")
    def main(request: Request, client: REDCapClient, settings: AppSettings):
        # Get NetID and other attributes from Shibboleth data
        if settings.in_development:
            remote_user = os.environ.get("REMOTE_USER")
            user_info = extract_user_info(dict(os.environ))
        else:
            remote_user = request.remote_user
            user_info = extract_user_info(request.environ)

        if not (remote_user and user_info.get("netid")):
            raise InternalServerError("No remote user!")

        redcap_record = client.fetch_participant(user_info)

        if not redcap_record:
            # If not in REDCap project, create new record
            new_record_id = client.register_participant(user_info)
            redcap_record = {"record_id": new_record_id}

        # Because of REDCap's survey queue logic, we can point a participant to an
        # upstream survey. If they've completed it, REDCap will automatically direct
        # them to the next, uncompleted survey in the queue.
        event = "enrollment_arm_1"
        instrument = "eligibility_screening"
        repeat_instance = None

        # If all enrollment event instruments are complete, point participants
        # to today's daily attestation instrument.
        # If the participant has already completed the daily attestation,
        # REDCap will prevent the participant from filling out the survey again.
        if client.redcap_registration_complete(redcap_record):
            event = "encounter_arm_1"
            instrument = "daily_attestation"
            repeat_instance = client.get_todays_repeat_instance()

            if repeat_instance <= 0:
                # This should never happen!
                raise InternalServerError("Failed to create a valid repeat instance")

        # Generate a link to the appropriate questionnaire, and then redirect.
        survey_link = client.generate_survey_link(
            redcap_record["record_id"], event, instrument, repeat_instance
        )
        return redirect(survey_link)
