#!/usr/bin/env python3
# web-publish v1.4 — Publish 1C infobase via Apache
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
#
# Deviations from web-publish.ps1 (py twin only):
#   * Linux / macOS: the web module is wsap24.so, the server binary is bin/httpd,
#     the platform is auto-discovered under /opt/1cv8. Apache is NOT downloaded
#     there (Apache Lounge ships Windows builds only) — the -Manual instruction is
#     printed instead. bin/httpd may be a prefix build or a link to the distribution
#     binary (Debian/Ubuntu `apache2`): the server is started with explicit
#     `-d <ApachePath> -f conf/httpd.conf`, and its processes are recognised by that
#     command line, not only by the `httpd` process name.
#   * Processes and the port holder are looked up with psutil when it is installed,
#     otherwise with OS tools (CIM / netstat / tasklist on Windows, /proc and ss on
#     Linux) — the PowerShell cmdlets have no Python equivalent in the stdlib.
#   * default.vrd also sets publishExtensionsByDefault="true": publishByDefault alone
#     publishes the HTTP services of the main configuration only, and the services of
#     configuration extensions answer 404.
#   * The generated httpd.conf blocks are inserted literally: a `$` in a path is not
#     treated as a regex substitution group, as it is by [regex]::Replace.

import argparse
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "_common"))
import dev_env  # noqa: E402

IS_WINDOWS = os.name == "nt"
WSAP_NAME = "wsap24.dll" if IS_WINDOWS else "wsap24.so"
HTTPD_NAME = "httpd.exe" if IS_WINDOWS else "httpd"
DOWNLOAD_PAGE = "https://www.apachelounge.com/download/"


def info(msg=""):
    print(msg, flush=True)


def fail(msg, hint=None):
    print(msg, file=sys.stderr, flush=True)
    if hint:
        print(hint, file=sys.stderr, flush=True)
    sys.exit(1)


# --- Resolve V8Path ---

def _find_project_v8path():
    """.dev.env PLATFORM_PATH first, then the nearest .v8-project.json v8path."""
    # 1c-rules: .dev.env is this project's single source of truth — it wins over
    # .v8-project.json, which stays supported as the legacy fallback below.
    value = dev_env.get_value("PLATFORM_PATH")
    if value:
        return value
    d = os.getcwd()
    while True:
        pf = os.path.join(d, ".v8-project.json")
        if os.path.isfile(pf):
            try:
                with open(pf, encoding="utf-8-sig") as f:
                    v = json.load(f).get("v8path")
                if v:
                    return str(v)
            except Exception:
                pass
            return None
        parent = os.path.dirname(d)
        if not parent or parent == d:
            return None
        d = parent


def _version_dir(p):
    """Version dir for both Windows (.../1cv8/<ver>/bin/1cv8.exe) and *nix (.../1cv8/<ver>/1cv8)."""
    parent = os.path.dirname(p)
    if os.path.basename(parent).lower() == "bin":
        parent = os.path.dirname(parent)
    return os.path.basename(parent)


def _version_key(p):
    return [int(x) for x in re.findall(r"\d+", _version_dir(p))]


def resolve_v8path(v8path):
    """Directory that holds the web module (wsap24)."""
    if not v8path:
        v8path = _find_project_v8path()
    if not v8path:
        if IS_WINDOWS:
            candidates = (glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe")
                          + glob.glob(r"C:\Program Files (x86)\1cv8\*\bin\1cv8.exe"))
        else:
            # PY-only: Linux packages install to /opt/1cv8/<arch>/<ver>/.
            candidates = glob.glob("/opt/1cv8/*/*/1cv8") + glob.glob("/opt/1cv8/*/1cv8")
        if not candidates:
            fail("Error: платформа 1С не найдена. Укажите -V8Path")
        found = max(candidates, key=_version_key)
        v8path = os.path.dirname(found)
        info(f"Auto-selected platform {_version_dir(found)}: {v8path}")
    elif os.path.isfile(v8path):
        v8path = os.path.dirname(v8path)
    elif (os.path.isdir(v8path)
          and not os.path.isfile(os.path.join(v8path, WSAP_NAME))
          and os.path.isfile(os.path.join(v8path, "bin", WSAP_NAME))):
        # PLATFORM_PATH (.dev.env) may point at the platform install dir — the web
        # module lives in bin/, same shape the db-* tools accept.
        v8path = os.path.join(v8path, "bin")
    return v8path


