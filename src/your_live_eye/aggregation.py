"""Calendar aggregation extracted from Hinome monitor/history.py (2026-10-27)."""
import bisect
import calendar
import datetime as dt
TZ=dt.timezone(dt.timedelta(hours=8))
TOPICS=["实时翻译","打招呼","支持赞美","玩梗反应","闲聊交流","攻击","待判断","关心爱护"]
SENTIMENTS=["支持友善","中性表达","不满担忧","无法判断"]
N_TOPICS=8
N_VECTOR=24
def window_start(end, months):
    """Inclusive rolling calendar window, ending on a Shanghai natural day."""
    n = end.year * 12 + end.month - 1 - months
    year, month = n // 12, n % 12 + 1
    previous = dt.date(year, month, min(end.day, calendar.monthrange(year, month)[1]))
    return previous + dt.timedelta(days=1)

def day_of(ts):
    return dt.datetime.fromtimestamp(ts / 1000, TZ).date().isoformat()

def zeros():
    # Source kinds and legacy tones remain internal audit dimensions.
    return [0] * N_VECTOR

def totals(vector):
    result = {}
    n = N_TOPICS
    for k, topic, tone in [('Message', vector[:n], vector[2*n:2*n+4]), ('SC', vector[n:2*n], vector[2*n+4:2*n+8])]:
        result[k] = {'topic':topic, 'tone':tone, 'total':sum(topic)}
        assert sum(topic) == sum(tone)
    result['all'] = {'topic':[a+b for a,b in zip(vector[:n], vector[n:2*n])],
                     'tone':[a+b for a,b in zip(vector[2*n:2*n+4], vector[2*n+4:2*n+8])],
                     'total':sum(vector[:2*n])}
    return result

def empty_day():
    return {'vector':zeros(), 'minutes':{}, 'sessions':set(), 'images':0, 'interrupts':0, 'first_ts':None, 'last_ts':None, 'live_ranges':{}}

def calendar_index(days, first, last):
    keys = []
    cursor = first
    while cursor <= last:
        keys.append(cursor.isoformat()); cursor += dt.timedelta(days=1)
    prefix = [zeros()]; observed = [0]
    for day in keys:
        vector = days.get(day, {}).get('vector', zeros())
        prefix.append([a+b for a,b in zip(prefix[-1], vector)])
        observed.append(observed[-1] + int(sum(vector[:2*N_TOPICS]) > 0))
    calendar_days = {}
    for i, day in enumerate(keys):
        end = dt.date.fromisoformat(day); windows = {}
        for name, months in [('month',1),('year',12),('decade',120)]:
            start = window_start(end, months); left = bisect.bisect_left(keys, start.isoformat())
            vector = [a-b for a,b in zip(prefix[i+1], prefix[left])]
            windows[name] = {'start':start.isoformat(),'end':day,'days':(end-start).days+1,
                             'observed_days':observed[i+1]-observed[left], 'series':totals(vector)}
        data = days.get(day, empty_day())
        calendar_days[day] = {'series':totals(data['vector']), 'observed':sum(data['vector'][:2*N_TOPICS]) > 0,
                              'interrupts':data['interrupts'],'windows':windows}
    return calendar_days
