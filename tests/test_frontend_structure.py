"""Structure checks for the page scripts that were split / moved out of templates.

There are no JavaScript unit tests in this project, and a split script fails in the browser
(ReferenceError, or a function silently missing), not in Python. These checks catch the
mistakes a split can introduce without needing a browser:
- the template loads every part, in an order where the core file comes first
- every inline onclick/onchange handler name is a function defined by one of the parts
- no function or top-level variable is defined twice (which would make load order matter)
- the parts parse as JavaScript, also when loaded together (node, when installed)
"""
import glob
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
JS = os.path.join(ROOT, "static", "js")
INVENTORY_PARTS = ["inventory.js", "inventory-selects.js", "inventory-add.js", "inventory-qr.js", "inventory-scan.js"]


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def _top_level_functions(src):
    return re.findall(r"^(?:async\s+)?function\s+([A-Za-z0-9_$]+)", src, re.M)


def _top_level_variables(src):
    return re.findall(r"^(?:let|const|var)\s+([A-Za-z0-9_$]+)", src, re.M)


def test_inventory_template_loads_every_part_core_first():
    tpl = _read("templates", "inventory.html")
    srcs = re.findall(r"filename='js/(inventory[a-z-]*\.js)'", tpl)
    assert srcs == INVENTORY_PARTS


def test_no_inventory_file_is_missing_or_unlisted():
    on_disk = sorted(os.path.basename(p) for p in glob.glob(os.path.join(JS, "inventory*.js")))
    assert on_disk == sorted(INVENTORY_PARTS)


def test_every_inventory_handler_is_defined_by_some_part():
    parts = {f: _read("static", "js", f) for f in INVENTORY_PARTS}
    defined = {n for src in parts.values() for n in _top_level_functions(src)}
    used = set()
    for text in [_read("templates", "inventory.html")] + list(parts.values()):
        used |= set(re.findall(r'on(?:click|change|input|keydown|keyup)="\s*([A-Za-z_][A-Za-z0-9_]*)\(', text))
    assert used, "handler scan found nothing - the pattern is broken"
    assert not (used - defined), sorted(used - defined)


def test_inventory_parts_do_not_define_anything_twice():
    funcs, variables = [], []
    for f in INVENTORY_PARTS:
        src = _read("static", "js", f)
        funcs += _top_level_functions(src)
        variables += _top_level_variables(src)
    assert len(funcs) == len(set(funcs)), sorted({n for n in funcs if funcs.count(n) > 1})
    assert len(variables) == len(set(variables)), sorted({n for n in variables if variables.count(n) > 1})
    assert len(funcs) > 100                                  # the page's ~105 functions are all still there


def test_inventory_shared_state_lives_in_the_core_file():
    core = _read("static", "js", "inventory.js")
    for name in ("allItems", "selectMode", "selectedIds", "SECTIONS"):
        assert name in _top_level_variables(core)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_inventory_parts_parse_alone_and_together(tmp_path):
    for f in INVENTORY_PARTS:
        done = subprocess.run(["node", "--check", os.path.join(JS, f)], capture_output=True, text=True)
        assert done.returncode == 0, (f, done.stderr)
    combined = tmp_path / "all.js"
    combined.write_text("\n".join(_read("static", "js", f) for f in INVENTORY_PARTS), encoding="utf-8")
    done = subprocess.run(["node", "--check", str(combined)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr                 # catches duplicate let/const across parts


# ---------------------------------------------------------------------------
# Bill detail: the script is a static file, not inline
# ---------------------------------------------------------------------------
def test_bill_detail_template_has_no_inline_script_body():
    tpl = _read("templates", "bill_detail.html")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", tpl, re.S)
    assert blocks and all(b.strip() == "" for b in blocks), "inline script code crept back into the template"
    assert "js/bill-detail.js" in tpl
    assert 'id="bill-detail-root" data-bill-id="{{ bill_id }}"' in tpl


def test_bill_detail_script_reads_the_id_from_the_page_and_has_no_template_syntax():
    js = _read("static", "js", "bill-detail.js")
    assert "document.getElementById('bill-detail-root').dataset.billId" in js
    assert "{{" not in js and "{%" not in js
    assert js.count("BILL_ID") >= 4


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_bill_detail_script_parses():
    done = subprocess.run(["node", "--check", os.path.join(JS, "bill-detail.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_no_static_script_contains_template_syntax():
    for path in glob.glob(os.path.join(JS, "*.js")):
        text = open(path, encoding="utf-8-sig").read()
        assert "{%" not in text, os.path.basename(path)
