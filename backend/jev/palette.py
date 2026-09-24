"""Palette, letter legend, and default scene for Jev pixel generation."""

PALETTE = {
    "white": (255, 255, 255),
    "red": (220, 40, 40),
    "blue": (40, 80, 220),
    "green": (40, 170, 70),
    "yellow": (240, 210, 40),
    "black": (20, 20, 20),
}

LETTER = {
    "white": ".",
    "red": "r",
    "blue": "b",
    "green": "g",
    "yellow": "y",
    "black": "k",
}

DEFAULT_SCENE = (
    "White background. A yellow sun: filled circle centred at (0.78, 0.22) with radius 0.14. "
    "A green hill: everything below the line y = 0.75. "
    "A red house: filled square from x=0.20 to x=0.50 and y=0.45 to y=0.75. "
    "A blue door: filled rectangle from x=0.31 to x=0.39 and y=0.60 to y=0.75. "
    "A black outline 0.02 thick around the house square."
)