# --- Apache install ---

def install_apache(apache_path):
    info("Apache не найден. Скачиваю...")
    tmp = tempfile.gettempdir()
    tmp_zip = os.path.join(tmp, "apache24.zip")
    tmp_dir = os.path.join(tmp, "apache24_extract")

    try:
        info(f"Определяю актуальную версию с {DOWNLOAD_PAGE} ...")
        req = urllib.request.Request(DOWNLOAD_PAGE, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Links are typically relative (/download/...), try that first
        m = re.search(r'(?i)href="(/download/[^"]*?httpd-[^"]*?Win64[^"]*?\.zip)"', html)
        if not m:
            m = re.search(r'(?i)href="(https://[^"]*?httpd-[^"]*?Win64[^"]*?\.zip)"', html)
        if not m:
            info("Не удалось определить ссылку автоматически.")
            fail(f"Скачайте вручную: {DOWNLOAD_PAGE}")
        zip_url = m.group(1)
        if zip_url.startswith("/"):
            zip_url = "https://www.apachelounge.com" + zip_url
        info(f"Найдено: {zip_url}")
        req = urllib.request.Request(zip_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(tmp_zip, "wb") as out:
            shutil.copyfileobj(resp, out)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        fail(f"Error: не удалось скачать Apache: {e}",
             f"Скачайте вручную: {DOWNLOAD_PAGE}")

    info("Распаковка...")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    with zipfile.ZipFile(tmp_zip) as zf:
        zf.extractall(tmp_dir)

    # Move Apache24 contents up to ApachePath
    inner_dir = os.path.join(tmp_dir, "Apache24")
    if not os.path.isdir(inner_dir):
        inner_dir = None
        for root, dirs, _files in os.walk(tmp_dir):
            if "Apache24" in dirs:
                inner_dir = os.path.join(root, "Apache24")
                break
        if not inner_dir:
            fail("Error: каталог Apache24 не найден в архиве")

    os.makedirs(apache_path, exist_ok=True)
    shutil.copytree(inner_dir, apache_path, dirs_exist_ok=True)

    # Cleanup
    try:
        os.remove(tmp_zip)
    except OSError:
        pass
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # Patch ServerRoot in httpd.conf
    conf_file = os.path.join(apache_path, "conf", "httpd.conf")
    if os.path.isfile(conf_file):
        apache_fwd = apache_path.replace("\\", "/")
        content = read_text(conf_file)
        content = re.sub(r"(?m)^Define SRVROOT .*$",
                         lambda _m: f'Define SRVROOT "{apache_fwd}"', content)
        write_text(conf_file, content)
        info(f"ServerRoot обновлён: {apache_fwd}")

    info(f"Apache установлен: {apache_path}")


def manual_instruction(apache_path):
    info(f"Apache не найден: {apache_path}")
    info("")
    info("Установите Apache вручную:")
    if IS_WINDOWS:
        info(f"  1. Скачайте Apache Lounge (x64) с {DOWNLOAD_PAGE}")
        info(f"  2. Распакуйте содержимое Apache24\\ в: {apache_path}")
    else:
        # PY-only: no portable Apache for *nix — use a prefix build or the distribution binary.
        info("  1. Соберите Apache httpd 2.4 с --prefix в каталог ниже или поставьте пакет")
        info("     (apache2 в Debian/Ubuntu) и сделайте ссылку:")
        info(f"     ln -s /usr/sbin/apache2 {os.path.join(apache_path, 'bin', 'httpd')}")
        info(f"  2. Создайте {os.path.join(apache_path, 'conf', 'httpd.conf')}: для пакета apache2")
        info("     модули не встроены — нужны LoadModule mpm_prefork, authz_core, alias,")
        info("     а также ServerName, PidFile и ErrorLog в каталоге публикации")
    info("  3. Запустите скрипт повторно")
    sys.exit(1)


# --- Text IO (mirrors [System.IO.File]::ReadAllText / WriteAllText) ---

def read_text(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return f.read()


def write_text(path, content, bom=False):
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(content)


def replace_or_append(content, start, end, block):
    if start in content:
        pattern = re.escape(start) + r"[\s\S]*?" + re.escape(end)
        return re.sub(pattern, lambda _m: block, content)
    return None


# --- Processes / port ---

def _norm(path):
    return os.path.normcase(os.path.realpath(path)) if path else ""


# Process names of Apache: a prefix build or Windows (`httpd`) and the Debian/Ubuntu
# distribution binary (`apache2`), which bin/httpd may link to.
HTTPD_PROCESS_NAMES = ("httpd", "httpd.exe", "apache2")


def list_httpd():
    """[(pid, exe_path, command_line)] of every running Apache process."""
    try:
        import psutil  # optional
        result = []
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            name = (p.info.get("name") or "").lower()
            if name in HTTPD_PROCESS_NAMES:
                result.append((p.info["pid"], p.info.get("exe") or "",
                               " ".join(p.info.get("cmdline") or [])))
        return result
    except ImportError:
        pass
    if IS_WINDOWS:
        cmd = ("Get-CimInstance Win32_Process -Filter \"Name='httpd.exe'\" | "
               "ForEach-Object { \"$($_.ProcessId)`t$($_.ExecutablePath)\" }")
        try:
            out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd],
                                 capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        result = []
        for line in out.splitlines():
            pid, _, exe = line.partition("\t")
            if pid.strip().isdigit():
                result.append((int(pid), exe.strip(), ""))
        return result
    result = []
    for entry in glob.glob("/proc/[0-9]*"):
        try:
            with open(os.path.join(entry, "comm")) as f:
                if f.read().strip() not in HTTPD_PROCESS_NAMES:
                    continue
        except OSError:
            continue
        try:
            exe = os.readlink(os.path.join(entry, "exe"))
        except OSError:
            exe = ""
        try:
            with open(os.path.join(entry, "cmdline"), "rb") as f:
                cmdline = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            cmdline = ""
        result.append((int(os.path.basename(entry)), exe, cmdline))
    return result


def our_httpd(httpd_exe, apache_path=""):
    """PIDs of the Apache started for this ApachePath.

    A process is ours when its executable is bin/httpd itself, or when its command
    line carries `-d <ApachePath>` — the case of bin/httpd linking to a distribution
    binary, whose resolved executable (/usr/sbin/apache2) is shared with other servers.
    """
    target = _norm(httpd_exe)
    # A link resolves to the shared distribution binary: only the command line tells ours apart.
    by_exe = not os.path.islink(httpd_exe)
    marker = f"-d {apache_path} " if apache_path else None
    pids = []
    for pid, exe, cmdline in list_httpd():
        if marker and marker in cmdline + " ":
            pids.append(pid)
        elif by_exe and exe and _norm(exe) == target:
            pids.append(pid)
    return pids


def port_holder(port):
    """(busy, pid or None) for a local TCP port, like Get-NetTCPConnection -LocalPort."""
    try:
        import psutil  # optional
        try:
            for c in psutil.net_connections(kind="tcp"):
                if c.laddr and c.laddr.port == port:
                    return True, c.pid
            return False, None
        except psutil.AccessDenied:
            pass
    except ImportError:
        pass
    if IS_WINDOWS:
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].rsplit(":", 1)[-1] == str(port):
                return True, int(parts[-1]) if parts[-1].isdigit() else None
        if out:
            return False, None
    elif shutil.which("ss"):
        try:
            out = subprocess.run(["ss", "-Htanp"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[3].rsplit(":", 1)[-1] == str(port):
                m = re.search(r"pid=(\d+)", line)
                return True, int(m.group(1)) if m else None
        return False, None
    # Last resort: can we bind it?
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return False, None
        except OSError:
            return True, None


def process_name(pid):
    try:
        import psutil  # optional
        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        pass
    if IS_WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout
            m = re.match(r'"([^"]+)"', out.strip())
            return m.group(1) if m else None
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return None


def kill(pid):
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


def start_hidden(exe, cwd):
    kwargs = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    if IS_WINDOWS:
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
        command = [exe]
    else:
        kwargs["start_new_session"] = True
        # A distribution binary has no compiled-in knowledge of this layout: without
        # -d/-f it reads /etc/apache2/apache2.conf. A prefix build accepts the same flags.
        command = [exe, "-d", cwd, "-f", os.path.join(cwd, "conf", "httpd.conf")]
    subprocess.Popen(command, **kwargs)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Publish 1C infobase via Apache HTTP Server",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="", help="Platform bin directory (for wsap24)")
    parser.add_argument("-InfoBasePath", default="", help="File infobase path")
    parser.add_argument("-InfoBaseServer", default="", help="1C server (server infobase)")
    parser.add_argument("-InfoBaseRef", default="", help="Infobase name on the server")
    parser.add_argument("-UserName", default="", help="1C user name")
    parser.add_argument("-Password", default="", help="1C user password")
    parser.add_argument("-AppName", default="", help="Publication name (default: from infobase name)")
    parser.add_argument("-ApachePath", default="", help="Apache root (default: tools/apache24)")
    parser.add_argument("-Port", type=int, default=8081, help="Port (default 8081)")
    parser.add_argument("-Manual", action="store_true", help="Do not download Apache")
    args = parser.parse_args()

    v8path = resolve_v8path(args.V8Path)

    # Validate wsap24
    wsap_dll = os.path.join(v8path, WSAP_NAME)
    if not os.path.isfile(wsap_dll):
        fail(f"Error: {WSAP_NAME} не найден в {v8path}")

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        fail("Error: укажите -InfoBasePath или -InfoBaseServer + -InfoBaseRef")

    # --- Resolve ApachePath ---
    apache_path = args.ApachePath or os.path.join(os.getcwd(), "tools", "apache24")
    # Ensure absolute path (agent may pass relative like "tools/apache24")
    apache_path = os.path.abspath(apache_path)

    # --- Check / Install Apache ---
    httpd_exe = os.path.join(apache_path, "bin", HTTPD_NAME)
    if not os.path.isfile(httpd_exe):
        if args.Manual or not IS_WINDOWS:
            manual_instruction(apache_path)
        install_apache(apache_path)

    # --- Derive AppName ---
    app_name = args.AppName
    if not app_name:
        if args.InfoBasePath:
            leaf = re.split(r"[\\/]", args.InfoBasePath.rstrip("\\/"))[-1]
            app_name = re.sub(r"[^\w]", "", leaf)
        else:
            app_name = re.sub(r"[^\w]", "", args.InfoBaseRef)
    app_name = app_name.lower()
    if not app_name:
        fail("Error: не удалось определить имя публикации. Укажите -AppName")

    info(f"Публикация: {app_name}")

    # --- Create publish directory ---
    publish_dir = os.path.join(apache_path, "publish", app_name)
    os.makedirs(publish_dir, exist_ok=True)

    # --- Generate default.vrd ---
    vrd_path = os.path.join(publish_dir, "default.vrd")
    ib_parts = []
    if args.InfoBaseServer and args.InfoBaseRef:
        ib_parts.append(f"Srvr=&quot;{args.InfoBaseServer}&quot;")
        ib_parts.append(f"Ref=&quot;{args.InfoBaseRef}&quot;")
    else:
        ib_parts.append(f"File=&quot;{args.InfoBasePath}&quot;")
    if args.UserName:
        ib_parts.append(f"Usr=&quot;{args.UserName}&quot;")
    if args.Password:
        ib_parts.append(f"Pwd=&quot;{args.Password}&quot;")
    ib_string = ";".join(ib_parts) + ";"

    vrd_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<point xmlns="http://v8.1c.ru/8.2/virtual-resource-system"\n'
        '       xmlns:xs="http://www.w3.org/2001/XMLSchema"\n'
        '       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        f'       base="/{app_name}"\n'
        f'       ib="{ib_string}">\n'
        '    <standardOdata enable="true"/>\n'
        '    <ws pointEnableCommon="true"/>\n'
        '    <httpServices publishByDefault="true" publishExtensionsByDefault="true"/>\n'
        '</point>'
    )
    write_text(vrd_path, vrd_content, bom=True)
    info(f"default.vrd: {vrd_path}")

    # --- Update httpd.conf ---
    conf_file = os.path.join(apache_path, "conf", "httpd.conf")
    if not os.path.isfile(conf_file):
        fail(f"Error: httpd.conf не найден: {conf_file}")

    conf = read_text(conf_file)
    wsap_fwd = wsap_dll.replace("\\", "/")
    publish_dir_fwd = publish_dir.replace("\\", "/")
    vrd_path_fwd = vrd_path.replace("\\", "/")

    # --- Global block (Listen + LoadModule) ---
    g_start = "# --- 1C: global ---"
    g_end = "# --- End: global ---"
    global_block = (f"{g_start}\n"
                    f"Listen {args.Port}\n"
                    f'LoadModule _1cws_module "{wsap_fwd}"\n'
                    f"{g_end}")
    replaced = replace_or_append(conf, g_start, g_end, global_block)
    if replaced is not None:
        conf = replaced
    else:
        # Comment out default Listen to avoid port conflict
        conf = re.sub(r"(?m)^(Listen\s+\d+)", r"#\1  # commented by web-publish", conf)
        conf = conf.rstrip() + "\n\n" + global_block + "\n"

    # --- Publication block ---
    p_start = f"# --- 1C Publication: {app_name} ---"
    p_end = f"# --- End: {app_name} ---"
    pub_block = (f"{p_start}\n"
                 f'Alias "/{app_name}" "{publish_dir_fwd}"\n'
                 f'<Directory "{publish_dir_fwd}">\n'
                 "    AllowOverride All\n"
                 "    Require all granted\n"
                 "    SetHandler 1c-application\n"
                 f'    ManagedApplicationDescriptor "{vrd_path_fwd}"\n'
                 "</Directory>\n"
                 f"{p_end}")
    replaced = replace_or_append(conf, p_start, p_end, pub_block)
    if replaced is not None:
        conf = replaced
    else:
        conf = conf.rstrip() + "\n\n" + pub_block + "\n"

    write_text(conf_file, conf)
    info("httpd.conf обновлён")

    # --- Check port availability ---
    busy, holder_pid = port_holder(args.Port)
    if busy and not our_httpd(httpd_exe, apache_path):
        name = process_name(holder_pid) if holder_pid else None
        if name:
            holder = f"{name} (PID: {holder_pid})"
        elif holder_pid:
            holder = f"PID {holder_pid}"
        else:
            holder = "неизвестным процессом"
        fail(f"Error: порт {args.Port} занят процессом {holder}",
             "Укажите другой порт: -Port 9090")

    # --- Start Apache if not running ---
    running = our_httpd(httpd_exe, apache_path)
    if running:
        info(f"Apache уже запущен (PID: {running[0]})")
        info("Перезапуск для применения конфигурации...")
        for pid in running:
            kill(pid)
        time.sleep(1)
    else:
        # Check if a foreign httpd holds the port
        foreign = list_httpd()
        if foreign and not IS_WINDOWS:
            foreign = [p for p in foreign if f"-d {apache_path} " not in p[2] + " "]
        if foreign:
            info(f"[WARN] Обнаружен сторонний Apache (PID: {foreign[0][0]})")
            info(f"       Наш Apache: {httpd_exe}")

    info("Запуск Apache...")
    start_hidden(httpd_exe, apache_path)
    time.sleep(2)

    started = our_httpd(httpd_exe, apache_path)
    if started:
        info(f"Apache запущен (PID: {started[0]})")
    else:
        print("Apache не удалось запустить", file=sys.stderr)
        # Run config test for diagnostics
        try:
            test_cmd = [httpd_exe, "-t"] if IS_WINDOWS else [
                httpd_exe, "-t", "-d", apache_path, "-f", os.path.join(apache_path, "conf", "httpd.conf")]
            test = subprocess.run(test_cmd, cwd=apache_path, capture_output=True,
                                  text=True, errors="replace", timeout=60)
            test_out = (test.stdout + test.stderr).splitlines()
        except (OSError, subprocess.SubprocessError) as e:
            test_out = [str(e)]
        if test_out:
            print("--- httpd -t ---", file=sys.stderr)
            for line in test_out:
                print(f"  {line}", file=sys.stderr)
        error_log = os.path.join(apache_path, "logs", "error.log")
        if os.path.isfile(error_log):
            print("--- error.log (последние 10 строк) ---", file=sys.stderr)
            with open(error_log, encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines()[-10:]:
                    print(line, file=sys.stderr)
        sys.exit(1)

    # --- Result ---
    info("")
    info("=== Публикация готова ===")
    info(f"URL:          http://localhost:{args.Port}/{app_name}")
    info(f"OData:        http://localhost:{args.Port}/{app_name}/odata/standard.odata")
    info(f"HTTP-сервисы: http://localhost:{args.Port}/{app_name}/hs/<RootUrl>/...")
    info(f"Web-сервисы:  http://localhost:{args.Port}/{app_name}/ws/<Имя>?wsdl")


if __name__ == "__main__":
    main()
