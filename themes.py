from enum import Enum
from dataclasses import dataclass
from typing import Tuple

@dataclass
class Theme:
    name: str
    primary_color: Tuple[int, int, int]  # RGB
    secondary_color: Tuple[int, int, int]
    text_color: Tuple[int, int, int]
    background_color: Tuple[int, int, int]
    opacity: int  # 0-255

class Themes(Enum):
    DEFAULT = Theme(
        "Default Green",
        (0, 255, 0),      # Primary: Green
        (255, 255, 255),  # Secondary: White
        (0, 255, 0),      # Text: Green
        (0, 0, 0),        # Background: Black
        180              # Opacity
    )
    
    MILITARY = Theme(
        "Military",
        (173, 255, 47),   # Primary: GreenYellow
        (255, 140, 0),    # Secondary: Orange
        (173, 255, 47),   # Text: GreenYellow
        (0, 0, 0),        # Background: Black
        200              # Opacity
    )
    
    MODERN = Theme(
        "Modern Blue",
        (0, 191, 255),    # Primary: DeepSkyBlue
        (255, 255, 255),  # Secondary: White
        (0, 191, 255),    # Text: DeepSkyBlue
        (0, 0, 0),        # Background: Black
        160              # Opacity
    )
    
    NIGHT = Theme(
        "Night Vision",
        (0, 255, 0),      # Primary: Green
        (173, 255, 47),   # Secondary: GreenYellow
        (0, 255, 0),      # Text: Green
        (0, 0, 0),        # Background: Black
        120              # Opacity
    )
