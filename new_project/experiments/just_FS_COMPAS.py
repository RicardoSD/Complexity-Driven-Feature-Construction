import pandas as pd
from pathlib import Path
import itertools
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler
from sklearn.compose import ColumnTransformer
from sklearn.metrics import f1_score
from sklearn.metrics import make_scorer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, FunctionTransformer
import ROD
from sklearn.model_selection import cross_val_score
from sklearn.model_selection import KFold
from sklearn.model_selection import GridSearchCV
from numpy.linalg import norm
import random
import sys
sys.path.insert(0, '~/Finding-Fair-Representations-Through-Feature-Construction/Code')

home = str(Path.home())

results_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/data/intermediate_results'

COMPAS_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/data/compas-analysis'

COMPAS = pd.read_csv(COMPAS_path + '/compas-scores.csv')

COMPAS = COMPAS.loc[(COMPAS['days_b_screening_arrest'] <= 30) &
                    (COMPAS['priors_count'].isin([1, 2, 3, 4, 5, 6]))
                    & (COMPAS['is_recid'] != -1)
                    & (COMPAS['race'].isin(['African-American','Caucasian']))
                    & (COMPAS['c_charge_degree'].isin(['F','M']))
                    , ['race', 'age', 'priors_count', 'is_recid', 'c_charge_degree']]

sensitive_feature = 'race'
inadmissible_features = []
target = 'is_recid'
admissible_features = [i for i in list(COMPAS) if
                       i not in inadmissible_features and i != sensitive_feature and i != target]

all_features = list(COMPAS)
all_features.remove(target)

