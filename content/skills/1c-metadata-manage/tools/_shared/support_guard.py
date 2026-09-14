#!/usr/bin/env python3
# support_guard v1.0 — shared support-state guard for 1c-metadata-manage tools (Python port)
# Mirrors tools/_shared/support-guard.ps1 — see docs/support-manage.md for the full spec.
# Import Assert-EditAllowed (write path) as assert_edit_allowed(), or the read-only
# status line as get_support_status_for_path().
#
# Deviation from the original tools, which resolve the guard policy from .v8-project.json's editingAllowedCheck. Here the policy
# comes from .dev.env's SUPPORT_GUARD instead (legacy SUPPORT_EDIT_POLICY still read) — .dev.env is this project's single
# source of truth for operational parameters (see AGENTS.md / dev-standards-core.md §1).
# .v8-project.json in this project is documentation-only for the guard (no script reads
# it for this purpose — see docs/db-manage.md; it remains in legitimate use as the
# optional multi-base registry for 1c-db-ops / 1c-epf-build / 1c-epf-dump, a separate
# concern). Same directory walk-up algorithm as the original tools (up to 20 levels), same default
# ('deny') when the file or field is absent. Everything else (Ext/ParentConfigurations.bin
# parsing, block/flag semantics) is unchanged from the original tools.
#
# Centralized here (mirrors the .ps1 side, which is also centralized rather than
# duplicated per script) so every 1c-metadata-manage Python tool shares one implementation.
#
# Callers import it via sys.path (mirrors dot-sourcing in the .ps1 counterpart):
#   sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
#   import support_guard

import os
import re
import sys

from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "_common"))
import dev_env  # noqa: E402


def get_root_uuid(xml_path):
    if not os.path.isfile(xml_path):
        return None
    try:
        mx = etree.parse(xml_path).getroot()
        for child in mx:
            if isinstance(child.tag, str) and child.get("uuid"):
                return child.get("uuid")
    except Exception:
        return None
    return None


def find_dev_env(start_dir):
    d = start_dir
    for _ in range(20):
        if not d:
            break
        f = os.path.join(d, ".dev.env")
        if os.path.isfile(f):
            return f
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def get_edit_mode(cfg_dir):
    """Guard policy: deny | warn | off. Default 'deny' when unset.

    Upstream renamed the .dev.env key SUPPORT_EDIT_POLICY -> SUPPORT_GUARD
    (DevEnv.ps1, 2026-08); the old name stays supported so a project that still
    carries it is not silently switched back to 'deny'.
    """
    try:
        for start in (os.getcwd(), cfg_dir):
            if not start:
                continue
            for key in ("SUPPORT_GUARD", "SUPPORT_EDIT_POLICY"):
                val = dev_env.get_value(key, start).strip().lower()
                if val:
                    return val if val in ("deny", "warn", "off") else "deny"
        # No .dev.env, or the key is absent / empty in every candidate -> the
        # documented default. (The .ps1 falls through to .v8-project.json here;
        # in this project that file is documentation-only for the guard.)
        return "deny"
    except Exception:
        return "deny"


