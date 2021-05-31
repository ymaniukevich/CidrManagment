import os
import sys


FILE_PATH = os.path.abspath(__file__)
PROJECT_PATH = os.path.dirname(FILE_PATH)
sys.path.insert(0, os.path.join(PROJECT_PATH, 'deps'))