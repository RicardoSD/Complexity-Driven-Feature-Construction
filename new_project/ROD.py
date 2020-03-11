import numpy as np
import subprocess
from pathlib import Path
import pandas as pd
from random import randrange
import os
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

    r = randrange(1000000)
    df.to_csv(path_or_buf=tmp_folder + '/' + name + str(r) + '.csv', index=False)
    subprocess.run("Rscript " + rscript_path + ' ' + name + str(r) + ' ' + tmp_path, shell=True)

    mb = []
    file = open(tmp_folder + '/' + name + str(r) + '.txt', 'r')
    f1 = file.readlines()
    for line in f1:
        line = line.strip()
        l = line.replace('\n\'', '')
        l = l.replace("\\", "")
        mb.extend([l])

    os.remove(tmp_folder + '/' + name + str(r) + '.csv')
    os.remove(tmp_folder + '/' + name + str(r) + '.txt')


    print('Markov blanket for ' + name + ' : {}'.format(mb))
    return mb

def generate_binned_df(df):
    columns2_drop = []
    df_ = df.copy()
    for i in list(df_):
        if i not in ['target', 'outcome'] and (df_[i].dtype != np.dtype('O') and len(df_[i].unique()) > 4):

            out, bins = pd.qcut(df_[i], q=4, retbins=True, duplicates='drop')
            df_.loc[:, i] = out.astype(str)

    return df_


def ROD(y_true=None, y_pred=None, sensitive=None, protected=None, admissible=None, name=None):

    if not isinstance(y_pred, pd.DataFrame):
        y_pred = pd.DataFrame(y_pred)
    else:
        pass

    sensitive_data = sensitive.iloc[y_pred.index.values]
    outcome_array = y_pred.to_numpy()
    outcome = pd.DataFrame(outcome_array, columns=['outcome'])
    admissible_data = admissible.iloc[y_pred.index.values]

    df = pd.concat([admissible_data, outcome], axis=1)

    mb = learn_MB(df, name)
    binned_df = generate_binned_df(df)
    contexts = binned_df.loc[:, mb].to_numpy()

    protected = np.asarray(protected)
    unique_contexts = np.array(list(set([tuple(x) for x in contexts])))

    mb_empty = False
    if len(mb) > 0:
        contexts = np.array(list([tuple(x) for x in contexts]))
    else:
        mb_empty = True

    if mb_empty == False:
        ROD = []
        weights = []
        for z in unique_contexts:

            if z.dtype == 'float64' and unique_contexts.dtype == 'float64':
                test_c = z == contexts
            else:
                test_c = np.char.equal(contexts, z)

            ids = np.argwhere(np.all(test_c, axis=1))

            test_s = np.not_equal(sensitive_data.to_numpy(), protected)
            s_ids = np.argwhere(test_s)
            cs_ids = np.intersect1d(ids, s_ids)

            if cs_ids.shape[0] > 0:
                p_1_0 = np.mean(np.ravel(outcome_array[cs_ids]))
                p_0_0 = float(1 - p_1_0)
            else:
                p_1_0 = 0.5
                p_0_0 = 0.5

            test_ns = np.equal(sensitive_data.to_numpy(), protected)
            ns_ids = np.argwhere(test_ns)
            cns_ids = np.intersect1d(ids, ns_ids)

            if cns_ids.shape[0] > 0:
                p_1_1 = np.mean(np.ravel(outcome_array[cns_ids]))
                p_0_1 = float(1 - p_1_1)
            else:
                p_1_1 = 0.5
                p_0_1 = 0.5


            try:
                OR = (p_1_0 / p_0_0) * (p_0_1 / p_1_1)

                if np.isinf(OR) == False and np.isnan(OR) == False:
                    ROD.extend([OR])
                    weights.extend([ids.shape[0] / contexts.shape[0]])
                else:
                    pass
            except ZeroDivisionError:
                pass

        result = abs(np.dot(np.squeeze(ROD), weights) - 1)
    else:
        test_s = np.not_equal(sensitive_data.to_numpy(), protected)
        s_ids = np.argwhere(test_s)
        if s_ids.shape[0] > 0:
            p_1_0 = np.mean(np.ravel(outcome_array[s_ids]))
            p_0_0 = float(1 - p_1_0)
        else:
            p_1_0 = 0.5
            p_0_0 = 0.5

        test_ns = np.equal(sensitive_data.to_numpy(), protected)
        ns_ids = np.argwhere(test_ns)

        if ns_ids.shape[0] > 0:
            p_1_1 = np.mean(np.ravel(outcome_array[ns_ids]))
            p_0_1 = float(1 - p_1_1)
        else:
            p_1_1 = 0.5
            p_0_1 = 0.5


        try:
            OR = (p_1_0 / p_0_0) * (p_0_1 / p_1_1)

            if np.isinf(OR) == False and np.isnan(OR) == False:
                result = abs(OR - 1)
            else:
                pass
        except ZeroDivisionError:
            pass


    return result

