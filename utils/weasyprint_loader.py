import os
import sys

def configure_weasyprint():
    if sys.platform == 'win32':
        gtk_paths = [
            r'C:\Program Files\GTK3-Runtime Win64\bin',
            r'C:\Program Files (x86)\GTK3-Runtime Win64\bin',
            r'C:\gtk\bin',
        ]

        for path in gtk_paths:
            if os.path.exists(path):
                os.add_dll_directory(path)
                os.environ['PATH'] = path + os.pathsep + os.environ['PATH']
                return True

        return False

    return True  # Linux já funciona
