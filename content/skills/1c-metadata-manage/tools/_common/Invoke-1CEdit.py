#!/usr/bin/env python3
# Invoke-1CEdit.py — preview / apply wrapper for the ported (Python) tools of
# the 1c-metadata-manage skill: logical object addressing, a unified diff of
# what a run changed, and a rollback when the run was only a preview.
#
# Python peer of Invoke-1CEdit.ps1, contract-identical. It wraps only tools that
# ship a .py peer: the ports are the ones whose contracts (paths, -DryRun) this
# wrapper can vouch for on a POSIX host. A .ps1-only tool is refused with that
# explanation instead of failing halfway through a run.
#
# Three things it adds:
#
#   1. **Logical addressing.** `-Object Справочник.Контрагенты` resolves to the
#      physical XML path the tool expects. Nested forms, templates, rights and
#      modules resolve too (`Отчет.Продажи.Макет.ОсновнаяСхема`). The resolved
#      path is passed as the tool's own path parameter, which every path-taking
#      tool aliases.
#
#   2. **Unified diff.** Whatever the run changed is printed as a diff, so an
#      agent can show the change instead of claiming it.
#
#   3. **Preview (optional).** `-Preview` runs the real tool and then puts the
#      tree back. Default is apply immediately; `METADATA_PREVIEW=auto` limits
#      it to the risky cases (see docs/edit-preview.md). When the tool ships its
#      own `-DryRun` (meta-remove, remove-form, remove-template, db-load-git)
#      that native flag is used instead: it is a plan the tool itself vouches
#      for, and nothing is written that would need rolling back.
#
# Two rollback backends, chosen automatically:
#
#   - **git** (preferred) — the configuration dump lives in a repository. The
#     whole dump is watched, so a write outside the edited object is still
#     caught, and the rollback is `git checkout` + `git clean` of that path.
#     Requires the watched path to be clean before the run: rolling back over
#     someone's uncommitted work is the one failure this must never cause.
#   - **copy** (fallback) — no repository, or the dump is not tracked. The
#     object folder, its parent kind folder and the root `Configuration.xml` are
#     copied to a temp folder first. This scope is stated in the output, and a
#     write outside it is reported as unwatched rather than silently missed.
#
# Exit code is the tool's own exit code, except when a preview rollback fails,
# which exits 2 and says what is left on disk.

import argparse
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dev_env  # noqa: E402
import MetadataAddress  # noqa: E402


def write_section(text):
    print()
    print(f"== {text}")


def resolve_tool_script(name):
    """Find <Tool>.py under the skill's tools/ directory. Resolved by name, not
    by a hard-coded table, so an upstream sync that adds a tool needs no edit
    here. An ambiguous name is an error, never a guess."""
    tools_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    leaf = name if name.endswith('.py') else name + '.py'
    hits = []
    for dirpath, dirnames, filenames in os.walk(tools_root):
        dirnames.sort()
        if leaf in filenames:
            hits.append(os.path.join(dirpath, leaf))
    if not hits:
        ps1 = name if name.endswith('.ps1') else name + '.ps1'
        ps1_hits = []
        known = set()
        for dirpath, dirnames, filenames in os.walk(tools_root):
            dirnames.sort()
            if ps1 in filenames:
                ps1_hits.append(os.path.join(dirpath, ps1))
            for fname in filenames:
                if fname.endswith('.py'):
                    known.add(os.path.splitext(fname)[0])
        if ps1_hits:
            raise RuntimeError(f"Tool '{name}' has no Python peer - only the PowerShell script "
                               f"exists ({ps1_hits[0]}). Run it under a PowerShell host; on this "
                               f"machine there is no preview for it.")
        raise RuntimeError(f"Unknown tool '{name}'. Known Python tools: {', '.join(sorted(known))}")
    if len(hits) > 1:
        raise RuntimeError(f"Ambiguous tool '{name}' - {len(hits)} matches: {'; '.join(hits)}")
    return hits[0]


