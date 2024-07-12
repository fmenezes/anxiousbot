from pythonjsonlogger import jsonlogger

class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, extra = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._extra = extra

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["levelname"] = record.levelname
        if self._extra is not None:
            for key, value in self._extra.items():
                log_record[key] = value
        

def get_logger(extra=None):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = CustomJsonFormatter(timestamp=True, extra=extra)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger