from fastsklearnfeature.candidates.CandidateFeature import CandidateFeature
from fastsklearnfeature.transformations.IdentityTransformation import IdentityTransformation
from fastsklearnfeature.transformations.feature_selection.SissoTransformer import SissoTransformer
from typing import List
import time
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model import LinearRegression
from sklearn.metrics import make_scorer
from sklearn.metrics import f1_score
import pickle
from sklearn.model_selection import GridSearchCV
import multiprocessing as mp
from sklearn.model_selection import StratifiedKFold
from fastsklearnfeature.configuration.Config import Config
import itertools
from fastsklearnfeature.feature_selection.evaluation.EvaluationFramework import EvaluationFramework
from sklearn.metrics.scorer import r2_scorer


class Sisso(EvaluationFramework):
    def __init__(self, dataset_config, classifier=LogisticRegression, grid_search_parameters={'penalty': ['l2'],
                                                                                                'C': [0.001, 0.01, 0.1, 1, 10, 100, 1000],
                                                                                                'solver': ['lbfgs'],
                                                                                                'class_weight': ['balanced'],
                                                                                                'max_iter': [10000]
                                                                                                },
                 reader=None,
                 score=make_scorer(f1_score, average='micro'),
                 folds=10
                 ):
        self.dataset_config = dataset_config
        self.classifier = classifier
        self.grid_search_parameters = grid_search_parameters
        self.reader = reader
        self.score = score
        self.folds=folds




    #https://stackoverflow.com/questions/10035752/elegant-python-code-for-integer-partitioning
    def partition(self, number):
        answer = set()
        answer.add((number,))
        for x in range(1, number):
            for y in self.partition(number - x):
                answer.add(tuple(sorted((x,) + y)))
        return answer

    def get_all_features_below_n_cost(self, cost):
        filtered_candidates = []
        for i in range(len(self.candidates)):
            if (self.candidates[i].get_number_of_transformations() + 1) <= cost:
                filtered_candidates.append(self.candidates[i])
        return filtered_candidates

    def get_all_features_equal_n_cost(self, cost):
        filtered_candidates = []
        for i in range(len(self.candidates)):
            if (self.candidates[i].get_number_of_transformations() + 1) == cost:
                filtered_candidates.append(self.candidates[i])
        return filtered_candidates



    def get_all_possible_representations_for_step_x(self, x):

        all_representations = set()
        partitions = self.partition(x)

        #get candidates of partitions
        candidates_with_cost_x = {}
        for i in range(x+1):
            candidates_with_cost_x[i] = self.get_all_features_equal_n_cost(i)

        for p in partitions:
            current_list = itertools.product(*[candidates_with_cost_x[pi] for pi in p])
            for c_output in current_list:
                if len(set(c_output)) == len(p):
                    all_representations.add(frozenset(c_output))

        return all_representations


    def filter_failing_features(self):
        working_features: List[CandidateFeature] = []
        for candidate in self.candidates:
            try:
                candidate.fit(self.dataset.splitted_values['train'])
                candidate.transform(self.dataset.splitted_values['train'])
            except:
                continue
            working_features.append(candidate)
        return working_features


    def filter_candidate(self, candidate):
        working_features: List[CandidateFeature] = []
        try:
            candidate.fit(self.dataset.splitted_values['train'])
            candidate.transform(self.dataset.splitted_values['train'])
            working_features.append(candidate)
        except:
            pass
        return working_features


    def filter_failing_in_parallel(self):
        pool = mp.Pool(processes=int(Config.get("parallelism")))
        results = pool.map(self.filter_candidate, self.candidates)
        return list(itertools.chain(*results))


    def run(self):
        self.global_starting_time = time.time()

        # generate all candidates
        self.generate()
        #starting_feature_matrix = self.create_starting_features()
        self.generate_target()

        all_f = CandidateFeature(IdentityTransformation(len(self.raw_features)), self.raw_features)


        feature_names = [str(r) for r in self.raw_features]

        t = CandidateFeature(SissoTransformer(len(self.raw_features), feature_names, ["^2", "^3", "1/"]), [all_f])

        t.pipeline.fit(self.dataset.splitted_values['train'], self.train_y_all_target)
        X = t.transform(self.dataset.splitted_values['train'])
        X_test = t.transform(self.dataset.splitted_values['test'])

        print("time: " + str(time.time() - self.global_starting_time))

        clf = GridSearchCV(self.classifier(), self.grid_search_parameters, cv=self.preprocessed_folds,
                           scoring=self.score, iid=False,
                           error_score='raise')
        clf.fit(X, self.train_y_all_target)

        print(X_test)

        print('test score: ' + str(clf.score(X_test, self.test_target)))
        print("\n\n")



#statlog_heart.csv=/home/felix/datasets/ExploreKit/csv/dataset_53_heart-statlog_heart.csv
#statlog_heart.target=13

if __name__ == '__main__':
    #dataset = (Config.get('statlog_heart.csv'), 13)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_27_colic_horse.csv", 22)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/phpAmSP4g_cancer.csv", 30)
    # dataset = ("/home/felix/datasets/ExploreKit/csv/phpOJxGL9_indianliver.csv", 10)
    # dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_29_credit-a_credit.csv", 15)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_37_diabetes_diabetes.csv", 8)
    # dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_31_credit-g_german_credit.csv", 20)
    # dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_23_cmc_contraceptive.csv", 9)
    # dataset = ("/home/felix/datasets/ExploreKit/csv/phpn1jVwe_mammography.csv", 6)

    #dataset = (Config.get('data_path') + '/house_price.csv', 79)

    from fastsklearnfeature.reader.OnlineOpenMLReader import OnlineOpenMLReader
    from fastsklearnfeature.feature_selection.evaluation.openMLdict import openMLname2task

    task_id = openMLname2task['transfusion'] #interesting
    # task_id = openMLname2task['iris']
    # task_id = openMLname2task['ecoli']
    # task_id = openMLname2task['breast cancer']
    # task_id = openMLname2task['contraceptive']
    #task_id = openMLname2task['german credit']  # interesting
    # task_id = openMLname2task['monks']
    # task_id = openMLname2task['banknote']
    # task_id = openMLname2task['heart-statlog']
    # task_id = openMLname2task['musk']
    # task_id = openMLname2task['eucalyptus']
    dataset = None

    #dataset = (Config.get('data_path') + '/transfusion.data', 4)

    selector = Sisso(dataset, reader=OnlineOpenMLReader(task_id))
    #selector = Sisso(dataset, score=r2_scorer, classifier=LinearRegression)
    #selector = Sisso(dataset)

    results = selector.run()

    pickle.dump(results, open("/tmp/all_data_iterations.p", "wb"))





