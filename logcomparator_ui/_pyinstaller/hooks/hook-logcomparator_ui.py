from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('logcomparator_ui')

# Keep Help > README identical to the project guide.
datas.append((str(Path(__file__).resolve().parents[3] / 'README.md'), '.'))

datas.append((str(Path(__file__).resolve().parents[3] / 'Log_Comparator_Web_Interface_Rectangles.drawio.png'), '.'))
