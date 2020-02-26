import pandas as pd
from pathlib import Path
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, FunctionTransformer
from sklearn.preprocessing import MinMaxScaler
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV
from sklearn.model_selection import KFold
from sklearn.metrics import accuracy_score, f1_score
from fastsklearnfeature.interactiveAutoML.feature_selection.ConstructionTransformation import ConstructionTransformer
from sklearn.metrics import make_scorer
from sklearn.linear_model import LogisticRegression
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
import ROD
import sys
sys.path.insert(0, '/Users/ricardosalazar/Finding-Fair-Representations-Through-Feature-Construction/Code')
from methods.capuchin import repair_dataset

home = str(Path.home())


adult_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/data'
results_path = home + '/Finding-Fair-Representations-Through-Feature-Construction/data/intermediate_results'

adult_df = pd.read_csv(adult_path + '/adult.csv', sep=';', header=0)

def label(row):
   if row['class'] == ' <=50K' :
      return 0
   else:
       return 1

sensitive_feature = 'sex'
inadmissible_features = ['marital-status']
target = 'target'
adult_df['target'] = adult_df.apply(lambda row: label(row), axis=1)
adult_df.drop(columns=['class', 'relationship', 'race', 'native-country', 'fnlwgt', 'education-num'], inplace=True)
admissible_features = [i for i in list(adult_df) if i not in inadmissible_features and i != sensitive_feature and i != target]

def generate_binned_df(df):
    columns2_drop = []
    df_ = df.copy()
    for i in list(df_):
        if i not in ['target', 'outcome'] and (df_[i].dtype != np.dtype('O') and len(df_[i].unique()) > 4):

            out, bins = pd.qcut(df_[i], q=4, retbins=True, duplicates='drop')
            df_.loc[:, i] = out.astype(str)

    return df_

#a = generate_binned_df(adult_df)
#print(adult_df['sex'].unique())

######################## Dropped #####################################

categorical_features_2 = []
numerical_features_2 = []

for i in list(adult_df):
    if i != target and i not in inadmissible_features and i != sensitive_feature and adult_df[i].dtype == np.dtype('O'):
        categorical_features_2.extend([i])
    elif i != target and i not in inadmissible_features and i != sensitive_feature and adult_df[i].dtype != np.dtype('O'):
        numerical_features_2.extend([i])

categorical_transformer_2 = Pipeline(steps=[
    ('onehot', OneHotEncoder(handle_unknown='ignore'))])

numerical_transformer_2 = Pipeline(steps=[
    ('scaler', MinMaxScaler())])

preprocessor_2 = ColumnTransformer(
    transformers=[
        ('cat', categorical_transformer_2, categorical_features_2),
        ('num', numerical_transformer_2, numerical_features_2)], remainder='passthrough')

dropped_pipeline = Pipeline(steps=[('preprocessor', preprocessor_2),
                      ('clf', RandomForestClassifier())])

cv_grid_dropped = GridSearchCV(dropped_pipeline, param_grid = {
    'clf__n_estimators' : [100]#,
    #'clf__criterion' : ['gini', 'entropy'],
    #'clf__class_weight' : [None, 'balanced'],
    #'clf__max_depth' : [None, 3, 5] #,
    #'clf__ccp_alpha' : [0.0, 0.5, 1.0]
    },
    n_jobs=-1,
    scoring='accuracy')

######################### Original ###########################

categorical_features = []
numerical_features = []
for i in list(adult_df):
    if i != target and adult_df[i].dtype == np.dtype('O'):
        categorical_features.extend([i])
    elif i != target and adult_df[i].dtype != np.dtype('O'):
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
                      ('clf', RandomForestClassifier())])

cv_grid_original = GridSearchCV(original_pipeline, param_grid = {
    'clf__n_estimators' : [100]#,
    #'clf__criterion' : ['gini', 'entropy'],
    #'clf__class_weight' : [None, 'balanced'],
    #'clf__max_depth' : [None, 3, 5] #,
    #'clf__ccp_alpha' : [0.0, 0.5, 1.0]
    },
    n_jobs=-1,
    scoring='accuracy')

############################## Capuchin ####################################

capuchin_df = adult_df

categorical_features_3 = []
numerical_features_3 = []

a = generate_binned_df(capuchin_df)

for i in list(a):
    if i != target and (a[i].dtype == np.dtype('O') or a[i].dtype == 'category'):
        categorical_features_3.extend([i])
    elif i != target and (a[i].dtype != np.dtype('O') and a[i].dtype != 'category'):
        numerical_features_3.extend([i])

categorical_transformer_3 = Pipeline(steps=[
    ('onehot', OneHotEncoder(handle_unknown='ignore'))])

numerical_transformer_3 = Pipeline(steps=[
    ('scaler', MinMaxScaler())])

preprocessor_3 = ColumnTransformer(
    transformers=[
        ('cat', categorical_transformer_3, categorical_features_3),
        ('num', numerical_transformer_3, numerical_features_3)], remainder='passthrough')

