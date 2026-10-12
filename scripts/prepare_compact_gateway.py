"""Small additive D1 migration, usable in CI and with local Wrangler OAuth."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bolsa_abierta.operations import prepare_compact_gateway

def main():
    # Windows callers may give the official CLI JS entrypoint to preserve SQL
    # arguments exactly; never read or copy the CLI's credential storage.
    entry = os.environ.get('WRANGLER_ENTRYPOINT')
    cli = [shutil.which('node'), entry] if entry else [shutil.which('npx'), 'wrangler']
    def execute(sql):
        result = subprocess.run([*cli, 'd1', 'execute', 'bolsa-abierta-gateway', '--remote',
            '--config', 'gateway/wrangler.toml', '--command=' + sql, '--json'],
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('D1 schema operation failed')
        report = json.loads(result.stdout)
        if not isinstance(report, list) or any(item.get('success') is False for item in report):
            raise RuntimeError('D1 schema operation failed')
        return report
    execute(Path('gateway/migrations/budget-bootstrap.sql').read_text())
    core = '\n'.join([Path('gateway/schema.sql').read_text(),
        Path('gateway/positions.sql').read_text().split('-- Indexed exact')[0],
        Path('gateway/migrations/0002-position-blocks.sql').read_text()])
    result = prepare_compact_gateway(execute, core, f'ddl:{int(time.time())}:1')
    print(json.dumps(result))
    if result['status'] != 'ready':
        raise SystemExit('Compact schema is not ready; existing deployment retained')

if __name__ == '__main__':
    main()
