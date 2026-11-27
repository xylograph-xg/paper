"""Resolve the weights behind an Ollama tag before using generated caches."""
import json
import urllib.request


def resolve_identity(model):
    with urllib.request.urlopen(model['base_url'].rstrip('/')+'/api/tags',timeout=8) as response:
        rows=json.load(response).get('models',[])
    name=model['name'];aliases={name,name+':latest'}
    matches=[row for row in rows if row.get('name') in aliases or row.get('model') in aliases]
    digests={row.get('digest') for row in matches if row.get('digest')}
    if len(digests)!=1:raise ValueError('无法唯一确认本地模型权重 digest；禁止复用旧生成缓存')
    return digests.pop()