capuchin_repair_pipeline = Pipeline(steps=[('generate_binned_df', FunctionTransformer(generate_binned_df)),
                        ('repair', FunctionTransformer(repair_dataset, kw_args={'admissible_attributes' : admissible_features,
                                                                                'sensitive_attribute': sensitive_feature,
                                                                                'target': target}))])

capuchin_pipeline = Pipeline(steps=[('preprocessor', preprocessor_3),
                        ('clf', RandomForestClassifier())])


cv_grid_capuchin = GridSearchCV(capuchin_pipeline, param_grid = {
    'clf__n_estimators' : [100]#,
    #'clf__criterion' : ['gini', 'entropy'],
    #'clf__class_weight' : [None, 'balanced'],
    #'clf__max_depth' : [None, 3, 5]#,
    #'clf__ccp_alpha' : [0.0, 0.5, 1.0]
    },
    n_jobs=-1,
    scoring='accuracy')

############################## Feature Construction #############################################

features2_build = []
for i in list(adult_df):
    if i not in inadmissible_features and i != sensitive_feature and i != target:
    #if i != target:
        features2_build.extend([i])

features2_build_cat = []
features2_build_num = []
for i in features2_build:
    if adult_df[i].dtype == np.dtype('O'):
        features2_build_cat.extend([i])
    else:
        features2_build_num.extend([i])

features2_scale = []
for i in features2_build:
    if adult_df[i].dtype != np.dtype('O'):
        features2_scale.extend([features2_build.index(i)])
    else:
        pass

numerical_transformer = Pipeline(steps=[
    ('scaler', MinMaxScaler())])

preprocessor = ColumnTransformer(
    transformers=[
        ('num', numerical_transformer, features2_scale)], remainder='passthrough')

new_order = features2_build_num + features2_build_cat
features2_build_mask = ([False] * len(features2_build_num)) + ([True] * len(features2_build_cat))

acc = make_scorer(accuracy_score, greater_is_better=True, needs_threshold=False)
f1 = make_scorer(f1_score, greater_is_better=True, needs_threshold=False)
column_transformation = Pipeline([('new_construction', ConstructionTransformer(c_max=3,max_time_secs=10000, scoring=acc, n_jobs=4, model=LogisticRegression(),
                                                       parameter_grid={'penalty': ['l2'], 'C': [1], 'solver': ['lbfgs'],
                                                                       'class_weight': ['balanced'], 'max_iter': [100000],
                                                                       'multi_class':['auto']}, cv=5, epsilon=-np.inf,
                                                    feature_names=new_order,
                                                    feature_is_categorical=features2_build_mask))])



transformed_pipeline = Pipeline(steps=[('preprocessor', preprocessor),
                                ('feature_construction', column_transformation)])#,#,
                                #('clf', RandomForestClassifier())])
                                #('clf', cv_grid_transformed)])

transformed_classifier = RandomForestClassifier(n_estimators=250, max_features=1.0 ,n_jobs=-1)

cv_grid_transformed = GridSearchCV(RandomForestClassifier(), param_grid = {
    'n_estimators' : [250],#,
    #'criterion' : ['gini', 'entropy'],
    #'class_weight' : [None, 'balanced'],
    #'max_depth' : [None, 3, 5],#,
    'max_features' : [1.0]
    },
    n_jobs=-1,
    scoring='accuracy')

#########################################

