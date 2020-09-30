#!/usr/bin/env python3
#-*- coding: utf-8 -*-

__author__ = "Mikhail Zhigun"
__copyright__ = "Copyright 2020, MeteoSwiss"

SCRIPT_DESC = """
Script configures ICON build with the following parameters:
    Build platform: Ubuntu 20 Desktop, CPU
    Target platform: Ubuntu 20 Desktop, CPU   
"""

import sys
assert sys.version_info[0] >= 3 and sys.version_info[1] >= 6, 'Python >= 3.6 is required'
import argparse, os
from typing import NamedTuple, Optional, Tuple
from enum import Enum
from os.path import join as join_path
import subprocess
from subprocess import run
try:
    import apt
except:
    print('Install python-apt [sudo apt-get install python-apt]')
    raise
try:
    import git
except:
    print('Install python-git [sudo apt-get install python3-git]')
    raise
from git import RemoteProgress, UpdateProgress


class Args(NamedTuple):
    icon_dir: str
    build_dir: str
    cc: str
    fc: str
    claw: Optional[str]
    icon_git_repo: Optional[str]
    icon_git_branch: Optional[str]
    mpi: bool


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description=SCRIPT_DESC)
    parser.add_argument('--icon-dir', type=str, required=True, help='Path to ICON source')
    parser.add_argument('--build-dir', type=str, required=True, help='Build directory')
    parser.add_argument('--fc', '--fortran-compiler', type=str, default='/usr/bin/gfortran', help='Path to Fortran compiler')
    parser.add_argument('--cc', '--c-compiler', type=str, default='/usr/bin/gcc', help='Path to C compiler')
    parser.add_argument('--claw', type=str, help='PAth to CLAW executable')
    parser.add_argument('--icon-git-repo', type=str, help='ICON git repository')
    parser.add_argument('--icon-git-branch', type=str, help='ICON git branch name')
    parser.add_argument('--mpi', action='store_true', help='Enable MPI')
    p_args = parser.parse_args()
    args = Args(icon_dir=p_args.icon_dir,
                build_dir=p_args.build_dir,
                cc=p_args.cc,
                fc=p_args.fc,
                claw=p_args.claw,
                icon_git_repo=p_args.icon_git_repo,
                icon_git_branch=p_args.icon_git_branch,
                mpi=p_args.mpi)
    return args


def dir_exists(path: str):
    return os.path.exists(path) and os.path.isdir(path)


def file_exists(path: str):
    return os.path.exists(path) and os.path.isfile(path)


class ReturnCode(Enum):
    SUCCESS = 0
    FAILURE = 1


RC = ReturnCode


class DependencyInfo(NamedTuple):
    name: str
    apt_package: str
    include_dir: str
    lib_dir: str
    test_h: str
    lib: str


DepInfo = DependencyInfo


DEPS = (
    DepInfo('lapack', 'liblapacke-dev', '/usr/include', '/usr/lib/x86_64-linux-gnu/lapack', 'lapacke.h', 'liblapack.so'),
    DepInfo('blas', 'libblas-dev', '/usr/include/x86_64-linux-gnu', '/usr/lib/x86_64-linux-gnu/blas', 'cblas.h', 'libblas.so'),
    DepInfo('NetCDF-Fortran', 'libnetcdff-dev', '/usr/include', '/usr/lib/x86_64-linux-gnu', 'netcdf.inc', 'libnetcdf.so'),
    DepInfo('NetCDF-C', 'libnetcdf-dev', '/usr/include', '/usr/lib/x86_64-linux-gnu', 'netcdf.h', 'libnetcdff.so'),
    DepInfo('zlib', 'zlib1g-dev', '/usr/include', '/usr/lib/x86_64-linux-gnu', 'zlib.h', 'libz.so'),
    DepInfo('szip', 'libsz2', '/usr/include', '/usr/lib/x86_64-linux-gnu', 'szlib.h', 'libsz.so'),
    DepInfo('xml2', 'libxml2-dev', '/usr/include/libxml2', '/usr/lib/x86_64-linux-gnu', 'libxml/parser.h', 'libxml2.so'))


def check_dependencies():
    cache = apt.cache.Cache()
    #cache.update()
    cache.open()
    for dep in DEPS:
        print(f'\t{dep.name}')
        pkg = cache.get(dep.apt_package)
        assert pkg is not None, f'\t\tApt package "{dep.apt_package}" not found. Update apt cache with' + \
                                f' [sudo apt-get update] before running the script'
        assert pkg.is_installed, f'Install "{dep.apt_package}" with [sudo apt-get install {dep.apt_package}]'
        test_h_path = join_path(dep.include_dir, dep.test_h)
        test_lib_path = join_path(dep.lib_dir, dep.lib)
        assert file_exists(test_h_path), f'Header "{dep.test_h}" not found at {dep.include_dir}'
        assert file_exists(test_lib_path), f'Header "{dep.lib}" not found at {dep.lib_dir}'