def assert_edit_allowed(target_path, require):
    try:
        rp = os.path.abspath(target_path)
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
                    cfg_dir = d
                    bin_path = cand
            if elem_uuid and cfg_dir:
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        if not elem_uuid and cfg_dir:
            elem_uuid = get_root_uuid(os.path.join(cfg_dir, "Configuration.xml"))
        if not bin_path or not os.path.exists(bin_path):
            return
        data = open(bin_path, "rb").read()
        if len(data) <= 32:
            return
        if data[:3] == b"\xef\xbb\xbf":
            data = data[3:]
        text = data.decode("utf-8", "replace")
        h = re.match(r"\{6,(\d+),(\d+),", text)
        if not h:
            return
        g = int(h.group(1))
        k = int(h.group(2))
        if k == 0:
            return
        best = None
        if elem_uuid:
            for m in re.finditer(r"([0-2]),0," + re.escape(elem_uuid.lower()), text):
                f1 = int(m.group(1))
                if best is None or f1 < best:
                    best = f1
        blocked = False
        code = ""
        reason = ""
        if g == 1:
            blocked = True
            code = "capability-off"
            reason = "возможность изменения конфигурации выключена (вся конфигурация read-only)"
        elif require == "removed":
            if best is not None and best != 2:
                blocked = True
                code = "not-removed"
                reason = "объект не снят с поддержки — удаление сломает обновления"
        else:
            if best is not None and best == 0:
                blocked = True
                code = "locked"
                reason = "объект на замке — редактирование сломает обновления"
        if not blocked:
            return
        mode = get_edit_mode(cfg_dir)
        if mode == "off":
            return
        if mode == "warn":
            sys.stderr.write(f"[support-guard] ПРЕДУПРЕЖДЕНИЕ: {reason}. Цель: {rp}\n")
            return
        head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
        cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) — состояние поддержки менять не нужно, обновления вендора сохраняются."
        off_note = "Снять проверку для этой базы: SUPPORT_GUARD=warn|off в .dev.env."
        if code == "capability-off":
            state = f"Состояние: у всей конфигурации выключена возможность изменения (режим read-only «из коробки») — поэтому объект «{rp}» редактировать нельзя."
            fix = (
                "Либо снять защиту явно (навык support-edit, два шага):\n"
                f'  1. support-edit -Path "{cfg_dir}" -Capability on — включить возможность изменения (объекты пока остаются на замке);\n'
                f'  2. support-edit -Path "{rp}" -Set editable — открыть этот объект для редактирования.\n'
                "  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
            )
        elif code == "not-removed":
            state = f"Состояние: объект «{rp}» на поддержке (не снят с поддержки) — его удаление разорвёт обновления вендора."
            fix = (
                "Либо сначала снять объект с поддержки, затем удалять:\n"
                f'  support-edit -Path "{rp}" -Set off-support — объект уходит из-под обновлений, после этого удаление безопасно.'
            )
        else:
            state = f"Состояние: объект «{rp}» на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
            fix = (
                "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):\n"
                f'  support-edit -Path "{rp}" -Set editable — редактировать и дальше получать обновления вендора (возможны конфликты слияния);\n'
                f'  support-edit -Path "{rp}" -Set off-support — снять с поддержки: обновления по объекту больше не приходят.'
            )
        sys.stderr.write(head + "\n" + state + "\n" + cfe + "\n" + fix + "\n" + off_note + "\n")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        return


def get_support_status_for_path(target_path):
    try:
        rp = os.path.abspath(target_path)
        elem_uuid = get_root_uuid(rp)
        bin_path = None
        d = os.path.dirname(rp)
        for _ in range(12):
            if not d:
                break
            if not elem_uuid:
                elem_uuid = get_root_uuid(d + ".xml")
            if not bin_path:
                cand = os.path.join(d, "Ext", "ParentConfigurations.bin")
                if os.path.exists(cand) or os.path.exists(os.path.join(d, "Configuration.xml")):
                    bin_path = cand
            if elem_uuid and bin_path:
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        if not bin_path or not os.path.exists(bin_path):
            return "не на поддержке"
        data = open(bin_path, "rb").read()
        if len(data) <= 32:
            return "снято с поддержки (правки свободны)"
        if data[:3] == b"\xef\xbb\xbf":
            data = data[3:]
        text = data.decode("utf-8", "replace")
        h = re.match(r"\{6,(\d+),(\d+),", text)
        if not h:
            return "не на поддержке"
        g = int(h.group(1))
        k = int(h.group(2))
        if k == 0:
            return "снято с поддержки (правки свободны)"
        if g == 1:
            return "конфигурация read-only (возможность изменения выключена) — правки невозможны без включения"
        if not elem_uuid:
            return "не на поддержке"
        best = None
        for m in re.finditer(r"([0-2]),0," + re.escape(elem_uuid.lower()), text):
            f1 = int(m.group(1))
            if best is None or f1 < best:
                best = f1
        if best is None:
            return "не на поддержке"
        return {
            0: "на замке — прямая правка сломает обновления; дорабатывай через cfe-* либо включи редактирование объекта",
            1: "редактируется с сохранением поддержки",
            2: "снято с поддержки (правки свободны)",
        }.get(best, "не на поддержке")
    except Exception:
        return "не на поддержке"
