from app.workers.celery_app import celery


@celery.task(name="app.workers.ping")
def ping() -> str:
    return "pong"