################################################
count = 0
method_list = []
kf1 = KFold(n_splits=5, shuffle=True)
for train_index, test_index in kf1.split(adult_df):

    print('Start proccessing fold: {}'.format(count+1))
    train_df = adult_df.iloc[train_index]
    test_df = adult_df.iloc[test_index]

    X_train = train_df.loc[:, ['workclass', 'education', 'sex', 'marital-status', 'occupation', 'age', 'capital-gain',
                            'capital-loss', 'hours-per-week']]

    y_train = train_df.loc[:, 'target']

    X_test = test_df.loc[:, ['workclass', 'education', 'sex', 'marital-status', 'occupation', 'age', 'capital-gain',
                               'capital-loss', 'hours-per-week']]

    y_test = test_df.loc[:, 'target']



    X_train_t = train_df.loc[:, features2_build].to_numpy()
    X_test_t = test_df.loc[:, features2_build].to_numpy()

    X_train_t_1, X_test_t_1, y_train_t_1, y_test_t_1 = train_test_split(X_train_t, y_train, test_size=0.33)

    transformed_train = transformed_pipeline.fit_transform(X_train_t_1, np.ravel(y_train_t_1))
    all_transformations = transformed_pipeline.named_steps['feature_construction'].named_steps[
        'new_construction'].all_features_set
    transformed_test = transformed_pipeline.transform(X_test)

    transformed_columns = []
    for i in all_transformations:
        j = (i.get_name()).strip()
        transformed_columns.extend([j])



    print('Start repairing training set with capuchin')
    train_repaired = capuchin_repair_pipeline.fit_transform(pd.concat([X_train, y_train], axis=1))
    print('Finished repairing training set with capuchin')
    y_train_repaired = train_repaired.loc[:, ['target']].to_numpy()
    X_train_repaired = train_repaired.loc[:,
                           ['workclass', 'education', 'occupation', 'sex', 'marital-status', 'age', 'capital-gain',
                               'capital-loss', 'hours-per-week']]
    X_test_capuchin = (generate_binned_df(X_test)).loc[:,['workclass', 'education', 'occupation', 'sex', 'marital-status',
                                                         'age', 'capital-gain',
                                                        'capital-loss', 'hours-per-week']]

    X_train_dropped = X_train.drop(columns=['sex', 'marital-status'])
    X_test_dropped = X_test.drop(columns=['sex', 'marital-status'])

    print('Training classifiers')
    dropped = dropped_pipeline.fit(X_train_dropped, np.ravel(y_train.to_numpy()))
    original = original_pipeline.fit(X_train, np.ravel(y_train.to_numpy()))
    capuchin = capuchin_pipeline.fit(X_train_repaired, np.ravel(y_train_repaired))
    print('start training feature construction training set')
    feature_construction_1 = transformed_classifier.fit(transformed_train, np.ravel(y_train_t_1))

    result = permutation_importance(feature_construction_1, transformed_train, np.ravel(y_train_t_1), n_repeats=5,
                                    scoring='accuracy', n_jobs=-1)

    sorted_idx = result.importances_mean.argsort()

    best = [all_transformations[i] for i in sorted_idx][-5:]
    best_idx = sorted_idx[-5:]

    trunc_clf = RandomForestClassifier()

    transformed_test_test = transformed_pipeline.transform(X_test_t_1)
    X_train_test_trunc = transformed_test_test[:, best_idx]

    feature_construction = trunc_clf.fit(X_train_test_trunc, np.ravel(y_test_t_1))

    transformed_test_trunc = transformed_test[:, best_idx]


    print('Classifiers were trained')
    #
    outcome_dropped = dropped.predict(X_test_dropped)
    y_pred_proba_dropped = dropped.predict_proba(X_test_dropped)[:, 1]
    outcome_original = original.predict(X_test)
    y_pred_proba_original = original.predict_proba(X_test)[:, 1]
    outcome_capuchin = capuchin.predict(X_test_capuchin)
    y_pred_proba_capuchin = capuchin.predict_proba(X_test_capuchin)[:, 1]
    outcome_transformed = feature_construction.predict(transformed_test_trunc)
    y_pred_proba_transformed = feature_construction.predict_proba(transformed_test_trunc)[:, 1]

    admissible_df = X_test_dropped
    admissible_feature_construction = pd.DataFrame(transformed_test_trunc, columns=best)

    rod_dropped = ROD.ROD(y_pred=y_pred_proba_dropped, sensitive=X_test.loc[:, ['sex']], admissible = admissible_df,
                      protected=' Female', name='dropped_adult')
    rod_original = ROD.ROD(y_pred=y_pred_proba_original, sensitive=X_test.loc[:, ['sex']], admissible = admissible_df,
                      protected=' Female', name='original_adult')
    rod_capuchin = ROD.ROD(y_pred=y_pred_proba_capuchin, sensitive=X_test.loc[:, ['sex']], admissible = admissible_df,
                      protected=' Female',
                      name='capuchin_adult')
    rod_transformed = ROD.ROD(y_pred=y_pred_proba_transformed, sensitive=X_test.loc[:, ['sex']], admissible=admissible_feature_construction,
                  protected=' Female', name='feature_construction_adult')

    acc_dropped = accuracy_score(np.ravel(y_test), outcome_dropped)
    acc_original = accuracy_score(np.ravel(y_test), outcome_original)
    acc_capuchin = accuracy_score(np.ravel(y_test), outcome_capuchin)
    acc_transformed = accuracy_score(np.ravel(y_test), outcome_transformed)

    method_list.extend([['feature_construction', acc_transformed, rod_transformed, count + 1],
                        ['original', acc_original, rod_original, count + 1],
                        ['dropped', acc_dropped, rod_dropped, count + 1],
                        ['capuchin', acc_capuchin, rod_capuchin, count + 1]])


    count += 1

    print('Fold: {}'.format(count))
    print('ROD dropped: {:.4f}'.format(rod_dropped))
    print('ROD orginal: {:.4f}'.format(rod_original))
    print('ROD capuchin: {:.4f}'.format(rod_capuchin))
    print('ROD transformed: {:.4f}'.format(rod_transformed))
    print('ACC dropped: {:.4f}'.format(acc_dropped))
    print('ACC orginal: {:.4f}'.format(acc_original))
    print('ACC capuchin: {:.4f}'.format(acc_capuchin))
    print('ACC transformed: {:.4f}'.format(acc_transformed))

summary_df = pd.DataFrame(method_list, columns=['Method', 'Accuracy', 'ROD', 'fold'])

print(summary_df.groupby('Method')['Accuracy'].mean())
print(summary_df.groupby('Method')['ROD'].mean())

summary_df.to_csv(path_or_buf=results_path + '/summary_adult_rfACC_df.csv', index=False)

#print(mb_original)
#print(mb_dropped)

#binned_X_test_original.to_csv(path_or_buf=adult_path + '/original_adult.csv', index=False)
#binned_X_test_dropped.to_csv(path_or_buf=adult_path + '/dropped_adult.csv', index=False)