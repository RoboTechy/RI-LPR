import jdatetime


def to_jalali_str(dt):
    """Format a timezone-aware UTC datetime as a Jalali date/time string
    for display in the admin panel (e.g. "1405/08/11 14:32:07")."""
    if dt is None:
        return ""
    local = dt.astimezone()  # convert to the server's local timezone first
    j = jdatetime.datetime.fromgregorian(datetime=local)
    return j.strftime("%Y/%m/%d %H:%M:%S")