def get_script_parameters(script_path):
    """Parameter names and aliases of the target tool, read from its own
    add_argument calls. The ports parse their arguments at module top level,
    so the module must not be imported - importing it would execute the tool.
    The argparse wiring is read from the AST instead: the same technique the
    PowerShell wrapper plays on its own language (Parser::ParseFile on the
    param block), with the parser Python already ships."""
    with open(script_path, 'r', encoding='utf-8-sig') as fh:
        tree = ast.parse(fh.read(), filename=script_path)
    params = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_argument'
                and node.args):
            continue
        names = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not names:
            continue
        is_switch = False
        for kw in node.keywords:
            if kw.arg == 'action' and isinstance(kw.value, ast.Constant) \
                    and kw.value.value in ('store_true', 'store_false', 'store_const', 'count'):
                is_switch = True
        dest = None
        for kw in node.keywords:
            if kw.arg == 'dest' and isinstance(kw.value, ast.Constant):
                dest = kw.value.value
        if dest is None:
            longs = [n for n in names if n.startswith('--')]
            base = longs[0] if longs else names[0]
            dest = base.lstrip('-').replace('-', '_')
        params[dest] = {
            'name': names[0],      # primary option string, leading dash included
            'names': names,        # every accepted option string
            'is_switch': is_switch,
        }
    return params


def find_path_parameter(parameters):
    """The parameter that takes the target path: the one aliased '-Path' when
    there is one, otherwise the single *Path parameter that is not a switch."""
    for p in parameters.values():
        if '-Path' in p['names']:
            return p['name']
    candidates = [p for p in parameters.values()
                  if p['name'].endswith('Path') and not p['is_switch']]
    if len(candidates) == 1:
        return candidates[0]['name']
    return None


def to_parameter_table(arguments, parameters):
    """Remaining arguments come in flat: -Operation add-attribute -Value {...}.
    A switch of the target tool takes no value; anything else consumes the
    next token unless that token is itself a parameter name."""
    def is_switch(name):
        for p in parameters.values():
            if p['name'] == name or name in p['names']:
                return p['is_switch']
        return False

    table = {}
    i = 0
    while i < len(arguments):
        token = str(arguments[i])
        # A launcher that joins an empty argument list can hand us a blank token;
        # it carries no instruction, so skip it rather than fail the run.
        if not token.strip():
            i += 1
            continue
        if not token.startswith('-'):
            raise RuntimeError(f"Cannot pass '{token}' through: expected a -ParameterName before it.")
        name = token.lstrip('-')
        if is_switch(name) or i + 1 >= len(arguments):
            table[name] = None     # a switch carries no value
            i += 1
            continue
        nxt = str(arguments[i + 1])
        if nxt.startswith('-') and len(nxt) > 1 and not re.match(r'^-\d', nxt):
            table[name] = None
            i += 1
            continue
        table[name] = arguments[i + 1]
        i += 2
    return table


def build_tool_command(table, parameters):
    """Back to a flat command line, spelling every option the way the target
    declares it (an unknown name is passed through as given)."""
    command = []
    for name, value in table.items():
        option = f"-{name}"
        for p in parameters.values():
            if p['name'] == name or name in p['names']:
                option = p['name']
                break
        command.append(option)
        if value is not None:
            command.append(str(value))
    return command


def run_tool(script_path, command):
    """The real tool, same interpreter, output straight through."""
    return subprocess.run([sys.executable, '-B', script_path] + command)


