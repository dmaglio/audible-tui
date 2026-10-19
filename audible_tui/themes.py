"""Temi Catppuccin: Latte (chiaro) e Macchiato (scuro)."""
from textual.theme import Theme

# nome: (dark, base, mantle, surface0, text, blue, mauve, red, green, yellow, peach, lavender, pink)
PALETTES = {
    "latte": (False, "#eff1f5", "#e6e9ef", "#ccd0da", "#4c4f69", "#1e66f5", "#8839ef",
              "#d20f39", "#40a02b", "#df8e1d", "#fe640b", "#7287fd", "#ea76cb"),
    "macchiato": (True, "#24273a", "#1e2030", "#363a4f", "#cad3f5", "#8aadf4", "#c6a0f6",
                  "#ed8796", "#a6da95", "#eed49f", "#f5a97f", "#b7bdf8", "#f5bde6"),
}


def build(name: str) -> Theme:
    dark, base, mantle, s0, text, blue, mauve, red, green, yellow, peach, lav, pink = PALETTES[name]
    return Theme(
        name=f"catppuccin-{name}", primary=blue, secondary=mauve, accent=pink,
        foreground=text, background=base, surface=mantle, panel=s0,
        success=green, warning=yellow, error=red, dark=dark,
        variables={"footer-key-foreground": peach, "block-cursor-foreground": base,
                   "block-cursor-background": blue, "input-selection-background": f"{lav} 35%"},
    )


def all_themes() -> list[Theme]:
    return [build(n) for n in PALETTES]
