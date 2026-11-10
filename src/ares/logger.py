"""Independent step snapshots with portable JSON-valued CSV columns."""
import copy
import csv
import io
import json
import math
from pathlib import Path


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    return value


class MissionLogger:
    def __init__(self):
        self.trace = []

    def record(self, **record):
        snapshot = clean(copy.deepcopy(record))
        self.trace.append(snapshot)
        return copy.deepcopy(snapshot)

    def export_csv(self, path=None):
        output = io.StringIO(newline='')
        fields = list(dict.fromkeys(key for row in self.trace for key in row))
        writer = csv.DictWriter(output, fieldnames=fields)
        if fields:
            writer.writeheader()
            for row in self.trace:
                writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (list, dict)) else v for k, v in row.items()})
        result = output.getvalue()
        if path is not None:
            Path(path).write_text(result, encoding='utf-8')
        return result