def invoke_git(git_args):
    """Every git call goes through here: a CRLF warning on stderr must not
    abort a diff or, worse, a rollback, and line-ending translation is switched
    off because this code compares bytes - a filter that rewrites them would
    invent differences."""
    try:
        proc = subprocess.run(
            ['git', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false'] + git_args,
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        return proc.returncode, (proc.stdout or '').splitlines()
    except OSError:
        return 1, []


def test_git_tracked(path):
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    if not directory:
        return False
    return invoke_git(['-C', directory, 'rev-parse', '--is-inside-work-tree'])[0] == 0


def get_git_status(repo_dir, watch_path):
    code, out = invoke_git(['-C', repo_dir, 'status', '--porcelain',
                            '--untracked-files=all', '--', watch_path])
    if code != 0:
        return []
    return [line for line in out if line]


def new_copy_snapshot(paths):
    """Copy the watched paths into a temp folder. Returns a map original -> copy
    plus the list of watched roots, so both the diff and the rollback know
    exactly what was observed."""
    store = os.path.join(tempfile.gettempdir(), f"1c-edit-{uuid.uuid4().hex[:12]}")
    os.makedirs(store, exist_ok=True)
    files = {}
    counter = 0
    for watched in paths:
        if not os.path.exists(watched):
            continue
        if os.path.isdir(watched):
            items = []
            for dirpath, _dirnames, filenames in os.walk(watched):
                for fname in filenames:
                    items.append(os.path.join(dirpath, fname))
        else:
            items = [watched]
        for full in items:
            if full in files:
                continue
            counter += 1
            copy = os.path.join(store, f"{counter:05d}.bin")
            shutil.copyfile(full, copy)
            files[full] = copy
    return {'store': store, 'files': files, 'watched': list(paths)}


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def get_copy_changes(snapshot):
    changes = []
    for original in snapshot['files']:
        if not os.path.exists(original):
            changes.append({'path': original, 'kind': 'deleted'})
            continue
        if hash_file(snapshot['files'][original]) != hash_file(original):
            changes.append({'path': original, 'kind': 'modified'})
    for watched in snapshot['watched']:
        if not os.path.exists(watched):
            continue
        if os.path.isdir(watched):
            items = []
            for dirpath, _dirnames, filenames in os.walk(watched):
                for fname in filenames:
                    items.append(os.path.join(dirpath, fname))
        else:
            items = [watched]
        for full in items:
            if full not in snapshot['files']:
                changes.append({'path': full, 'kind': 'added'})
    return changes


def show_unified_diff(before, after, label):
    """git diff --no-index gives a real unified diff for any two files, including
    /dev/null for an addition or a deletion. git is already a hard requirement
    of the surrounding workflow, so there is no second diff implementation here
    to keep in sync."""
    nul = 'NUL' if os.name == 'nt' else '/dev/null'
    _code, out = invoke_git(['diff', '--no-index', '--no-color', '--',
                             before or nul, after or nul])
    if not out:
        return
    # git labels the two temp paths it was handed; rewrite the header so the
    # reader sees the file that actually changed.
    print(f"--- a/{label}")
    print(f"+++ b/{label}")
    for line in out[4:]:
        print(line)


def main():
    parser = argparse.ArgumentParser(
        prog='Invoke-1CEdit.py',
        description='Preview / apply wrapper for the ported tools of the 1c-metadata-manage skill: '
                    'logical addressing, a unified diff and a preview rollback.',
        allow_abbrev=False)
    parser.add_argument('-Tool', required=True,
                        help='short name of the tool script, e.g. meta-edit, form-edit')
    parser.add_argument('-Object', default=None,
                        help='logical address of the target, e.g. Справочник.Контрагенты')
    parser.add_argument('-Root', default=None,
                        help='configuration dump root; default: EXPORT_PATH from .dev.env, '
                             'else the nearest folder with a Configuration.xml')
    parser.add_argument('-Preview', '-DryRun', action='store_true',
                        help='run the tool, show the diff, then restore the tree')
    parser.add_argument('-Scope', nargs='+', default=[],
                        help='extra paths to watch and restore (copy backend)')
    parser.add_argument('-NoDiff', action='store_true',
                        help='apply without printing the diff')
    # Everything the wrapper does not know belongs to the tool: parse_known_args
    # returns those in the original order (REMAINDER would error on the first
    # unknown -Option instead of handing it through).
    args, tool_args = parser.parse_known_args()
    args.tool_args = tool_args

    try:
        script_path = resolve_tool_script(args.Tool)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    parameters = get_script_parameters(script_path)
    native_dry_run = 'DryRun' in parameters

    # ------------------------------------------------------------ resolve address
    target_path = None
    if args.Object:
        dump_root = MetadataAddress.resolve_dump_root(args.Root)
        if not dump_root:
            print("Cannot locate the configuration dump root. Pass -Root, or set EXPORT_PATH in .dev.env.",
                  file=sys.stderr)
            sys.exit(1)
        try:
            target_path = MetadataAddress.resolve_object_path(args.Object, dump_root)
        except MetadataAddress.AddressError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        path_param = find_path_parameter(parameters)
        if not path_param:
            print(f"{args.Tool} takes no single path parameter - drop -Object and pass "
                  f"its own parameters instead.", file=sys.stderr)
            sys.exit(1)
        args.tool_args = [path_param, target_path] + list(args.tool_args)

    try:
        table = to_parameter_table(args.tool_args, parameters)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------ native dry-run
    if args.Preview and native_dry_run:
        write_section(f"preview via the tool's own -DryRun ({args.Tool})")
        run = run_tool(script_path, build_tool_command(table, parameters) + ['-DryRun'])
        sys.exit(run.returncode)

    # ------------------------------------------------------------ watch and run
    watch_paths = []
    if target_path:
        watch_paths.extend(MetadataAddress.get_watch_paths(target_path))
    watch_paths.extend(args.Scope or [])
    watch_paths = sorted({p for p in watch_paths if p})

    backend = 'none'
    repo_dir = None
    snapshot = None
    git_watch = None

    if args.Preview:
        if not watch_paths:
            print("-Preview needs something to watch: pass -Object, or -Scope <path> "
                  "when the tool is addressed directly.", file=sys.stderr)
            sys.exit(1)
        anchor = watch_paths[0]
        if test_git_tracked(anchor):
            backend = 'git'
            repo_dir = anchor if os.path.isdir(anchor) else os.path.dirname(anchor)
            git_watch = MetadataAddress.resolve_dump_root(args.Root) if args.Object else anchor
            dirty = get_git_status(repo_dir, git_watch)
            if dirty:
                print("Refusing to preview: the watched path already has uncommitted changes.",
                      file=sys.stderr)
                print("A rollback would take them with it. Commit or stash first, or run without -Preview.",
                      file=sys.stderr)
                for line in dirty[:20]:
                    print(f"  {line}", file=sys.stderr)
                sys.exit(2)
        else:
            backend = 'copy'
            snapshot = new_copy_snapshot(watch_paths)
            print(f"Preview scope (copy backend): {'; '.join(watch_paths)}")
            print("Writes outside this scope are not watched and not rolled back.")

    write_section(f"run: {args.Tool}")
    run = run_tool(script_path, build_tool_command(table, parameters))
    tool_exit = run.returncode

    # ---------------------------------------------------------------- show diff
    if not args.NoDiff and args.Preview:
        write_section('diff')
        if backend == 'git':
            invoke_git(['-C', repo_dir, 'add', '--intent-to-add', '--all', '--', git_watch])
            _code, out = invoke_git(['-C', repo_dir, 'diff', '--no-color', '--', git_watch])
            if out:
                for line in out:
                    print(line)
            else:
                print('(no changes)')
            invoke_git(['-C', repo_dir, 'reset', '--quiet', '--', git_watch])
        else:
            changes = get_copy_changes(snapshot)
            if not changes:
                print('(no changes)')
            label_root = MetadataAddress.resolve_dump_root(args.Root) if args.Object else None
            for change in changes:
                label = change['path']
                if label_root and change['path'].startswith(label_root):
                    label = change['path'][len(label_root):].lstrip('\\/')
                if change['kind'] == 'added':
                    show_unified_diff(None, change['path'], label)
                elif change['kind'] == 'deleted':
                    show_unified_diff(snapshot['files'][change['path']], None, label)
                elif change['kind'] == 'modified':
                    show_unified_diff(snapshot['files'][change['path']], change['path'], label)

    # ----------------------------------------------------------------- rollback
    if args.Preview:
        write_section('rollback (preview)')
        failed = False
        if backend == 'git':
            if invoke_git(['-C', repo_dir, 'checkout', '--quiet', '--', git_watch])[0] != 0:
                failed = True
            if invoke_git(['-C', repo_dir, 'clean', '--quiet', '-fd', '--', git_watch])[0] != 0:
                failed = True
            left = get_git_status(repo_dir, git_watch)
            if left:
                failed = True
                for line in left:
                    print(f"  still dirty: {line}", file=sys.stderr)
        else:
            for change in get_copy_changes(snapshot):
                try:
                    if change['kind'] == 'added':
                        os.remove(change['path'])
                    else:
                        shutil.copyfile(snapshot['files'][change['path']], change['path'])
                except OSError as exc:
                    failed = True
                    print(f"  restore failed: {change['path']} - {exc}", file=sys.stderr)
            shutil.rmtree(snapshot['store'], ignore_errors=True)
        if failed:
            print("Rollback incomplete - the tree still holds part of the preview. "
                  "Inspect before continuing.", file=sys.stderr)
            sys.exit(2)
        print('tree restored; nothing was applied')

    sys.exit(tool_exit)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
