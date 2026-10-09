- When you change the code and at the end update the Readme.md file
- Don't install linux packages
- After every change, rebuild the executable before completing the task.
- Run from the project root using the project virtual environment:
  .\.venv\Scripts\python.exe update_build_info.py
  .\.venv\Scripts\pyinstaller.exe --onefile --name LogComparator --add-data "build.json;." main.py
- Always publish the latest executable at <project>/dist/LogComparator.exe, inside the project. The Desktop shortcut must keep pointing to this fixed path.
