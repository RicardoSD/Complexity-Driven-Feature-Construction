from fastsklearnfeature.candidates.CandidateFeature import CandidateFeature
from typing import List, Dict, Set
import numpy as np
from fastsklearnfeature.reader.Reader import Reader
from fastsklearnfeature.splitting.Splitter import Splitter
import time
from fastsklearnfeature.candidates.RawFeature import RawFeature
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import make_scorer
from sklearn.metrics import roc_auc_score
from sklearn.metrics import f1_score
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import GridSearchCV
import multiprocessing as mp
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold
from fastsklearnfeature.configuration.Config import Config
from sklearn.pipeline import FeatureUnion
from fastsklearnfeature.candidate_generation.feature_space.explorekit_transformations import get_transformation_for_feature_space
import warnings


class EvaluationFramework:
    def __init__(self, dataset_config, classifier=LogisticRegression(), grid_search_parameters={'classifier__penalty': ['l2'],
                                                                                                'classifier__C': [0.001, 0.01, 0.1, 1, 10, 100, 1000],
                                                                                                'classifier__solver': ['lbfgs'],
                                                                                                'classifier__class_weight': ['balanced'],
                                                                                                'classifier__max_iter': [10000],
                                                                                                'classifier__multi_class':['auto']
                                                                                                },
                 transformation_producer=get_transformation_for_feature_space
                 ):
        self.dataset_config = dataset_config
        self.classifier = classifier
        self.grid_search_parameters = grid_search_parameters
        self.transformation_producer = transformation_producer

    #generate all possible combinations of features
    def generate(self):
        s = Splitter(train_fraction=[0.6, 10000000], valid_fraction=0.0, test_fraction=0.4, seed=42)

        self.dataset = Reader(self.dataset_config[0], self.dataset_config[1], s)
        self.raw_features = self.dataset.read()

        print("training:" + str(len(self.dataset.splitted_target['train'])))
        print("test:" + str(len(self.dataset.splitted_target['test'])))

    #rank and select features
    def random_select(self, k: int):
        arr = np.arange(len(self.candidates))
        np.random.shuffle(arr)
        return arr[0:k]

    def generate_target(self):
        current_target = self.dataset.splitted_target['train']

        label_encoder = LabelEncoder()
        label_encoder.fit(current_target)

        self.current_target = label_encoder.transform(current_target)
        self.test_target = label_encoder.transform(self.dataset.splitted_target['test'])

        self.preprocessed_folds = []
        for train, test in StratifiedKFold(n_splits=10, random_state=42).split(self.dataset.splitted_values['train'],
                                                                               self.current_target):
            self.preprocessed_folds.append((train, test))

    #def evaluate(self, candidate, score=make_scorer(roc_auc_score, average='micro'), folds=10):
    def evaluate(self, candidate, score=make_scorer(f1_score, average='micro'), folds=10):
        parameters = self.grid_search_parameters


        if not isinstance(candidate, CandidateFeature):
            pipeline = Pipeline([('features', FeatureUnion(

                        [(p.get_name(), p.pipeline) for p in candidate]
                    )),
                ('classifier', self.classifier)
            ])
        else:
            pipeline = Pipeline([('features', FeatureUnion(
                [
                    (candidate.get_name(), candidate.pipeline)
                ])),
                 ('classifier', self.classifier)
                 ])

        result = {}

        clf = GridSearchCV(pipeline, parameters, cv=self.preprocessed_folds, scoring=score, iid=False, error_score='raise')
        clf.fit(self.dataset.splitted_values['train'], self.current_target)
        result['score'] = clf.best_score_
        result['hyperparameters'] = clf.best_params_

        result['test_score'] = clf.score(self.dataset.splitted_values['test'], self.test_target)

        return result




    def evaluate_candidates(self, candidates):
        pool = mp.Pool(processes=int(Config.get("parallelism")))
        results = pool.map(self.evaluate_single_candidate, candidates)
        return results


    '''
    def evaluate_candidates(self, candidates):
        self.preprocessed_folds = []
        for train, test in StratifiedKFold(n_splits=10, random_state=42).split(self.dataset.splitted_values['train'],
                                                                               self.current_target):
            self.preprocessed_folds.append((train, test))

        results = []
        for c in candidates:
            results.append(self.evaluate_single_candidate(c))
        return results
    '''




    def evaluate_single_candidate(self, candidate):
        result = {}
        time_start_gs = time.time()
        try:
            result = self.evaluate(candidate)
            #print("feature: " + str(candidate) + " -> " + str(new_score))
        except Exception as e:
            warnings.warn(str(candidate) + " -> " + str(e), RuntimeWarning)
            result['score'] = -1.0
            result['test_score'] = -1.0
            result['hyperparameters'] = {}
            pass
        result['candidate'] = candidate
        result['execution_time'] = time.time() - time_start_gs
        result['global_time'] = time.time() - self.global_starting_time
        return result




    '''
    def evaluate_single_candidate(self, candidate):
        result = {}
        result['score'] = 0.0
        result['candidate'] = candidate
        return result
    '''

    '''
    def evaluate_single_candidate(self, candidate):
        new_score = -1.0
        new_score = self.evaluate(candidate)
        return new_score
    '''





