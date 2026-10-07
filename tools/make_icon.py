"""Draw the JarvisAI icon from the HUD colors."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icon.ico"


def frame(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (6, 16, 24, 255))
    draw = ImageDraw.Draw(image)
    pad = size * 0.08
    box = (pad, pad, size - pad, size - pad)
    draw.ellipse(box, outline=(122, 239, 255, 255), width=max(2, size // 28))
    inner = size * 0.18
    draw.ellipse(
        (pad + inner, pad + inner, size - pad - inner, size - pad - inner),
        outline=(226, 177, 90, 255),
        width=max(2, size // 40),
    )
    core = size * 0.34
    draw.ellipse(
        (core, core, size - core, size - core),
        fill=(18, 70, 90, 255),
        outline=(180, 245, 255, 255),
        width=max(1, size // 64),
    )
    return image


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image = frame(256)
    image.save(
        OUT,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
