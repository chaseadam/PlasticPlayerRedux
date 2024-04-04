import tidalapi
import pickle
import requests
from PIL import Image, ImageDraw
import csv

# NXP CSV format "Text",<value>,,,,,
fields = ["Type","Content","URI type","Description","Interaction counter","UID mirror","Interaction counter mirror"]
dbfile = open('examplePickle', 'rb')
creds = pickle.load(dbfile)
session = tidalapi.Session()
print(session.load_oauth_session(*creds))

#from pathlib import Path
#session_file1 = Path("tidal-session-oauth.json")
## Load session from file; create a new OAuth session if necessary
#session.login_session_file(session_file1)

user = session.user

tags = []

#image sizes [80, 160, 320, 640, 1280]
# library default 320
image_size = 640
# 300 DPI with 0.5" margins
expected_size_collage = (3000, 2250)
expected_size_image = (640, 640)
collage = Image.new("RGBA", expected_size_collage, color=(255,255,255,255))
collages = []

# https://danyelkoca.com/en/blog/make-photo-collage-with-python
img_count = 0
h = 0
w = 0
def addImage(imageObj):
    global w,h
    global img_count
    global collage
    global collages
    next_image = False
    image = Image.open(requests.get(imageObj(image_size), stream=True).raw)
        # Get the original image width and height
    image_width = image.size[0]
    image_height = image.size[1]

    # Get how the width and height should be
    width_factor = image_width / expected_size_image[0]
    height_factor = image_height / expected_size_image[1]

    # If width and height factors are same, no cropping is needed
    # If not, we need to crop image to the same ratio as expected_size_image
    if width_factor != height_factor:
        # Get the limiting factor
        factor = min(width_factor, height_factor)

        # Calculate the resulting image width and height
        expected_width = round(factor * expected_size_image[0])
        expected_height = round(factor * expected_size_image[1])

        # Get minx, miny, maxx, and maxy coordinates of new image
        start_width = round((image_width - expected_width) / 2)
        start_height = round((image_height - expected_height) / 2)
        end_width = expected_width + round((image_width - expected_width) / 2)
        end_height = expected_height + round((image_height - expected_height) / 2)

        # Crop the image
        image = image.crop((start_width, start_height, end_width, end_height))

    # Once the image is cropped, resize the image
    # Image should have the aspect ratio as the expected_size_image so resize won't disturb the image
    image = image.resize(expected_size_image)

    # Copy image to collage canvas
    collage.paste(image, (w, h))

    w = range(w, expected_size_collage[0], expected_size_image[0])
    next_line = False
    if len(w) > 1:
        w = w[1] + 10
        # check if there is enough room for expected image size
        if expected_size_collage[0] - w <= expected_size_image[0]:
            w = 0
            next_line = True
    # not sure when we would hit this?
    else:
        w = 0
        next_line = True
    if next_line:
        h = range(h, expected_size_collage[1], expected_size_image[1])
        if len(h) > 1:
            h = h[1] + 10
            if expected_size_collage[1] - h <= expected_size_image[1]:
                h = 0
                next_image = True
        else:
             h = 0
             next_image = True
    if next_image:
        collages.append(collage)
        collage = Image.new("RGBA", expected_size_collage, color=(255,255,255,255))
        next_image = False
        # shouldn't be necessary?
        w = 0
        h = 0
    
    img_count += 1

def printItem(name, isrc, uri, artist):
    tags.append({"Type":"Text", "Content":uri})
    print(f"{name},{isrc},{uri},{artist}")

#for track in user.favorites.tracks():
#    name = track.name
#    uri = f"tidal://track:{track.id}"
#    artist = track.artist.name
#    isrc = track.isrc
#    image = track.album.image
#    printItem(name, isrc, uri, artist)
#    # TODO, add track overlay text
#    addImage(image)

#for album in user.favorites.albums():
#    name = album.name
#    uri = f"tidal://album:{album.id}"
#    artist = album.artist.name
#    # no ISRC?
#    isrc = ""
#    image = album.image
#    printItem(name, isrc, uri, artist)
#    addImage(image)
#
for playlist in user.favorites.playlists():
    name = playlist.name
    uri = f"tidal://playlist:{playlist.id}"
    artist = ""
    isrc = ""
    image = playlist.image
    printItem(name, isrc, uri, artist)
    addImage(image)

# Save collage
collage.save("collage.png")
#TODO iterate through collages
for i, collage in enumerate(collages):
    collage.save(f"{i}.png")

with open("tags.csv", 'w') as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fields)
    writer.writeheader()
    writer.writerows(tags)
