from datetime import date


def month_start(d: date) -> date:
    return d.replace(day=1)
