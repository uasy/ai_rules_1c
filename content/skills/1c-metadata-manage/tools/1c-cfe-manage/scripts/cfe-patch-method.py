#!/usr/bin/env python3
# cfe-patch-method v2.5-partial — Source-aware method interceptor for 1C extension (CFE)
# Generation is ported in full; the -Check / -Actualize resync of controlled
# (&ИзменениеИКонтроль) methods is NOT yet ported and exits with a notice.
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills

import argparse
import os
import re
import sys
from lxml import etree

# ============================================================================
# Helpers
# ============================================================================

TYPE_DIR_MAP = {
    "Catalog": "Catalogs", "Document": "Documents", "Enum": "Enums",
    "CommonModule": "CommonModules", "Report": "Reports", "DataProcessor": "DataProcessors",
    "ExchangePlan": "ExchangePlans", "ChartOfAccounts": "ChartsOfAccounts",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "BusinessProcess": "BusinessProcesses", "Task": "Tasks",
    "InformationRegister": "InformationRegisters", "AccumulationRegister": "AccumulationRegisters",
    "AccountingRegister": "AccountingRegisters", "CalculationRegister": "CalculationRegisters",
    "Catalogs": "Catalogs", "Documents": "Documents", "Enums": "Enums",
    "CommonModules": "CommonModules", "Reports": "Reports", "DataProcessors": "DataProcessors",
    "ExchangePlans": "ExchangePlans", "ChartsOfAccounts": "ChartsOfAccounts",
    "ChartsOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartsOfCalculationTypes": "ChartsOfCalculationTypes",
    "BusinessProcesses": "BusinessProcesses", "Tasks": "Tasks",
    "InformationRegisters": "InformationRegisters",
    "AccumulationRegisters": "AccumulationRegisters",
    "AccountingRegisters": "AccountingRegisters",
    "CalculationRegisters": "CalculationRegisters",
}

# InterceptorType -> Russian decorator keyword
DECORATOR_MAP = {
    "Before": "Перед", "After": "После", "Instead": "Вместо",
    "ModificationAndControl": "ИзменениеИКонтроль",
}

MODULE_FILE_MAP = {
    "ObjectModule": "ObjectModule.bsl",
    "ManagerModule": "ManagerModule.bsl",
    "RecordSetModule": "RecordSetModule.bsl",
    "CommandModule": "CommandModule.bsl",
    "ValueManagerModule": "ValueManagerModule.bsl",
}

CONTEXT_DIRECTIVE_RE = re.compile(
    r'^&(НаКлиенте|НаСервере|НаСервереБезКонтекста|НаКлиентеНаСервереБезКонтекста|'
    r'НаКлиентеНаСервере)\s*$')


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def get_module_rel_path(module_path):
    """Relative .bsl path segments from a logical ModulePath."""
    parts = module_path.split(".")
    if len(parts) < 2:
        die(f"Invalid ModulePath format: {module_path}. "
            f"Expected: Type.Name.Module, Type.Name.Form.FormName or CommonModule.Name")
    obj_type, obj_name = parts[0], parts[1]
    if obj_type not in TYPE_DIR_MAP:
        die(f"Unknown object type: {obj_type}")
    dir_name = TYPE_DIR_MAP[obj_type]
    if obj_type == "CommonModule":
        return [dir_name, obj_name, "Ext", "Module.bsl"]
    if len(parts) >= 4 and parts[2] == "Form":
        return [dir_name, obj_name, "Forms", parts[3], "Ext", "Form", "Module.bsl"]
    if len(parts) >= 3:
        module_name = parts[2]
        return [dir_name, obj_name, "Ext",
                MODULE_FILE_MAP.get(module_name, f"{module_name}.bsl")]
    die(f"Invalid ModulePath format: {module_path}")


def get_rel_parts_from_file_path(path):
    """Relative module path segments from a filesystem path to a .bsl, anchored
    on a known type directory (Catalogs / Documents / CommonModules / ...)."""
    segs = [s for s in path.replace("\\", "/").split("/") if s]
    anchors = set(TYPE_DIR_MAP.values())
    for i, seg in enumerate(segs):
        # case-sensitive: 1C type dirs are PascalCase
        if seg in anchors:
            return segs[i:]
    return None


