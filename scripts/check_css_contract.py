"""Check that every CSS class the JS/HTML uses is actually defined somewhere."""
import re
from pathlib import Path

css = Path("static/css/style.css").read_text(encoding="utf-8")
html = Path("static/index.html").read_text(encoding="utf-8")
js = Path("static/js/app.js").read_text(encoding="utf-8")

css_classes = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
html_classes = set()
for m in re.findall(r'class="([^"]+)"', html):
    html_classes.update(m.split())

# classes the JS assigns or queries
js_classes = set()
for m in re.findall(r"""className\s*=\s*['"]([^'"]+)['"]""", js):
    js_classes.update(m.split())
for m in re.findall(r"""class="([^"]*\$\{[^"]*)""", js):   # template literals
    # Drop ${...} interpolations first: `${c.id === activeId ? 'active' : ''}`
    # contains identifiers that look like class names but are JS variables.
    stripped = re.sub(r"\$\{[^}]*\}", " ", m)
    js_classes.update(re.findall(r"[A-Za-z][\w-]*", stripped))
for m in re.findall(r"""\$\$?\(['"]\.([\w-]+)""", js):
    js_classes.add(m)

used = html_classes | js_classes
# Tailwind utilities are resolved at runtime by the CDN, not by style.css.
tw_prefixes = ("text-", "bg-", "border", "p-", "m-", "mt-", "mb-", "ml-", "mr-",
               "w-", "h-", "flex", "grid", "gap-", "rounded", "shadow", "font-",
               "truncate", "hidden", "block", "items-", "justify-", "space-",
               "whitespace-", "overflow-", "max-", "min-", "absolute", "relative",
               "inset-", "top-", "left-", "right-", "bottom-", "resize-",
               "transition", "hover:", "focus-", "sm:", "md:", "lg-", "col-",
               "uppercase", "leading-", "tracking-", "opacity-", "cursor-",
               "from-", "via-", "to-", "space-x", "sr-only", "uppercase-")
tailwind = {c for c in used if c.startswith(tw_prefixes)}

missing = sorted(c for c in used
                 if c not in css_classes and c not in html_classes
                 and c not in tailwind)

print(f"classes used      : {len(used)}")
print(f"defined in css    : {len(css_classes)}")
print(f"resolved by tailwind: {len(tailwind)}")
print(f"UNRESOLVED        : {len(missing)}")
for c in missing:
    print(f"  MISSING . {c}")
print("\nOK — every class resolves" if not missing else "\nFIX the classes above")
