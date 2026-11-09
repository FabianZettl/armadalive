import os, re, unittest

QML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "armadalive", "qml", "Theme.qml")
KEYS = ("bg", "card", "circle", "border", "text", "muted", "accent")


def themes():
    with open(QML) as f:
        src = f.read()
    groups = re.findall(r'\{ id: "(\w+)", name: "[^"]+"[^}]*\}', src)
    found = {}
    block = src[src.index("readonly property var themes"):]
    block = block[:block.index("\n    })")]
    for m in re.finditer(r"^        (\w+):\s*\{(.*)\}[,]?$", block, re.M):
        body = m.group(2)
        found[m.group(1)] = dict(re.findall(r'(\w+): "([^"]*)"', body))
    return groups, found


def luminance(h):
    r, g, b = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Themes(unittest.TestCase):
    def test_every_theme_has_all_colours_and_a_known_group(self):
        groups, found = themes()
        self.assertGreater(len(found), 40)
        for key, t in found.items():
            for k in KEYS:
                self.assertRegex(t.get(k, ""), r"^#[0-9a-fA-F]{6}$", f"{key}.{k}")
            self.assertIn(t.get("group", groups[0]), groups, key)

    def test_text_can_be_read_on_the_background_and_on_cards(self):
        _, found = themes()
        for key, t in found.items():
            if key == "follow":      # its palette is made from the game's artwork at run time
                continue
            self.assertGreaterEqual(contrast(t["text"], t["bg"]), 3.0, f"{key}: text on background")
            self.assertGreaterEqual(contrast(t["text"], t["card"]), 3.0, f"{key}: text on card")


if __name__ == "__main__":
    unittest.main()


class Styles(unittest.TestCase):
    def test_styles_only_name_known_themes_and_values(self):
        with open(QML) as f:
            src = f.read()
        _, found = themes()
        block = src[src.index("readonly property var styles"):]
        block = block[:block.index("\n    })")]
        entries = re.findall(r"(\w+):\s*\{ ([^}]*) \}", block)
        self.assertGreater(len(entries), 40)
        for key, body in entries:
            self.assertIn(key, found, f"style for unknown theme {key}")
            d = dict(re.findall(r'(\w+): "?([\w]+)"?', body))
            self.assertIn(d.get("shape", "round"), ("round", "pill", "soft", "square", "cut"), key)
            self.assertIn(d.get("pattern", "none"), ("none", "dots", "grid", "scan", "diag", "checker", "stars"), key)
            self.assertIn(d.get("motion", "smooth"), ("smooth", "snappy", "bouncy", "gentle", "steps"), key)
            self.assertIn(d.get("font", ""), ("", "mono", "serif", "pixel", "term", "tech", "round", "fantasy", "hand"), key)
            self.assertIn(d.get("icons", "normal"), ("thin", "normal", "bold", "block", "line", "duo"), key)