def split_top_level(text, sep=','):
    """Split at a top-level separator, respecting parens and string literals."""
    result, depth, in_str, buf = [], 0, False, []
    for ch in text:
        if in_str:
            buf.append(ch)
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
            continue
        if ch == '(':
            depth += 1
            buf.append(ch)
            continue
        if ch == ')':
            depth -= 1
            buf.append(ch)
            continue
        if ch == sep and depth == 0:
            result.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    result.append("".join(buf))
    return result


def is_context_directive(trimmed):
    return bool(CONTEXT_DIRECTIVE_RE.match(trimmed))


def read_signature(lines, start_idx):
    """Read a method signature from its declaration line.
    Returns (params_text, end_line_idx) or None."""
    depth, in_str, open_found = 0, False, False
    params = []
    for li in range(start_idx, len(lines)):
        line = lines[li]
        for ch in line:
            if in_str:
                if open_found:
                    params.append(ch)
                if ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                if open_found:
                    params.append(ch)
                continue
            if ch == '(':
                depth += 1
                if not open_found:
                    open_found = True
                else:
                    params.append(ch)
                continue
            if ch == ')':
                depth -= 1
                if depth == 0:
                    return "".join(params), li
                params.append(ch)
                continue
            if open_found:
                params.append(ch)
        if open_found and depth >= 1:
            params.append("\r\n")
    return None


def get_effective_condition(frame):
    """Effective condition of the current branch of an #Если frame."""
    conds = frame["Conds"]
    if frame["InElse"]:
        return " И ".join(f"НЕ ({c})" for c in conds)
    if len(conds) == 1:
        return conds[0]
    parts = [f"НЕ ({c})" for c in conds[:-1]] + [conds[-1]]
    return " И ".join(parts)


def get_enclosing_chain(lines, target_idx):
    """Enclosing wrapper chain (regions + preprocessor) at a target line,
    outer -> inner."""
    stack = []
    for i in range(target_idx):
        t = lines[i].strip()
        m = re.match(r'^#Область\s+(\S+)', t)
        if m:
            stack.append({"Kind": "region", "Name": m.group(1)})
            continue
        if re.match(r'^#КонецОбласти', t):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k]["Kind"] == "region":
                    del stack[k]
                    break
            continue
        m = re.match(r'^#Если\s+(.+?)\s+Тогда', t)
        if m:
            stack.append({"Kind": "if", "Conds": [m.group(1).strip()], "InElse": False})
            continue
        m = re.match(r'^#ИначеЕсли\s+(.+?)\s+Тогда', t)
        if m:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k]["Kind"] == "if":
                    stack[k]["Conds"].append(m.group(1).strip())
                    stack[k]["InElse"] = False
                    break
            continue
        if re.match(r'^#Иначе(\s|$)', t):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k]["Kind"] == "if":
                    stack[k]["InElse"] = True
                    break
            continue
        if re.match(r'^#КонецЕсли', t):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k]["Kind"] == "if":
                    del stack[k]
                    break
    chain = []
    for f in stack:
        if f["Kind"] == "region":
            chain.append({"Kind": "region", "Name": f["Name"]})
        else:
            chain.append({"Kind": "if", "Cond": get_effective_condition(f)})
    return chain


def extract_method(lines, method_name):
    """Extract a method from source .bsl lines; None when not found."""
    decl_re = re.compile(r'^\s*(Асинх\s+)?(Процедура|Функция)\s+('
                         + re.escape(method_name) + r')\s*\(', re.I)
    for i, line in enumerate(lines):
        m = decl_re.match(line)
        if not m:
            continue
        is_async = bool(m.group(1))
        is_function = m.group(2).lower() == "функция"
        canonical = m.group(3)

        sig = read_signature(lines, i)
        if not sig:
            die(f"Не удалось разобрать сигнатуру метода '{method_name}'")
        params_text, sig_end = sig

        param_names = []
        if params_text.strip():
            for seg in split_top_level(params_text):
                s = re.sub(r'^Знач\s+', '', seg.strip())
                mm = re.match(r'^(\w+)', s)
                if mm:
                    param_names.append(mm.group(1))

        end_re = re.compile(r'^\s*КонецФункции\b' if is_function else r'^\s*КонецПроцедуры\b', re.I)
        body_start = sig_end + 1
        body_end = -1
        for j in range(body_start, len(lines)):
            if end_re.match(lines[j]):
                body_end = j
                break
        if body_end < 0:
            die(f"Не найден конец метода '{method_name}'")
        body_lines = lines[body_start:body_end]

        context = ""
        if i >= 1 and is_context_directive(lines[i - 1].strip()):
            context = lines[i - 1].strip()

        return {
            "Canonical": canonical, "IsFunction": is_function, "IsAsync": is_async,
            "ParamsText": params_text, "ParamNames": param_names, "Context": context,
            "BodyLines": body_lines, "Chain": get_enclosing_chain(lines, i),
            "DeclIdx": i, "SigEndIdx": sig_end, "BodyEndIdx": body_end,
        }
    return None


