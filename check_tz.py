import sys
import datetime
import pytz

reset_date_str = "2026-01-31"
reset_date = datetime.datetime.strptime(reset_date_str, "%Y-%m-%d").date()

naive_dt = datetime.datetime.combine(reset_date, datetime.time.max)
user_tz_name = 'Asia/Bangkok'
user_tz = pytz.timezone(user_tz_name)
local_dt = user_tz.localize(naive_dt)
utc_dt = local_dt.astimezone(pytz.utc)
reset_dt = utc_dt.replace(tzinfo=None)

print(f"naive_dt: {naive_dt}")
print(f"local_dt: {local_dt}")
print(f"utc_dt: {utc_dt}")
print(f"reset_dt: {reset_dt}")
