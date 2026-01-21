import sys
import os

# Add Source directory to path
sys.path.append(os.path.join(os.getcwd(), 'Source'))

try:
    from modern_theme import get_stylesheet
    style_light = get_stylesheet("light")
    style_dark = get_stylesheet("dark")
    print("Success: get_stylesheet executed without errors.")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)