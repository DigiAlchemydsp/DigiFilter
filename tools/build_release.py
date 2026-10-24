#!/usr/bin/env python3
"""Build DigiFilter 1.2 for the two latest-OS targets (Digitakt 1.54, Digitone 1.44).

Builds one elemod per machine, lints each against its core, patch-checks the
stock image, stages the elemods under releases/elemods/ and writes the release
zip. It does not distribute firmware: the written .syx files are local test
builds made from the user's own stock files.

    python tools/build_release.py \
        --elekloader <elekloader checkout> \
        --stock-dt <Digitakt_OS1.54.syx> \
        --stock-dn <Digitone_OS1.44.syx>

The matching cores are found next to the elekloader checkout by default:
core-4.0-os1.54.elemod and core-dn1-4.0-os1.44.elemod. Override with
--core-dt/--core-dn. Set --toolchain-bin if m68k-elf-gcc is not on PATH.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.2'
SYX_VERSION = '1.2a'          # the custom OS tag must be exactly 4 ASCII chars
DT_MOD = 'digifilter-dt'
DN_MOD = 'digifilter-dn'
DT_ELEMOD = f'digifilter-{VERSION}.elemod'
DN_ELEMOD = f'digifilter-dn-{VERSION}.elemod'
DT_CORE = f'core-4.0-os1.54.elemod'
DN_CORE = f'core-dn1-4.0-os1.44.elemod'


def arg_or_env(parser, args, name, env, help_text):
    value = getattr(args, name) or os.environ.get(env)
    if not value:
        parser.error(f'--{name.replace("_", "-")} is required (or set ${env})')
    return Path(value).expanduser().resolve()


def find_core(elekloader, name, explicit):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f'core not found: {path}')
        return path
    here = elekloader
    candidates = [
        here / 'mods' / 'core' / 'out' / name,
        here / 'mods' / 'core-dn1' / 'out' / name,
        here / name,
        here.parent / name,
        here.parent.parent / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit(
        f'core not found: {name}\n'
        f'looked in: {", ".join(str(p) for p in candidates)}\n'
        f'pass --core-dt/--core-dn explicitly')


def run(cmd, env):
    print('+', ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], cwd=ROOT, env=env, check=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build_one(args, env, mod, stock, core, elemod, syx):
    out = args.out
    run([sys.executable, '-m', 'elekloader.sdk.build', mod,
         '--stock', stock, '--out', out], env)
    if not elemod.is_file():
        raise SystemExit(f'expected build output not found: {elemod}')
    run([sys.executable, '-m', 'elekloader.lint', elemod,
         '--stock', stock, '--with', core], env)
    run([sys.executable, '-m', 'elekloader.patch', '--stock', stock,
         '--mod', core, '--mod', elemod, '--out', syx,
         '--version', SYX_VERSION, '--check'], env)
    if not args.no_syx:
        run([sys.executable, '-m', 'elekloader.patch', '--stock', stock,
             '--mod', core, '--mod', elemod, '--out', syx,
             '--version', SYX_VERSION], env)


def stage_elemod(elemod):
    dest_dir = ROOT / 'releases' / 'elemods'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / elemod.name
    shutil.copy2(elemod, dest)
    return dest


def make_zip(elemods):
    dest = ROOT / 'releases' / f'DigiFilter-{VERSION}.zip'
    include = ['README.md', 'LICENSE', 'CHANGELOG.md',
               DT_MOD, DN_MOD, 'shared', 'docs', 'tests', 'tools']
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in include:
            path = ROOT / name
            if path.is_file():
                z.write(path, path.relative_to(ROOT).as_posix())
            elif path.is_dir():
                for item in sorted(path.rglob('*')):
                    if item.is_file() and '__pycache__' not in item.parts:
                        z.write(item, item.relative_to(ROOT).as_posix())
        for elemod in elemods:
            z.write(elemod, f'elemods/{elemod.name}')
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--elekloader', required=False,
                        help='elekloader checkout (0.5+); or $ELEKLOADER_ROOT')
    parser.add_argument('--stock-dt', help='Digitakt_OS1.54.syx; or $DT_STOCK')
    parser.add_argument('--stock-dn', help='Digitone_OS1.44.syx; or $DN_STOCK')
    parser.add_argument('--core-dt', help=f'{DT_CORE} (default: next to the checkout)')
    parser.add_argument('--core-dn', help=f'{DN_CORE} (default: next to the checkout)')
    parser.add_argument('--toolchain-bin', help='directory with m68k-elf-gcc')
    parser.add_argument('--out', default=str(ROOT / 'out'),
                        help='build output directory (default: out/)')
    parser.add_argument('--no-syx', action='store_true',
                        help='only patch-check, do not write the test .syx files')
    parser.add_argument('--no-zip', action='store_true', help='do not write the release zip')
    args = parser.parse_args()

    elekloader = arg_or_env(parser, args, 'elekloader', 'ELEKLOADER_ROOT', 'elekloader checkout')
    stock_dt = arg_or_env(parser, args, 'stock_dt', 'DT_STOCK', 'Digitakt 1.54 stock .syx')
    stock_dn = arg_or_env(parser, args, 'stock_dn', 'DN_STOCK', 'Digitone 1.44 stock .syx')
    args.out = Path(args.out).expanduser().resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    core_dt = find_core(elekloader, DT_CORE, args.core_dt)
    core_dn = find_core(elekloader, DN_CORE, args.core_dn)

    env = os.environ.copy()
    pythonpath = str(elekloader)
    if env.get('PYTHONPATH'):
        pythonpath += os.pathsep + env['PYTHONPATH']
    env['PYTHONPATH'] = pythonpath
    env.setdefault('ELEKLOADER_CROSS', 'm68k-elf-')
    if args.toolchain_bin:
        env['PATH'] = str(Path(args.toolchain_bin).expanduser().resolve()) + os.pathsep + env['PATH']

    print(f'stock DT: {stock_dt}')
    print(f'core  DT: {core_dt}')
    print(f'stock DN: {stock_dn}')
    print(f'core  DN: {core_dn}')

    dt_elemod = args.out / DT_ELEMOD
    dn_elemod = args.out / DN_ELEMOD
    build_one(args, env, DT_MOD, stock_dt, core_dt, dt_elemod,
              args.out / f'digifilter-{VERSION}-dt.syx')
    build_one(args, env, DN_MOD, stock_dn, core_dn, dn_elemod,
              args.out / f'digifilter-{VERSION}-dn.syx')

    staged = [stage_elemod(dt_elemod), stage_elemod(dn_elemod)]
    for path in staged:
        print(f'staged {path.relative_to(ROOT)}  sha256 {sha256(path)}')
    if not args.no_zip:
        path = make_zip(staged)
        print(f'wrote {path.relative_to(ROOT)}  sha256 {sha256(path)}')
    print('OK: one elemod per machine, latest OS only')


if __name__ == '__main__':
    sys.exit(main())
