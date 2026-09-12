import os
import sys

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)
