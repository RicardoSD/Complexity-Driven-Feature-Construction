import numpy as np
import subprocess
from pathlib import Path
import pandas as pd
from random import randrange
home = str(Path.home())
import os

path = Path(home + '/Finding-Fair-Representations-Through-Feature-Construction/data/tmp')
path.mkdir(parents=True, exist_ok=True)
tmp_folder = home + '/Finding-Fair-Representations-Through-Feature-Construction/data/tmp'
rscript_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/d_separation.R'

if Path(rscript_path).is_file():
    pass
else:
    print('Please locate the corresponding Rscript in the following path: ' + rscript_path)
    exit()

def d_separation(df=None, sensitive=None, target=None, tmp_path=tmp_folder):

    df.to_csv(path_or_buf=tmp_folder + '/' + sensitive + '.csv', index=False)
    subprocess.run("Rscript " + rscript_path + ' ' + sensitive + ' ' + target + ' ' + tmp_path, shell=True)

    file = open(tmp_folder + '/' + sensitive + '.txt', 'r')
    f1 = file.readlines()
    l = f1[0].strip()
    l = l.replace('\n\'', '')

    if l == 'TRUE':
        response = True
    elif l == 'FALSE':
        response = False

    os.remove(tmp_folder + '/' + sensitive + '.csv')
    os.remove(tmp_folder + '/' + sensitive + '.txt')

    return response