"""The image check shared by the Codex preflight and the Claude precheck.

Both engines see the same kind of image: the policy camera size, split into a
left and a right half of two different colours from a fixed list. The colours
are random, so a fixed guess fails. Some models misread much smaller images
(gpt-6-luna read a 256x128 red/blue image as all blue), so the image keeps the
size of a real observation.
"""
import hashlib
import secrets

VERSION = 'two-halves-896x560-v1'
SIZE = (896, 560)
COLORS = {'red': (220, 35, 35), 'green': (37, 201, 113), 'blue': (35, 60, 220), 'yellow': (230, 210, 30)}
PROMPT = ('The image has two halves, each one solid color: red, green, blue or yellow. '
          'Name the color of the left half and of the right half.')


def choose():
    """Two different colours, left then right."""
    return tuple(secrets.SystemRandom().sample(sorted(COLORS), 2))


def write(path, left, right):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', SIZE, COLORS[left])
    ImageDraw.Draw(image).rectangle((SIZE[0]//2, 0, SIZE[0]-1, SIZE[1]-1), fill=COLORS[right])
    image.save(path)
    return {'version': VERSION, 'left': left, 'right': right, 'colors': sorted(COLORS), 'prompt': PROMPT,
            'width': SIZE[0], 'height': SIZE[1], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def answer(probe):
    """The expected one-line text answer: the two colour names, left then right."""
    return probe['left']+' '+probe['right']


def normalize(text):
    return ' '.join((text or '').lower().replace(',', ' ').split())
