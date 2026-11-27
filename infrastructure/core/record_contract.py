"""Normalize provider records once; malformed items retain an explicit error."""
def text(value, field):
    if value is None:return ''
    if isinstance(value,str):return value.strip()
    if isinstance(value,list) and all(isinstance(x,str) for x in value):return ' '.join(value).strip()
    raise ValueError('书目字段形状不合法：'+field)


def normalize(record):
    if not isinstance(record,dict):raise ValueError('书目记录必须是对象')
    row=dict(record)
    for key in ('title','abstract','doi','venue','url'):
        if key in row:row[key]=text(row[key],key)
    if not row.get('title'):raise ValueError('书目缺少标题')
    for key in ('channels','source','pdf_urls','discovery_reasons','authors','discovered_from_seed_dois'):
        value=row.get(key,[])
        if value is None:value=[]
        if isinstance(value,str):value=[value]
        if not isinstance(value,list) or any(not isinstance(x,str) for x in value):raise ValueError('书目列表形状不合法：'+key)
        row[key]=list(dict.fromkeys(x.strip() for x in value if x.strip()))
    year=row.get('year')
    if year is not None and (type(year) is not int or not 1000<=year<=2200):raise ValueError('书目年份不合法')
    return row
