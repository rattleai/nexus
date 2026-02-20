from cadprice.workers.celery_app import celery


@celery.task(name="cadprice.workers.ping")
def ping() -> str:
    return "pong"
