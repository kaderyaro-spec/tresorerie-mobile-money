from PIL import Image

src = Image.open("static/logo.png").convert("RGB")
# Couleur de fond = pixel du coin haut-gauche (fond réel du logo).
bg = src.getpixel((2, 2))

def make(size, safe=0.82):
    canvas = Image.new("RGB", (size, size), bg)
    inner = int(size * safe)                     # zone de sécurité (icône ronde)
    logo = src.copy()
    logo.thumbnail((inner, inner), Image.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.paste(logo, (x, y))
    return canvas

make(512).save("static/icon-512.png")
make(192).save("static/icon-192.png")
print("Icones generees. Fond detecte:", bg)
