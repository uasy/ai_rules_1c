#!/usr/bin/env python3
# support-edit v1.0 — Toggle 1C configuration support state (Ext/ParentConfigurations.bin)
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills

import argparse
import os
import re
import sys

from lxml import etree


def err(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def get_root_uuid(xml_path):
    """uuid of the first metadata element in an .xml file (or None)."""
    if not os.path.isfile(xml_path):
        return None
    try:
        root = etree.parse(xml_path).getroot()
        for el in root:
            if isinstance(el.tag, str):
                u = el.get("uuid")
                return u or None
    except Exception:
        pass
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Toggle 1C configuration support state (Ext/ParentConfigurations.bin)",
        allow_abbrev=False)
    parser.add_argument("-TargetPath", "-Path", dest="TargetPath", required=True)
    parser.add_argument("-Set", dest="Set", default="",
                        choices=["", "editable", "off-support", "locked"])
    parser.add_argument("-Capability", dest="Capability", default="", choices=["", "on", "off"])
    args = parser.parse_args()

    if (not args.Set and not args.Capability) or (args.Set and args.Capability):
        err("Укажите ровно одно: -Set editable|off-support|locked  ЛИБО  -Capability on|off")

    target_path = args.TargetPath
    if not os.path.exists(target_path):
        err(f"Путь не найден: {target_path}")
    rp = os.path.abspath(target_path)

    # --- Resolve target uuid + config root + bin (walk-up, same as support-guard) ---
    elem_uuid = get_root_uuid(rp)
    cfg_dir = None
    bin_path = None
    d = rp if os.path.isdir(rp) else os.path.dirname(rp)
    for _ in range(12):
        if not d:
            break
        if not elem_uuid:
            elem_uuid = get_root_uuid(d + ".xml")
        if not cfg_dir:
            cand = os.path.join(d, "Ext", "ParentConfigurations.bin")
            if os.path.exists(cand) or os.path.exists(os.path.join(d, "Configuration.xml")):
                cfg_dir, bin_path = d, cand
        if elem_uuid and cfg_dir:
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if not elem_uuid and cfg_dir:
        elem_uuid = get_root_uuid(os.path.join(cfg_dir, "Configuration.xml"))

    if not cfg_dir:
        err(f"Не найден корень конфигурации (Configuration.xml) над путём: {rp}")
    if not os.path.isfile(bin_path):
        print("Конфигурация не на поддержке (Ext/ParentConfigurations.bin отсутствует) — "
              "переключать нечего.")
        sys.exit(0)

    # --- Read bin (UTF-8 text with BOM) ---
    with open(bin_path, "rb") as f:
        data = f.read()
    if len(data) <= 32:
        print("Поддержка снята полностью (пустой ParentConfigurations.bin) — переключать нечего.")
        sys.exit(0)
    body = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
    text = body.decode("utf-8", errors="replace")

    hm = re.match(r'^\{6,(\d+),(\d+),', text)
    if not hm:
        err("Неизвестный формат ParentConfigurations.bin")
    g = int(hm.group(1))

    def save_bin(txt):
        with open(bin_path, "wb") as fh:
            fh.write(b"\xef\xbb\xbf")
            fh.write(txt.encode("utf-8"))

    # === Capability (global G) ===
    if args.Capability:
        target = "0" if args.Capability == "on" else "1"
        if g == int(target):
            word = "включена" if args.Capability == "on" else "выключена"
            print(f"Возможность изменения конфигурации уже {word} — изменений нет.")
            sys.exit(0)
        # G + X (per block) + bulk f1
        text = re.sub(r'^(\{6,)\d+(,)', r'\g<1>' + target + r'\g<2>', text)
        text = re.sub(r'([0-9a-f-]{36}),\d+,([0-9a-f-]{36})', r'\g<1>,' + target + r',\g<2>', text)
        text = re.sub(r'[0-2],0,([0-9a-f-]{36})', target + r',0,\g<1>', text)
        save_bin(text)
        if args.Capability == "on":
            print("Возможность изменения конфигурации ВКЛЮЧЕНА. Все объекты поставщика — на замке.")
            print("Включайте редактирование точечно: support-edit -Path <объект> -Set editable")
        else:
            print("Возможность изменения конфигурации ВЫКЛЮЧЕНА. Вся конфигурация стала "
                  "read-only; пообъектные правила сброшены.")
        sys.exit(0)

    # === Per-object -Set ===
    if g == 1:
        err(f"Возможность изменения конфигурации выключена — пообъектное переключение "
            f"недоступно.\n  Сначала: support-edit -Path {target_path} -Capability on")
    if not elem_uuid:
        err(f"Не удалось определить объект по пути: {rp}")

    u = re.escape(elem_uuid.lower())
    found = re.findall(r'([0-2]),0,' + u, text)
    if not found:
        print(f"Объект (uuid {elem_uuid}) не на поддержке (своё добавление или не найден "
              f"в bin) — переключать нечего.")
        sys.exit(0)

    new_f1 = {"editable": "1", "off-support": "2", "locked": "0"}[args.Set]
    # The replacement carries no group refs — the uuid is fixed, only f1 is rewritten.
    text = re.sub(r'([0-2]),0,' + u, f"{new_f1},0,{elem_uuid.lower()}", text)
    save_bin(text)
    state = {
        "editable": "редактируется с сохранением поддержки (объект продолжит получать "
                    "обновления вендора — возможны конфликты при обновлении)",
        "off-support": "снят с поддержки (обновления вендора по этому объекту прекращаются)",
        "locked": "на замке (правка запрещена)",
    }[args.Set]
    print(f"Объект uuid {elem_uuid} → {state}.")
    print(f"Записей в bin изменено: {len(found)}. Цель: {rp}")
    sys.exit(0)


if __name__ == "__main__":
    main()
