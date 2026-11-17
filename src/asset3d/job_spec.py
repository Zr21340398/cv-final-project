"""应用和实验共用的任务描述；只依赖标准库，供网页服务与计算节点共同校验。"""
import re

def validate(spec):
    if not isinstance(spec, dict) or set(spec) != {'name', 'seeds', 'variants', 'images'}:
        raise ValueError('配置必须包含 name、seeds、variants、images')
    safe = lambda x: isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', x)
    if not safe(spec['name']):
        raise ValueError('实验名请使用字母、数字、下划线或短横线')
    seeds = spec['seeds']
    if not isinstance(seeds, list) or not seeds or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('seeds 必须为不同的非负整数')
    images = spec['images']
    if not isinstance(images, list) or not images or any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.(png|jpg|jpeg)', s, re.I) for s in images) or len(set(images)) != len(images):
        raise ValueError('images 请填写不同的 JPG/PNG 文件名，仅支持英文、数字、点、短横线、下划线')
    variants = spec['variants']
    if not isinstance(variants, list) or not variants:
        raise ValueError('至少需要一个方案')
    names = set()
    for v in variants:
        if not isinstance(v, dict) or set(v) - {'name','decimation_target','texture_size'} or not safe(v.get('name')) or v['name'] in names:
            raise ValueError('方案需要唯一 name，可选 decimation_target 和 texture_size')
        names.add(v['name'])
        if type(v.get('decimation_target',1000000)) is not int or not 1000 <= v.get('decimation_target',1000000) <= 1000000:
            raise ValueError('decimation_target 范围为 1000 至 1000000')
        if v.get('texture_size',2048) not in (1024,2048,4096):
            raise ValueError('texture_size 可选 1024、2048、4096')
    count = len(images)*len(seeds)*len(variants)
    if count > 200:
        raise ValueError('单批次最多 200 次生成，请拆分实验')
    return count