def configure(args: Args):
    assert dir_exists(args.icon_dir), f'ICON source dir "{args.icon_dir}" not found'


def prepare_source(args: Args):
    if args.icon_git_repo is not None:
        git_link = args.icon_git_repo
        git_branch= args.icon_git_branch
        if git_branch is None:
            git_branch = 'master'
        if dir_exists(args.icon_dir):
            print(f'\tSource directory "{args.icon_dir}" not empty')
            repo = git.Repo(args.icon_dir)
            dir_link = repo.remote("origin").url
            assert dir_link == git_link, f'\tSource directory origin is in different repository "{dir_link}"'
            dir_branch_name = repo.active_branch.name
            assert dir_branch_name == git_branch, f'\tSource directory origin is different branch "{dir_branch_name}"'
        else:
            class CloneProgress(RemoteProgress):
                def update(self, op_code, cur_count, max_count=None, message=''):
                    if message:
                        print(message)
            print(f'Cloning into {args.icon_dir}')
            git.Repo.clone_from(git_link, args.icon_dir, branch=git_branch, progress=CloneProgress())
        repo = git.Repo(args.icon_dir)
        print('\tUpdating submodules...')
        class SubmoduleUpdateProgress(UpdateProgress):
            def update(self, op_code, cur_count, max_count=None, message=''):
                if message:
                    print(message)
        for submodule in repo.submodules:
            print(f'\t{submodule.name}')
            submodule.update(init=True, progress=SubmoduleUpdateProgress())
    else:
        assert dir_exists(args.icon_dir), f'ICON source dir "{args.icon_dir}" does not exist'


def generate_configure_script(args: Args) -> Tuple[str, str]:
    include_dirs = set()
    lib_dirs = set()
    libs = []
    cfg_flags = []
    for dep in DEPS:
        include_dirs.add(dep.include_dir)
        lib_dirs.add(dep.lib_dir)
        lib = dep.lib
        assert lib.startswith('lib')
        lib = lib[3:]
        if lib.endswith('.a'):
            lib = lib[:-2]
        elif lib.endswith('.so'):
            lib = lib[:-3]
        libs.append(lib)
    inc_str = ' '.join([f'-I{inc}' for inc in include_dirs])
    lib_dirs_str = ' '.join([f'-L{lib}' for lib in lib_dirs])
    libs_str = ' '.join([f'-l{lib}' for lib in libs])
    cfg_defs = f'''
export CC="{args.cc}"
export FC="{args.fc}"
export CFLAGS="{inc_str}"
export CPPFLAGS="{inc_str}"
export FCFLAGS="{inc_str}"
export LDFLAGS="{lib_dirs_str}"
export LIBS="{libs_str}"
'''
    if args.claw is not None:
        cfg_defs += f'export CLAW="{args.claw}"'
        cfg_flags += ['--enable-claw']
    if args.mpi:
        assert False, 'Not implemented'
    else:
        cfg_flags += ['--disable-mpi']
    cfg_flags_str = ' '.join(cfg_flags)
    cfg_script_header = '''
#!/bin/bash
'''
    cfg_script = cfg_script_header + cfg_defs
    cfg_script += f'''
{args.icon_dir}/configure {cfg_flags_str}
'''
    os.makedirs(args.build_dir, exist_ok=True)
    cfg_script_file = join_path(args.build_dir, 'configure.sh')
    if file_exists(cfg_script_file):
        txt = None
        with open(cfg_script_file, 'r') as f:
            txt = f.read()
        if cfg_script != txt:
            os.remove(cfg_script_file)
    with open(cfg_script_file, 'w') as f:
        f.write(cfg_script)
    return cfg_script_file, cfg_script


def check_compilers(args: Args):
    assert file_exists(args.cc), f'C compiler "{args.cc}" not found'
    assert file_exists(args.fc), f'Fortran compiler "{args.cc}" not found'
    if args.claw is not None:
        assert file_exists(args.claw), f'CLAW compiler "{args.claw}" not found'


def main():
    args = parse_args()
    print('Checking that dependencies are installed...')
    check_dependencies()
    print('Preparing source...')
    prepare_source(args)
    print('Checking compilers...')
    check_compilers(args)
    print('Generating configure script...')
    cfg_script_file, cfg_script = generate_configure_script(args)
    print(cfg_script)
    print('Configuring ICON...')
    assert run(f'bash configure.sh',
               shell=True,
               cwd=args.build_dir,
               stdout=sys.stdout, stderr=subprocess.STDOUT).returncode == RC.SUCCESS.value


if __name__ == '__main__':
    main()
    sys.exit(RC.SUCCESS.value)
