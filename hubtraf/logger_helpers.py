import copy
import logging
import os
import sys

import colorama

from jupyter_telemetry import EventLog


class ColoramaHandler(logging.StreamHandler):
    def emit(self, record):
        status = record.msg["status"]
        event_kind = record.msg["action"]
        username = record.msg["username"]

        if status == "Success":
            color = colorama.Fore.GREEN
        elif status == "Failure":
            color = colorama.Fore.RED
        else:
            color = colorama.Fore.YELLOW

        events = []
        for k, v in record.msg.items():
            if not "__" in k and k != "status" and k != "action" and k != "username":
                events.append(f"{k}:{v}")
        events = " ".join(events)
        self.stream.write(
            f"{color}{status}:{colorama.Style.RESET_ALL} {event_kind} {username} {events}\n"
        )


def init_telemetry_schemas(event_logger, schemas_location, allowed_schemas):
    for dirname, _, files in os.walk(schemas_location):
        for file in files:
            if not file.endswith(".yaml"):
                continue
            event_logger.register_schema_file(os.path.join(dirname, file))
    event_logger.allowed_schemas = allowed_schemas


def get_logger(json):
    if json:
        logger = EventLog(handlers=[logging.StreamHandler(sys.stdout)])
    else:
        logger = EventLog(handlers=[ColoramaHandler(sys.stdout)])

    schemas = os.path.join(os.path.dirname(__file__), "event-schemas")
    allowed_schemas = ["hubtraf.jupyter.org/event"]
    init_telemetry_schemas(logger, schemas, allowed_schemas)

    return logger
