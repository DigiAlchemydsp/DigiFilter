"""Portable steps behind mise.toml; run the SDK and simulator without shell expansion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'vendor/elekloader'
EMU = ROOT / 'vendor/digiemu'
OUT = ROOT / 'out'
OS_VERSIONS = ('1.53', '1.54')


def run(args, *, cwd=ROOT, capture=False):
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True,
                            stdout=subprocess.PIPE if capture else None, text=True)
    return result.stdout.strip() if capture else None


def manifest(folder=ROOT):
    return json.loads((folder / 'mod.json').read_text(encoding='utf-8'))


def stock_os(stock):
    from elekloader import devices
    device, release = devices.identify(hashlib.sha256(stock.read_bytes()).hexdigest())
    if device.key != 'digitakt-mk1' or release.version not in OS_VERSIONS:
        raise ValueError('DigiFilter needs stock Digitakt mk1 OS 1.53 or 1.54')
    return release.version


def stocks():
    selected = os.environ.get('DIGIFILTER_BUILD_OS', '1.54')
    if selected != 'all' and selected not in OS_VERSIONS:
        raise ValueError('DIGIFILTER_BUILD_OS must be 1.53, 1.54 or all')
    versions = OS_VERSIONS if selected == 'all' else (selected,)
    result = []
    for version in versions:
        path = ROOT / 'firmware' / f'Digitakt_OS{version}.syx'
        if stock_os(path) != version:
            raise ValueError(f'{path} does not contain stock OS {version}')
        result.append(path)
    return result


def artifact(folder, version):
    mod = manifest(folder)
    suffix = '' if version == mod['os'] else f'-os{version}'
    return OUT / f'os{version}' / f"{mod['id']}-{mod['version']}{suffix}.elemod"


def build(stock):
    version = stock_os(stock)
    for folder in (SDK / 'mods/core', ROOT):
        run([sys.executable, '-m', 'elekloader.sdk.build', folder,
             '--stock', stock, '--out', OUT / f'os{version}'])
    return version


def patch_args(stock, version):
    return [sys.executable, '-m', 'elekloader.patch', '--stock', stock,
            '--mod', artifact(SDK / 'mods/core', version),
            '--mod', artifact(ROOT, version), '--out', firmware_path(version),
            '--version', os.environ.get('FW_VERSION', 'DFlt')]


def firmware_path(version):
    return OUT / f'os{version}' / 'Digitakt_custom.syx'


def emulator_python():
    python = EMU / ('.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python')
    if not python.is_file():
        raise ValueError('Simulator environment missing; run mise bootstrap first')
    return python


def bootstrap():
    run(['uv', 'sync', '--locked', '--python', sys.executable], cwd=EMU)
    python = emulator_python()
    probe = subprocess.run([str(python), '-m', 'emu.unicorn_compat'], cwd=EMU,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if probe.returncode:
        if sys.platform == 'win32':
            command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                       'tools/install-patched-unicorn.ps1']
        else:
            command = ['bash', 'tools/install-patched-unicorn.sh']
        # The upstream installers use PYTHON to select the environment to patch.
        os.environ['PYTHON'] = str(python)
        run(command, cwd=EMU)
    run([python, '-m', 'emu.unicorn_compat'], cwd=EMU)


def test_emu():
    stock = Path(os.environ.get('ELEKLOADER_STOCK', ROOT / 'firmware/Digitakt_OS1.54.syx')).resolve()
    version = stock_os(stock)
    run([emulator_python(), '-u', '-m', 'emu.fwcheck', firmware_path(version),
         '--baseline', stock, '--out', OUT / f'os{version}' / 'test-emu'], cwd=EMU)


def release():
    if run(['git', 'status', '--porcelain'], capture=True):
        raise ValueError("release: commit first, so the release is the source it's tagged on")
    run(['git', 'fetch', '-q', 'origin'])
    if run(['git', 'log', 'origin/master..HEAD'], capture=True):
        raise ValueError('release: push first')
    version = manifest()['version']
    head = run(['git', 'rev-parse', 'HEAD'], capture=True)
    run(['gh', 'release', 'create', f'v{version}', *(artifact(ROOT, v) for v in OS_VERSIONS),
         '--target', head, '--title', f'DigiFilter {version}', '--generate-notes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=('bootstrap', 'build', 'check', 'test:emu', 'bench', 'firmware',
                                        'emu', 'release'))
    task = parser.parse_args().task
    sys.path.insert(0, str(SDK))
    os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, (str(SDK), os.environ.get('PYTHONPATH'))))
    if task == 'bootstrap':
        bootstrap()
    elif task == 'build':
        for stock in stocks():
            build(stock)
    elif task == 'check':
        for stock in stocks():
            version = stock_os(stock)
            run([sys.executable, '-m', 'elekloader.lint', artifact(ROOT, version),
                 '--stock', stock, '--with', artifact(SDK / 'mods/core', version)])
            run([*patch_args(stock, version), '--check'])
    elif task == 'bench':
        run([emulator_python(), ROOT / 'tests/df_bench.py'], cwd=EMU)
    elif task == 'test:emu':
        test_emu()
    elif task == 'firmware':
        stock = Path(os.environ.get('ELEKLOADER_STOCK', ROOT / 'firmware/Digitakt_OS1.54.syx')).resolve()
        version = stock_os(stock)
        run(patch_args(stock, version))
    elif task == 'emu':
        stock = Path(os.environ.get('ELEKLOADER_STOCK', ROOT / 'firmware/Digitakt_OS1.54.syx')).resolve()
        firmware = firmware_path(stock_os(stock))
        python = emulator_python()
        run([python, '-m', 'emu.portable', '--add', firmware, '--yes'], cwd=EMU)
        folder = run([python, '-c', 'from emu.portable import plan_add; import sys; '
                      'print(plan_add(sys.argv[1]).fwdir)', firmware], cwd=EMU, capture=True)
        run([python, '-m', 'emu.portable', '--worker', 'panel', folder], cwd=EMU)
    elif task == 'release':
        release()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1)