complexity = 4
CF = False
count = 0
method_list = []
kf1 = KFold(n_splits=5, random_state=42, shuffle=True)
for train_index, test_index in kf1.split(COMPAS):

    train_df = COMPAS.iloc[train_index]
    test_df = COMPAS.iloc[test_index]

    X_train = train_df.loc[:, all_features]

    y_train = train_df.loc[:, target]

    X_test = test_df.loc[:, all_features]

    y_test = test_df.loc[:, target]

    rod_score = make_scorer(ROD.ROD, greater_is_better=True, needs_proba=True,
                            sensitive=X_train.loc[:, sensitive_feature],
                            admissible=X_train.loc[:, admissible_features],
                            protected='African-American', name='train_COMPAS')

    f1 = make_scorer(f1_score, greater_is_better=True, needs_threshold=False)

    ##################### Original

    categorical_features = []
    numerical_features = []
    for i in list(COMPAS):
        if i != target and COMPAS[i].dtype == np.dtype('O'):
            categorical_features.extend([i])
        elif i != target and COMPAS[i].dtype != np.dtype('O'):
            numerical_features.extend([i])

    categorical_transformer = Pipeline(steps=[
        ('onehot', OneHotEncoder(handle_unknown='ignore'))])

    numerical_transformer = Pipeline(steps=[
        ('scaler', MinMaxScaler())])

    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', categorical_transformer, categorical_features),
            ('num', numerical_transformer, numerical_features)], remainder='passthrough')

    original_pipeline = Pipeline(steps=[('preprocessor', preprocessor),
                                        ('clf',
                                         LogisticRegression(penalty='l2', C=1, solver='lbfgs', class_weight='balanced',
                                                            max_iter=100000, multi_class='auto'))])

    original_train = preprocessor.fit_transform(X_train)
    original_test = preprocessor.transform(X_test)

    feature_names = list(preprocessor.transformers_[0][1].named_steps['onehot'].get_feature_names(categorical_features))
    feature_names.extend(numerical_features)

    test_clf = LogisticRegression(penalty='l2', C=1, solver='lbfgs', class_weight='balanced',
                                  max_iter=100000, multi_class='auto', n_jobs=-1)

    accepted_features = []
    accepted_ids = []
    transformed_train = np.empty((X_train.shape[0], 1))
    transformed_test = np.empty((X_test.shape[0], 1))
    global_F1 = 0
    global_ROD = -np.inf
    registered_representations_train = []
    registered_representations_test = []
    unique_representations = []
    for idj in range(original_train.shape[1]):
        ##### step 1: Try to add a feature :

        accepted_ids.extend([idj])

        transformed_train = original_train[:, accepted_ids]
        transformed_test = original_test[:, accepted_ids]
        accepted_features.extend([feature_names[idj]])
        accepted_features_photo = accepted_features.copy()
        accepted_features_photo.sort()
        unique_representations.append(accepted_features_photo.copy())

        print('SFFS - adding', transformed_train.shape[1], accepted_features_photo)

        cv_scores = GridSearchCV(LogisticRegression(), param_grid={
            'penalty':['l2'], 'C':[1], 'solver':['lbfgs'], 'class_weight':['balanced'],
                                  'max_iter':[100000], 'multi_class':['auto']
        },
                     n_jobs=-1,
                     scoring={'F1': f1, 'ROD': rod_score}, refit='F1', cv=3)

        cv_scores.fit(transformed_train, np.ravel(y_train.to_numpy()))
        test_scores = cv_scores.cv_results_['mean_test_F1'][0]
        rod_scores = cv_scores.cv_results_['mean_test_ROD'][0]

        #test_clf.fit(transformed_train, np.ravel(y_train.to_numpy()))
        predicted_ff = cv_scores.predict(transformed_test)
        predicted_ff_proba = cv_scores.predict_proba(transformed_test)[:, 1]
        rod_ff = ROD.ROD(y_pred=predicted_ff_proba, sensitive=X_test.loc[:, [sensitive_feature]],
                         admissible=X_test.loc[:, admissible_features],
                         protected='African-American', name='backward_COMPAS')
        f1_ff = f1_score(np.ravel(y_test.to_numpy()), predicted_ff)

        predicted_ff_train = cv_scores.predict(transformed_train)
        predicted_ff_proba_train = cv_scores.predict_proba(transformed_train)[:, 1]
        rod_ff_train = ROD.ROD(y_pred=predicted_ff_proba_train, sensitive=X_train.loc[:, [sensitive_feature]],
                         admissible=X_train.loc[:, admissible_features],
                         protected='African-American', name='backward_COMPAS')
        f1_ff_train = f1_score(np.ravel(y_train.to_numpy()), predicted_ff_train)

        registered_representations_test.append(
            [accepted_features.copy(), transformed_test.shape[1], f1_ff, rod_ff])
        registered_representations_train.append(
            [accepted_features.copy(), transformed_train.shape[1], f1_ff_train, rod_ff_train])

        print(transformed_train.shape, f1_ff, rod_ff, accepted_features)

        if test_scores > global_F1:
            global_F1 = test_scores

            ##### Step 2: Try to remove a feature:

            selected_ids = []
            for idd in range(transformed_train.shape[1]):
                if transformed_train.shape[1] > len(selected_ids) + 1:
                    selected_ids.extend([idd])
                    transformed_train_r = np.delete(transformed_train, selected_ids, 1)
                    transformed_test_r = np.delete(transformed_test, selected_ids, 1)
                    accepted_features_r = [f for idf, f in enumerate(accepted_features) if idf not in selected_ids]
                    accepted_features_r.sort()

                    print('SFFS - removing', transformed_train_r.shape[1], accepted_features_r)

                    if accepted_features_r not in unique_representations:
                        unique_representations.append(accepted_features_r.copy())

                        cv_scores.fit(transformed_train_r, np.ravel(y_train.to_numpy()))
                        test_scores_r = cv_scores.cv_results_['mean_test_F1'][0]
                        rod_scores_r = cv_scores.cv_results_['mean_test_ROD'][0]

                        #test_clf.fit(transformed_train_r, np.ravel(y_train.to_numpy()))
                        predicted_ff_r = cv_scores.predict(transformed_test_r)
                        predicted_ff_r_proba = cv_scores.predict_proba(transformed_test_r)[:, 1]
                        rod_ff_r = ROD.ROD(y_pred=predicted_ff_r_proba, sensitive=X_test.loc[:, [sensitive_feature]],
                                           admissible=X_test.loc[:, admissible_features],
                                           protected='African-American', name='backward_COMPAS')
                        f1_ff_r = f1_score(np.ravel(y_test.to_numpy()), predicted_ff_r)

                        predicted_ff_r_train = cv_scores.predict(transformed_train_r)
                        predicted_ff_r_proba_train = cv_scores.predict_proba(transformed_train_r)[:, 1]
                        rod_ff_r_train = ROD.ROD(y_pred=predicted_ff_r_proba_train, sensitive=X_train.loc[:, [sensitive_feature]],
                                           admissible=X_train.loc[:, admissible_features],
                                           protected='African-American', name='backward_COMPAS')
                        f1_ff_r_train = f1_score(np.ravel(y_train.to_numpy()), predicted_ff_r_train)

                        registered_representations_test.append(
                            [accepted_features_r.copy(), transformed_test_r.shape[1], f1_ff_r, rod_ff_r])
                        registered_representations_train.append(
                            [accepted_features_r.copy(), transformed_train_r.shape[1], f1_ff_r_train, rod_ff_r_train])

                        if test_scores_r > global_F1:
                            global_F1 = test_scores_r
                        else:
                            selected_ids.remove(idd)
                    else:
                        selected_ids.remove(idd)
                else:
                    pass
            print('selected ids for removing: ' + str(selected_ids))
            if len(selected_ids) > 0:
                transformed_train = np.delete(transformed_train, selected_ids, 1)
                transformed_test = np.delete(transformed_test, selected_ids, 1)
                accepted_ids = [idf for idf, f in enumerate(accepted_features) if idf not in selected_ids]
                accepted_features = [f for idf, f in enumerate(accepted_features) if idf not in selected_ids]
            else:
                pass
            print(transformed_train.shape[1], accepted_features)
        elif transformed_train.shape[1] > 1:
            transformed_train = np.delete(transformed_train, -1, 1)
            transformed_test = np.delete(transformed_test, -1, 1)
            del accepted_features[-1]
            del accepted_ids[-1]
        else:
            pass

    print(transformed_train.shape, transformed_test.shape, str(global_F1))


    cv_scores = GridSearchCV(LogisticRegression(), param_grid={
        'penalty': ['l2'], 'C': [1], 'solver': ['lbfgs'], 'class_weight': ['balanced'],
        'max_iter': [100000], 'multi_class': ['auto']
    },
                             n_jobs=-1,
                             scoring={'F1': f1, 'ROD': rod_score},refit='ROD', cv=3)

    cv_scores.fit(transformed_train, np.ravel(y_train.to_numpy()))
    test_scores_c = cv_scores.cv_results_['mean_test_F1'][0]
    rod_scores_c = cv_scores.cv_results_['mean_test_ROD'][0]

    rod_complete = rod_scores_c
    f1_complete = test_scores_c

    print('__________________________________________')
    print('Round 2 : Improving in the other direction. Start with backward floating elimination: ')

    print('F1 complete: {:.4f}'.format(f1_complete))
    print('ROD complete {:.4f}'.format(rod_complete))

    selected_ids_r = []
    for d in range(transformed_train.shape[1]):
        if transformed_train.shape[1] > len(selected_ids_r) + 1:
            selected_ids_r.extend([d])
            transformed_train_cr = np.delete(transformed_train, selected_ids_r, 1)
            transformed_test_cr = np.delete(transformed_test, selected_ids_r, 1)
            accepted_features_cr = [f for idf, f in enumerate(accepted_features) if idf not in selected_ids_r]
            accepted_features_cr.sort()

            print('SFBS - removing', transformed_train_cr.shape[1], accepted_features_cr)

            if accepted_features_cr not in unique_representations:

                cv_scores.fit(transformed_train_cr, np.ravel(y_train.to_numpy()))
                test_scores_cr = cv_scores.cv_results_['mean_test_F1'][0]
                rod_scores_cr = cv_scores.cv_results_['mean_test_ROD'][0]

                #complete_clf.fit(transformed_train_cr, np.ravel(y_train.to_numpy()))
                predicted_b = cv_scores.predict(transformed_test_cr)
                predicted_b_proba = cv_scores.predict_proba(transformed_test_cr)[:, 1]
                rod_b = ROD.ROD(y_pred=predicted_b_proba, sensitive=X_test.loc[:, [sensitive_feature]],
                                admissible=X_test.loc[:, admissible_features],
                                protected='African-American', name='backward_COMPAS')
                f1_b = f1_score(np.ravel(y_test.to_numpy()), predicted_b)

                predicted_b_train = cv_scores.predict(transformed_train_cr)
                predicted_b_proba_train = cv_scores.predict_proba(transformed_train_cr)[:, 1]
                rod_b_train = ROD.ROD(y_pred=predicted_b_proba_train, sensitive=X_train.loc[:, [sensitive_feature]],
                                admissible=X_train.loc[:, admissible_features],
                                protected='African-American', name='backward_COMPAS')
                f1_b_train = f1_score(np.ravel(y_train.to_numpy()), predicted_b_train)

                registered_representations_test.append(
                    [accepted_features_cr.copy(), transformed_test_cr.shape[1], f1_b, rod_b])
                registered_representations_train.append(
                    [accepted_features_cr.copy(), transformed_train_cr.shape[1], f1_b_train, rod_b_train])
                unique_representations.append(accepted_features_cr.copy())

                print(transformed_train_cr.shape, f1_b, rod_b, accepted_features_cr)

                if rod_scores_cr > rod_complete:
                    rod_complete = rod_scores_cr
                    f1_complete = test_scores_cr

                    for ida in selected_ids_r:
                        selected_ids_r.remove(ida)
                        transformed_train_a = np.delete(transformed_train, selected_ids_r, 1)
                        transformed_test_a = np.delete(transformed_test, selected_ids_r, 1)
                        accepted_features_a = [f for idf, f in enumerate(accepted_features) if
                                               idf not in selected_ids_r]
                        accepted_features_a.sort()
                        print('SFBS - adding', transformed_train_a.shape[1], accepted_features_a)

                        if accepted_features_a not in unique_representations:
                            cv_scores.fit(transformed_train_a, np.ravel(y_train.to_numpy()))
                            test_scores_a = cv_scores.cv_results_['mean_test_F1'][0]
                            rod_scores_a = cv_scores.cv_results_['mean_test_ROD'][0]

                            #complete_clf.fit(transformed_train_a, np.ravel(y_train.to_numpy()))
                            predicted_a = cv_scores.predict(transformed_test_a)
                            predicted_a_proba = cv_scores.predict_proba(transformed_test_a)[:, 1]
                            rod_a = ROD.ROD(y_pred=predicted_a_proba, sensitive=X_test.loc[:, [sensitive_feature]],
                                            admissible=X_test.loc[:, admissible_features],
                                            protected='African-American', name='backward_COMPAS')
                            f1_a = f1_score(np.ravel(y_test.to_numpy()), predicted_a)

                            predicted_a_train = cv_scores.predict(transformed_train_a)
                            predicted_a_proba_train = cv_scores.predict_proba(transformed_train_a)[:, 1]
                            rod_a_train = ROD.ROD(y_pred=predicted_a_proba_train, sensitive=X_train.loc[:, [sensitive_feature]],
                                            admissible=X_train.loc[:, admissible_features],
                                            protected='African-American', name='backward_COMPAS')
                            f1_a_train = f1_score(np.ravel(y_train.to_numpy()), predicted_a_train)

                            registered_representations_test.append(
                                [accepted_features_a.copy(), transformed_test_a.shape[1], f1_a, rod_a])
                            registered_representations_train.append(
                                [accepted_features_a.copy(), transformed_train_a.shape[1], f1_a_train, rod_a_train])
                            unique_representations.append(accepted_features_a.copy())

                            if rod_scores_a > rod_complete:
                                rod_complete = rod_scores_a
                                f1_complete = test_scores_a
                            else:
                                selected_ids_r.extend([ida])
                        else:
                            selected_ids_r.extend([ida])
                else:
                    selected_ids_r.remove(d)
            else:
                selected_ids_r.remove(d)
        else:
            pass

        print('representation size: ' + str(transformed_train.shape[1] - len(selected_ids_r)),
              'ROD: ' + str(rod_complete), 'F1' + str(f1_complete))

    # if len(selected_ids_r) > 0:
    #     transformed_train = np.delete(transformed_train, selected_ids_r, 1)
    #     transformed_test = np.delete(transformed_test, selected_ids_r, 1)
    #     accepted_features = [f for idf, f in enumerate(accepted_features) if idf not in selected_ids_r]
    # else:
    #     pass

    all_visited = np.asarray(registered_representations_train)
    all_visited_test = np.asarray(registered_representations_test)
    scores = all_visited[:, [2, 3]]


    def identify_pareto(scores):
        # Count number of items
        population_size = scores.shape[0]
        # Create a NumPy index for scores on the pareto front (zero indexed)
        population_ids = np.arange(population_size)
        # Create a starting list of items on the Pareto front
        # All items start off as being labelled as on the Parteo front
        pareto_front = np.ones(population_size, dtype=bool)
        # Loop through each item. This will then be compared with all other items
        for i in range(population_size):
            # Loop through all other items
            for j in range(population_size):
                # Check if our 'i' pint is dominated by out 'j' point
                if all(scores[j] >= scores[i]) and any(scores[j] > scores[i]):
                    # j dominates i. Label 'i' point as not on Pareto front
                    pareto_front[i] = 0
                    # Stop further comparisons with 'i' (no more comparisons needed)
                    break
        # Return ids of scenarios on pareto front
        return population_ids[pareto_front]


    normalized = (scores[:, 1] - scores[:, 1].min()) / (0 - scores[:, 1].min())
    scores[:, 1] = normalized

    pareto = identify_pareto(scores)
    pareto_front = scores[pareto]

    ideal_point = np.asarray([1, 1])
    dist = np.empty((pareto_front.shape[0], 1))

    for idx, i in enumerate(pareto_front):
        dist[idx] = norm(i - ideal_point)

    min_dist = np.argmin(dist)
    selected_representation = all_visited_test[pareto[min_dist]]
    selected_representation_train = all_visited[pareto[min_dist]]

    print('ROD original ' + ': ' + str(selected_representation[3]))
    print('F1 original ' + ': ' + str(selected_representation[2]))

    count += 1

    method_list.append(['COMPAS - test', selected_representation[3], selected_representation[2], selected_representation[0], selected_representation[1], count])
    method_list.append(
        ['COMPAS - train', selected_representation_train[3], selected_representation_train[2], selected_representation_train[0],
         selected_representation_train[1], count])
    method_df = pd.DataFrame(method_list, columns=['Problem - Set', 'ROD', 'F1', 'Representation', 'Size', 'Fold'])
    method_df.to_csv(
            path_or_buf=results_path + '/COMPAS_original_FS.csv', index=False)

    registered_representations_train_df = pd.DataFrame(registered_representations_train,
                                                       columns=['Representation', 'Size', 'F1', 'ROD'])

    registered_representations_test_df = pd.DataFrame(registered_representations_test,
                                                       columns=['Representation', 'Size', 'F1', 'ROD'])


    registered_representations_train_df.to_csv(
        path_or_buf=results_path + '/COMPAS_complete_visited_representations_train_' + str(count) + '.csv',
        index=False)
    registered_representations_test_df.to_csv(
        path_or_buf=results_path + '/COMPAS_complete_visited_representations_test_' + str(count) + '.csv',
        index=False)