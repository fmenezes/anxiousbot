import asyncio
import logging
import os
import traceback

from watchtower import CloudWatchLogFormatter, CloudWatchLogHandler


class CustomFormatter(CloudWatchLogFormatter):
    def format(self, message):
        for attr in self.add_log_record_attrs:
            if not hasattr(message, attr):
                setattr(message, attr, None)
        return super().format(message)


def _get_log_handler(extra=None):
    attrs = [
        "name",
        "levelname",
        "taskName",
        "exchange",
        "duration",
        "symbol",
        "pathname",
        "lineno",
        "exc_formatted",
    ]
    if extra is not None:
        attrs += extra.keys()
    formatter = CustomFormatter(add_log_record_attrs=attrs)
    if os.getenv("LOG_HANDLER", "STDOUT") == "CLOUD_WATCH":
        handler = CloudWatchLogHandler(
            boto3_client=boto3.client("logs", region_name=os.getenv("AWS_REGION")),
            send_interval=5,
            log_group=os.getenv("LOG_GROUP_NAME"),
            stream_name=os.getenv("LOG_STREAM_NAME"),
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    return handler


def _log_record_factory(log_factory=None, extra=None):
    if log_factory is None:
        log_factory = logging.getLogRecordFactory()

    def _factory(*args, **kwargs):
        record = log_factory(*args, **kwargs)

        if isinstance(record.exc_info, BaseException):
            try:
                record.exc_formatted = "".join(
                    traceback.format_exception(record.exc_info)
                )
            except:
                pass
        if isinstance(record.exc_info, tuple):
            try:
                record.exc_formatted = "".join(
                    traceback.format_exception(record.exc_info[1])
                )
            except:
                pass

        try:
            record.taskName = asyncio.current_task().get_name()
        except Exception:
            record.taskName = None
        if extra is not None:
            for key, value in extra.items():
                setattr(record, key, value)
        return record

    return _factory


def get_logger(name=None, extra=None):
    logging.setLogRecordFactory(_log_record_factory(extra=extra))
    logger = logging.getLogger(name)
    try:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))
    except:
        level = logging.INFO
    logger.setLevel(level)
    handler = _get_log_handler(extra)
    logger.addHandler(handler)
    return logger
