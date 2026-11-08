"""Build source plugin and native desktop archives; never publish automatically."""
import argparse
import json
from pathlib import Path
import platform
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(native=None):
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    metadata = json.loads((ROOT / 'plugin.json').read_text())
    version = metadata['version']
    files = ['server.py', 'pyproject.toml', 'README.md', 'LICENSE', 'plugin.json',
             'mcp.json', '.mcp.json', '.claude-plugin/plugin.json']
    source = output / f'siat-mcp-{version}-source-plugin.zip'
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(ROOT / name, name)
        for path in (ROOT / 'docs').glob('*.md'):
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(source)
    if native is None:
        return
    native = Path(native).resolve()
    system = {'Windows': 'win32', 'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
    exe = 'siat-mcp.exe' if system == 'win32' else 'siat-mcp'
    if not (native / exe).is_file():
        raise ValueError(f'Missing executable: {native / exe}')
    suffix = f'{system}-{platform.machine().lower()}'
    manifest = {
        'manifest_version': '0.3', 'name': metadata['name'], 'version': version,
        'display_name': 'Uzbekistan Statistics', 'description': metadata['description'],
        'author': metadata['author'], 'license': metadata['license'],
        'homepage': metadata['homepage'], 'support': metadata['homepage'] + '/issues',
        'server': {'type': 'binary', 'entry_point': 'server/' + exe,
                   'mcp_config': {'command': '${__dirname}/server/' + exe, 'args': []}},
        'compatibility': {'platforms': [system]}, 'tools_generated': True,
    }
    def write_json(archive, name, obj):
        archive.writestr(name, json.dumps(obj, indent=2) + '\n')
    for kind in ('mcpb', 'desktop-plugin.zip'):
        path = output / f'siat-mcp-{version}-{suffix}.{kind}'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(ROOT / 'LICENSE', 'LICENSE')
            if kind == 'mcpb':
                write_json(archive, 'manifest.json', manifest)
            else:
                write_json(archive, 'plugin.json', metadata)
                write_json(archive, 'mcp.json', {
                    '$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
                    'mcpServers': {'siat-stat-uz': {'type': 'stdio',
                        'command': '${PLUGIN_ROOT}/server/' + exe, 'args': []}}})
                claude = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
                write_json(archive, '.claude-plugin/plugin.json', claude)
                write_json(archive, '.mcp.json', {'mcpServers': {'siat-stat-uz': {
                    'command': '${CLAUDE_PLUGIN_ROOT}/server/' + exe, 'args': []}}})
            for item in sorted(native.rglob('*')):
                if item.is_symlink():
                    raise ValueError(f'Symlink requires explicit packaging support: {item}')
                if item.is_file():
                    archive.write(item, 'server/' + item.relative_to(native).as_posix())
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert 'server/' + exe in archive.namelist()
        print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, help='PyInstaller onedir output for this OS/architecture')
    build(parser.parse_args().native)
