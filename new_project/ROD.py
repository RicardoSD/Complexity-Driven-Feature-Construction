import numpy as np
import subprocess
from pathlib import Path
import pandas as pd
home = str(Path.home())

path = Path(home + '/Finding-Fair-Representations-Through-Feature-Construction/data/tmp')
path.mkdir(parents=True, exist_ok=True)
tmp_folder = home + '/Finding-Fair-Representations-Through-Feature-Construction/data/tmp'
rscript_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/Rscript_template.R'

if Path(rscript_path).is_file():
    pass
else:
    print('Please locate the corresponding Rscript in the following path: ' + rscript_path)
    exit()

def learn_MB(df=None, name=None, tmp_path=tmp_folder):

    df.to_csv(path_or_buf=tmp_folder + '/' + name + '.csv', index=False)
    subprocess.run("Rscript " + rscript_path + ' ' + name + ' ' + tmp_path, shell=True)

    mb = []
    file = open(tmp_folder + '/' + name + '.txt', 'r')
    f1 = file.readlines()
    for line in f1:
        line = line.strip()
        l = line.replace('\n\'', '')
        l = l.replace("\\", "")
        mb.extend([l])

    print('Markov blanket for ' + name + ' : {}'.format(mb))
    return mb


def ROD(y_true=None, y_pred=None, sensitive=None, protected=None, inadmissible=None, name=None):

    if not isinstance(y_pred, pd.DataFrame):
        y_pred = pd.DataFrame(y_pred)
    else:
        pass

    sensitive_data = y_pred.loc[:, [sensitive]].to_numpy()
    outcome = y_pred.loc[:, ['outcome']].to_numpy()

    if 'outcome' in list(y_pred):
        t = [i for i in list(y_pred) if (i != sensitive and i not in inadmissible)]
        df = y_pred.loc[:, t]
        mb = learn_MB(df, name)
        contexts = df.loc[:, mb].to_numpy()
    else:
        print('outcome must be specified in dataframe')
        exit()

    protected = np.asarray(protected)
    unique_contexts = np.array(list(set([tuple(x) for x in contexts])))
    contexts = np.array(list([tuple(x) for x in contexts]))
    ROD = []
    weights = []
    for z in unique_contexts:

        test_c = np.char.equal(contexts, z)
        ids = np.argwhere(np.all(test_c, axis=1))

        test_s = np.not_equal(sensitive_data, protected)
        s_ids = np.argwhere(test_s)
        cs_ids = np.intersect1d(ids, s_ids)
        if cs_ids.shape[0] > 0:
            p_1_0 = np.mean(np.ravel(outcome[cs_ids]))
            p_0_0 = float(1 - p_1_0)
        else:
            p_1_0 = 0.5
            p_0_0 = 0.5

        test_ns = np.equal(sensitive_data, protected)
        ns_ids = np.argwhere(test_ns)
        cns_ids = np.intersect1d(ids, ns_ids)
        if cns_ids.shape[0] > 0:
            p_1_1 = np.mean(np.ravel(outcome[cns_ids]))
            p_0_1 = float(1 - p_1_1)
        else:
            p_1_1 = 0.5
            p_0_1 = 0.5

        try:
            OR = (p_1_0 / p_0_0) * (p_0_1 / p_1_1)

            if np.isinf(OR) == False and np.isnan(OR) == False:
                ROD.extend([OR])
                weights.extend([ids.shape[0] / y_pred.shape[0]])
            else:
                pass
        except ZeroDivisionError:
            pass

    result = abs(np.dot(np.squeeze(ROD), weights) - 1)

    return result


