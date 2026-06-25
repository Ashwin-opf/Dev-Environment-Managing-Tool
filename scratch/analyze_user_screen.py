import os
from PIL import Image

path = "/home/rooster/.gemini/antigravity/brain/d9da8558-37d4-4065-8f87-afaafe5b264b/artifacts/user_screen.png"
if os.path.exists(path):
    img = Image.open(path)
    print("Format:", img.format)
    print("Size:", img.size)
    print("Mode:", img.mode)
else:
    print("File not found")
