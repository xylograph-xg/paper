"""Check physical ownership and public import boundaries without running jobs."""
import argparse
import ast
import json
from core.api import paths__WorkspacePath as Path
import sys

ROOT = __import__('core.api',fromlist=['paths__workspace_root']).paths__workspace_root()
EXCLUDED = {'tests', 'vendor', 'all', 'data', 'workspace', 'build', '__pycache__', '.venv', 'dependencies', 'environments'}


def sources(folder):
    workspace=json.loads((ROOT/'workspace.json').read_text())
    nested=[ROOT/p['path'] for p in workspace['projects'].values() if ROOT/p['path']!=folder and (ROOT/p['path']).is_relative_to(folder)]
    for path in folder.rglob('*.py'):
        if any(path.is_relative_to(child) for child in nested):continue
        if path.is_symlink() or any(part in EXCLUDED or part.startswith('.')
                                   for part in path.relative_to(folder).parts[:-1]):
            continue
        yield path


def check(root=ROOT):
    root = Path(root).resolve()
    workspace = json.loads((root / 'workspace.json').read_text())
    projects = set(workspace['projects'])
    errors = []
    exports = 0
    source_count = 0
    for project in sorted(projects):
        folder = root / workspace['projects'][project].get('path',project)
        if not folder.is_dir() or folder.is_symlink():
            errors.append('子项目不是独立真实目录：' + project)
            continue
        for name in ('README.md', 'interface.json', 'api.py', 'pyproject.toml'):
            if not (folder / name).is_file() or (folder / name).is_symlink():
                errors.append('子项目接口文件缺失：' + project + '/' + name)
        interface = json.loads((folder / 'interface.json').read_text())
        if interface['project'] != project:
            errors.append('接口归属错误：' + project)
        exports += len(interface.get('python_exports', {}))
        for alias in folder.rglob('*'):
            relative = alias.relative_to(folder)
            if any(part in EXCLUDED or part.startswith('.') for part in relative.parts):
                continue
            if alias.is_symlink():
                errors.append('源码或说明仍有跨目录链接：' + str(alias.relative_to(root)))
        for path in sources(folder):
            source_count += 1
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError as exc:
                errors.append(str(exc))
                continue
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or '']
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                for name in names:
                    owner = name.split('.')[0]
                    if owner == 'pipeline':
                        errors.append('新源码依赖旧适配项目：' + str(path.relative_to(root)))
                    if owner in projects and owner != project:
                        allowed = name == owner + '.api' or name.startswith(owner + '.api.')
                        if owner == 'codex_desktop_chat' and name == owner:
                            allowed = True  # Existing registered public __all__ interface.
                        if not allowed:
                            errors.append('绕过公开接口：' + str(path.relative_to(root)) + ' -> ' + name)
                        if owner not in interface.get('dependencies', []):
                            errors.append('未声明依赖：' + project + ' -> ' + owner)
        for target in interface.get('python_exports', {}).values():
            module = target.partition(':')[0]
            path = root.joinpath(*module.split('.')).with_suffix('.py')
            if not path.is_file():
                package = root.joinpath(*module.split('.')) / '__init__.py'
                if not package.is_file():
                    errors.append('接口实现缺失：' + project + ' -> ' + target)
    for retired in workspace['removed_roots']:
        if (root / retired).exists():
            errors.append('过期结构仍存在：' + retired)
    for name in workspace['support_roots']:
        if not (root / name / 'README.md').is_file():
            errors.append('支持项目说明缺失：' + name)
    return {'passed': not errors, 'projects': len(projects),
            'production_source_files': source_count, 'public_exports': exports,
            'errors': sorted(set(errors))}


def main():
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
