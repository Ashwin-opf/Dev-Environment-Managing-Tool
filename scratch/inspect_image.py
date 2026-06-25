import os
from PIL import Image

path = "/home/rooster/.gemini/antigravity/brain/d9da8558-37d4-4065-8f87-afaafe5b264b/artifacts/user_screen.png"
if os.path.exists(path):
    img = Image.open(path)
    print("Dimensions:", img.size)
    # Let's crop the sidebar area (e.g. left 300px) and save it
    sidebar = img.crop((0, 0, 300, 1080))
    sidebar.save("/home/rooster/Desktop/PC Doc/scratch/crop_sidebar.png")
    print("Sidebar cropped and saved")
    
    # Crop topbar area
    topbar = img.crop((300, 0, 1920, 150))
    topbar.save("/home/rooster/Desktop/PC Doc/scratch/crop_topbar.png")
    print("Topbar cropped and saved")
    
    # Crop central area
    center = img.crop((300, 150, 1920, 1080))
    center.save("/home/rooster/Desktop/PC Doc/scratch/crop_center.png")
    print("Center cropped and saved")
else:
    print("File not found")