def get_interceptors(lines):
    """Interceptors present in a module (type + method + line)."""
    out = []
    for i, line in enumerate(lines):
        m = re.match(r'^&(Перед|После|ИзменениеИКонтроль|Вместо)\("([^"]+)"\)', line.strip())
        if m:
            out.append({"Type": m.group(1), "Method": m.group(2), "Line": i})
    return out


def get_proc_names(lines):
    names = []
    for line in lines:
        m = re.match(r'^\s*(?:Асинх\s+)?(?:Процедура|Функция)\s+(\w+)\s*\(', line, re.I)
        if m:
            names.append(m.group(1))
    return names


# ============================================================================
# Build interceptor block (without enclosing wrappers)
# ============================================================================

def build_interceptor_core(method, interceptor_type, interceptor_name):
    decorator_ru = DECORATOR_MAP[interceptor_type]
    async_prefix = "Асинх " if method["IsAsync"] else ""
    keyword = "Функция" if method["IsFunction"] else "Процедура"
    end_keyword = "КонецФункции" if method["IsFunction"] else "КонецПроцедуры"

    lines = []
    if method["Context"]:
        lines.append(method["Context"])
    lines.append(f'&{decorator_ru}("{method["Canonical"]}")')
    lines.append(f'{async_prefix}{keyword} {interceptor_name}({method["ParamsText"]})')

    if interceptor_type == "Before":
        lines.append("\t// TODO: код перед вызовом оригинального метода")
    elif interceptor_type == "After":
        lines.append("\t// TODO: код после вызова оригинального метода")
    elif interceptor_type == "Instead":
        joined = ", ".join(method["ParamNames"])
        if method["IsFunction"]:
            lines.append(f"\tРезультат = ПродолжитьВызов({joined});")
            lines.append("\t// TODO: доработать поведение")
            lines.append("\tВозврат Результат;")
        else:
            lines.append(f"\tПродолжитьВызов({joined});")
            lines.append("\t// TODO: доработать поведение")
    elif interceptor_type == "ModificationAndControl":
        lines.extend(method["BodyLines"])

    lines.append(end_keyword)
    return lines


def build_wrapped_block(chain, core):
    """Wrap the core in region / preprocessor lines, with blank-line air around
    each structural boundary. An empty chain returns the core as is."""
    out = []
    for w in chain:
        out.append(f'#Область {w["Name"]}' if w["Kind"] == "region"
                   else f'#Если {w["Cond"]} Тогда')
        out.append("")
    out.extend(core)
    for w in reversed(chain):
        out.append("")
        out.append("#КонецОбласти" if w["Kind"] == "region" else "#КонецЕсли")
    return out


# ============================================================================
# Main
# ============================================================================

