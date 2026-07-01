import os
import runpy

# Hugging Face Spaces and Cloud Platform root entrypoint
# This redirects execution directly to our main Streamlit app in scripts/app.py
if __name__ == "__main__":
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "app.py")
    runpy.run_path(script_path, run_name="__main__")
