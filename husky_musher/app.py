import logging
import os
from typing import cast

from flask import Flask, render_template
from flask_injector import FlaskInjector
from flask_session import RedisSessionInterface, Session
from injector import Injector
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics
from redis import Redis

from husky_musher.blueprints.app import AppBlueprint
from husky_musher.blueprints.saml import MockSAMLBlueprint, SAMLBlueprint
from husky_musher.utils.cache import MockRedis
from husky_musher.utils.redcap import *

if os.environ.get("GUNICORN_LOG_LEVEL", None):
    MetricsClientCls = GunicornInternalPrometheusMetrics
else:
    MetricsClientCls = PrometheusMetrics


class InvalidNetId(BadRequest):
    detail = "Invalid NetID"
    code = 400


def configure_metrics(app_injector: FlaskInjector, settings: AppSettings):
    app = app_injector.app
    injector_ = app_injector.injector
    cls = PrometheusMetrics
    if os.environ.get('GUNICORN_LOG_LEVEL'):  # If gunicorn is configured and in use
        cls = GunicornInternalPrometheusMetrics
    metrics = cls(
        app,
        defaults_prefix=f"{settings.app_name}_flask",
    )
    app.metrics = metrics
    injector_.binder.bind(PrometheusMetrics, metrics, scope=singleton)
    return metrics


def configure_session_cache(app: Flask, cache: Cache, settings: AppSettings):
    if settings.redis_host:
        app.session_interface = RedisSessionInterface(
            redis=cache.redis,
            key_prefix=f'{cache.prefix}sessions.'
        )
    else:
        Session(app)


def register_error_handlers(app: Flask):
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
        return render_template("invalid_netid.html", netid=netid), InvalidNetId.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error(f"Unexpected error occurred: {error}", exc_info=error)
        return render_template("something_went_wrong.html"), 500


class AppInjectorModule(Module):
    @provider
    @singleton
    def provide_redis(self, settings: AppSettings) -> Redis:
        if settings.redis_host:
            return Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                username=settings.app_name,
                password=settings.redis_password,
            )
        return cast(Redis, MockRedis())

    @provider
    @singleton
    def provide_app(
        self,
        injector_: Injector,
        app_blueprint: AppBlueprint,
    ) -> Flask:
        app = Flask(__name__)
        logging_config_file = os.path.join(os.getcwd(), "logging.yaml")
        settings = injector_.get(AppSettings)

        with open(logging_config_file, "rb") as file:
            from id3c.logging import load_config
            logging.config.dictConfig(load_config(file))

        logger = logging.getLogger('gunicorn.error').getChild('app')
        injector_.binder.bind(
            logging.Logger, logger, singleton
        )
        blueprint_cls = MockSAMLBlueprint if settings.use_mock_idp else SAMLBlueprint
        app.register_blueprint(injector_.get(blueprint_cls))
        app.register_blueprint(app_blueprint)
        flask_injector = FlaskInjector(app, injector=injector_)

        metrics = configure_metrics(flask_injector, settings)

        configure_session_cache(app, injector_.get(Cache), settings)

        # Setup Prometheus metrics collector.

        register_error_handlers(app)
        return app


def create_app_injector() -> Injector:
    modules = [
        AppInjectorModule,
        RedcapInjectorModule
    ]
    return Injector(modules)


def create_app(injector_: Optional[Injector] = None):
    if not injector_:
        injector_ = create_app_injector()
    return injector_.get(Flask)


if __name__ == "__main__":
    create_app().run()
