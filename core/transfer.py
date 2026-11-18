import re
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import zipfile
import csv
import queue
import sys
import shutil
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.error
import urllib.parse

from .constants import *

def authorization_ok(typed, own_confirmed, phrase=SEND_PHRASE):
    """Autorización explícita: casilla de propiedad marcada Y frase exacta escrita."""
    return bool(own_confirmed) and (typed or "").strip() == phrase