def read_lines(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read().split("\n")


def write_text(path, text):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Source-aware method interceptor for 1C extension (CFE)",
        allow_abbrev=False)
    parser.add_argument("-ExtensionPath", required=True)
    parser.add_argument("-ConfigPath", default="")
    # Generation: logical name or path to a .bsl. Optional in -Check/-Actualize.
    parser.add_argument("-ModulePath", default="")
    parser.add_argument("-MethodName", default="")
    parser.add_argument("-InterceptorType", default="",
                        choices=["", "Before", "After", "Instead", "ModificationAndControl"])
    # Batch modes over &ИзменениеИКонтроль of the extension (no generation):
    parser.add_argument("-Check", action="store_true", help="report drift only, no writes")
    parser.add_argument("-Actualize", action="store_true",
                        help="actualize drifted controlled methods")
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    config_path = args.ConfigPath

    # --- Resolve extension path ---
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if os.path.isfile(extension_path):
        extension_path = os.path.dirname(extension_path)
    cfg_file = os.path.join(extension_path, "Configuration.xml")
    if not os.path.isfile(cfg_file):
        die(f"Configuration.xml не найден в расширении: {extension_path}")

    # --- Read NamePrefix ---
    cfg_ns = {"md": "http://v8.1c.ru/8.3/MDClasses"}
    cfg_root = etree.parse(cfg_file).getroot()
    props = cfg_root.xpath("//md:Configuration/md:Properties", namespaces=cfg_ns)
    props_node = props[0] if props else None
    name_prefix = "Расш_"
    ext_name = "Расширение"
    if props_node is not None:
        pn = props_node.xpath("md:NamePrefix", namespaces=cfg_ns)
        if pn and (pn[0].text or "").strip():
            name_prefix = pn[0].text
        en = props_node.xpath("md:Name", namespaces=cfg_ns)
        if en and (en[0].text or "").strip():
            ext_name = en[0].text

    # --- Batch modes: -Check / -Actualize ---
    if args.Check or args.Actualize:
        if args.Check and args.Actualize:
            die("Укажите либо -Check, либо -Actualize, не оба.")
        die("Режимы -Check / -Actualize (ресинк контролируемых методов) в python-порту "
            "пока не реализованы — используйте .ps1 на Windows либо сверяйте вручную.")

    # --- Generation mode ---
    if not args.ModulePath or not args.MethodName or not args.InterceptorType:
        die("Нужны -ModulePath, -MethodName, -InterceptorType (генерация перехватчика). "
            "Для проверки/актуализации контролируемых методов используйте -Check или -Actualize.")

    module_path = args.ModulePath
    method_name = args.MethodName
    interceptor_type = args.InterceptorType

    has_config_path = bool(config_path)
    if has_config_path:
        if not os.path.isabs(config_path):
            config_path = os.path.join(os.getcwd(), config_path)
        if os.path.isfile(config_path):
            config_path = os.path.dirname(config_path)

    is_file_path = bool(re.search(r'[\\/]', module_path)) or module_path.endswith(".bsl")

    if is_file_path:
        mp_abs = module_path if os.path.isabs(module_path) \
            else os.path.join(os.getcwd(), module_path)
        rel_parts = get_rel_parts_from_file_path(module_path)
        if not rel_parts:
            die(f"Не удалось определить объект по пути модуля: {module_path}\n"
                f"(нет распознаваемой типовой папки — Catalogs/Documents/CommonModules/…)")
        ext_bsl = os.path.join(extension_path, *rel_parts)
        if has_config_path:
            src_bsl = os.path.join(config_path, *rel_parts)
        else:
            # a path under the extension itself is not a valid source
            ext_root_abs = os.path.abspath(extension_path).rstrip("\\/")
            if os.path.abspath(mp_abs).lower().startswith(ext_root_abs.lower()):
                die("Путь модуля указывает внутрь расширения, а не на источник. "
                    "Укажите путь к модулю-источнику или -ConfigPath.")
            src_bsl = mp_abs
    else:
        if not has_config_path:
            die("Не указан -ConfigPath. Укажите путь к исходникам конфигурации или "
                "передайте путь к файлу модуля в -ModulePath.")
        if not os.path.isfile(os.path.join(config_path, "Configuration.xml")):
            die(f"Configuration.xml не найден в конфигурации-источнике: {config_path}")
        rel_parts = get_module_rel_path(module_path)
        ext_bsl = os.path.join(extension_path, *rel_parts)
        src_bsl = os.path.join(config_path, *rel_parts)

    if not os.path.isfile(src_bsl):
        die(f"Модуль-источник не найден: {src_bsl}\n(проверьте ModulePath и ConfigPath)")

    # --- Extract the original method ---
    src_lines = read_lines(src_bsl)
    method = extract_method(src_lines, method_name)
    if not method:
        die(f"Метод '{method_name}' не найден в модуле-источнике: {src_bsl}")

    # --- Guard: functions cannot use Before/After ---
    if method["IsFunction"] and interceptor_type in ("Before", "After"):
        die(f"Метод '{method_name}' — функция. Для функций доступны только Instead и "
            f"ModificationAndControl (перехват &Перед/&После к функциям неприменим).")

    decorator_ru = DECORATOR_MAP[interceptor_type]

    # --- Read the existing extension module (if any) ---
    ext_exists = os.path.isfile(ext_bsl)
    ext_lines = read_lines(ext_bsl) if ext_exists else []
    existing_interceptors = get_interceptors(ext_lines) if ext_exists else []
    existing_proc_names = get_proc_names(ext_lines) if ext_exists else []

    # --- Does the same (method, type) already exist? ---
    dup = next((ic for ic in existing_interceptors
                if ic["Type"] == decorator_ru and ic["Method"].lower() == method_name.lower()),
               None)
    if dup:
        if interceptor_type != "ModificationAndControl":
            print(f'[ПРОПУЩЕН] Перехватчик &{decorator_ru}("{method_name}") уже есть в модуле '
                  f'— дубль не создаётся.')
            print(f"     Файл: {ext_bsl}")
            sys.exit(0)
        die(f'&ИзменениеИКонтроль("{method_name}") уже есть в модуле. Ресинк тела '
            f'(перенос правок из обновлённого оригинала) в python-порту пока не реализован '
            f'— используйте .ps1 на Windows.')

    # --- New interceptor: name, block, region-aware placement ---
    candidate = f'{name_prefix}{method["Canonical"]}'
    taken = {n.lower() for n in existing_proc_names}
    interceptor_name = candidate
    if candidate.lower() in taken:
        suffix = "ИзменениеИКонтроль" if interceptor_type == "ModificationAndControl" \
            else decorator_ru
        interceptor_name = f"{candidate}_{suffix}"

    core = build_interceptor_core(method, interceptor_type, interceptor_name)

    # Innermost region of the source chain that already exists in the extension module
    chain = method["Chain"]
    reuse_region_idx, reuse_line_idx = -1, -1
    if ext_exists:
        for c in range(len(chain) - 1, -1, -1):
            if chain[c]["Kind"] == "region":
                rname = chain[c]["Name"]
                rre = re.compile(r'^#Область\s+' + re.escape(rname) + r'\s*$')
                for li, line in enumerate(ext_lines):
                    if rre.match(line.strip()):
                        reuse_region_idx, reuse_line_idx = c, li
                        break
            if reuse_region_idx >= 0:
                break

    if reuse_region_idx >= 0:
        # Insert inside the existing region, before its matching #КонецОбласти.
        # Wrappers inner to the reused region are emitted; outer ones are inherited.
        inner_chain = chain[reuse_region_idx + 1:]
        block = build_wrapped_block(inner_chain, core)

        depth, close_idx = 0, -1
        for li in range(reuse_line_idx, len(ext_lines)):
            t = ext_lines[li].strip()
            if re.match(r'^#Область\s', t):
                depth += 1
            elif re.match(r'^#КонецОбласти', t):
                depth -= 1
                if depth == 0:
                    close_idx = li
                    break
        if close_idx < 0:
            die("Не найден #КонецОбласти для региона (переиспользование)")

        last_content = close_idx - 1
        while last_content >= 0 and ext_lines[last_content].strip() == "":
            last_content -= 1
        out = ext_lines[:last_content + 1] + [""] + block + [""] + ext_lines[close_idx:]
        write_text(ext_bsl, "\r\n".join(out) + "\r\n")
        placement = f"в существующий регион '{chain[reuse_region_idx]['Name']}'"
    else:
        block = build_wrapped_block(chain, core)
        block_text = "\r\n".join(block) + "\r\n"
        os.makedirs(os.path.dirname(ext_bsl), exist_ok=True)
        if ext_exists:
            with open(ext_bsl, encoding="utf-8-sig", errors="replace") as f:
                existing = f.read()
            if not existing.strip():
                # borrowed-but-empty module (e.g. a cfe-borrow form module)
                write_text(ext_bsl, block_text)
                placement = "заполнен модуль"
            else:
                sep = "\r\n" if existing.endswith("\n") else "\r\n\r\n"
                write_text(ext_bsl, existing + sep + block_text)
                placement = "дописан в модуль"
        else:
            write_text(ext_bsl, block_text)
            placement = "создан модуль"

    params_flat = re.sub(r'\s+', ' ', method["ParamsText"])
    print(f'[OK] Перехватчик &{decorator_ru}("{method_name}") — {placement}')
    print(f"     Файл:       {ext_bsl}")
    print(f"     Процедура:  {interceptor_name}({params_flat})")
    if method["Context"]:
        print(f'     Контекст:   {method["Context"]}')
    if chain:
        desc = " > ".join(f'Область:{w["Name"]}' if w["Kind"] == "region" else f'Если:{w["Cond"]}'
                          for w in chain)
        print(f"     Обрамление: {desc}")


if __name__ == "__main__":
    main()
