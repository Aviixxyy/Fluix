"""Regenerate the Fluix icon files (fluix.png / fluix.ico) for a theme.

Usage:
    python make_icon.py            # active theme (settings.json) or default
    python make_icon.py slate     # a specific theme
"""

import sys

import themes


def main():
    theme = themes.active()
    if len(sys.argv) > 1:
        theme = sys.argv[1]
    if theme not in themes.THEMES:
        print("[!] Unknown theme '{}'. Options: {}".format(theme, ", ".join(themes.THEMES)))
        return 1
    m = themes.apply(theme)
    print("Saved fluix.png / fluix.ico for theme '{}' ({}).".format(theme, m["title"]))


if __name__ == "__main__":
    main()
