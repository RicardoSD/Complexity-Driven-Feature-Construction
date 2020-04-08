from fastsklearnfeature.candidates.CandidateFeature import CandidateFeature
from typing import List, Dict, Set
import time
from fastsklearnfeature.candidates.RawFeature import RawFeature
from sklearn.linear_model import LogisticRegression
import pickle
import multiprocessing as mp
from fastsklearnfeature.configuration.Config import Config
import itertools
from fastsklearnfeature.transformations.Transformation import Transformation
from fastsklearnfeature.transformations.UnaryTransformation import UnaryTransformation
from fastsklearnfeature.transformations.IdentityTransformation import IdentityTransformation
from fastsklearnfeature.transformations.MinusTransformation import MinusTransformation
from fastsklearnfeature.transformations.MinMaxScalingTransformation import MinMaxScalingTransformation
import copy
from fastsklearnfeature.candidate_generation.feature_space.division import get_transformation_for_division
from fastsklearnfeature.feature_selection.evaluation.CachedEvaluationFramework import CachedEvaluationFramework
import sympy
from sklearn.metrics import make_scorer
from sklearn.metrics import f1_score
from sklearn.metrics import roc_auc_score
from sklearn.metrics import log_loss

import fastsklearnfeature.feature_selection.evaluation.my_globale_module as my_globale_module
from fastsklearnfeature.feature_selection.evaluation import nested_my_globale_module
from fastsklearnfeature.feature_selection.evaluation.run_evaluation import evaluate_candidates_parallel
from fastsklearnfeature.feature_selection.openml_wrapper.pipeline2openml import candidate2openml
import numpy as np
#from fastsklearnfeature.feature_selection.evaluation.nested_cv_scikit import nested_cv_score_parallel
from fastsklearnfeature.feature_selection.evaluation.multiple_cv_scikit import multiple_cv_score_parallel

import warnings
warnings.filterwarnings("ignore")
#warnings.filterwarnings("ignore", message="was converted to float64 by MinMaxScaler.")
warnings.filterwarnings("ignore", message="All-NaN slice encountered")
warnings.filterwarnings("ignore", message="divide by zero encountered in true_divide")


class ComplexityDrivenFeatureConstruction(CachedEvaluationFramework):
    def __init__(self, dataset_config, classifier=LogisticRegression, grid_search_parameters={'penalty': ['l2'],
                                                                                                'C': [0.001, 0.01, 0.1, 1, 10, 100, 1000],
                                                                                                'solver': ['lbfgs'],
                                                                                                'class_weight': ['balanced'],
                                                                                                'max_iter': [10000],
                                                                                                'multi_class':['auto']
                                                                                                },
                 transformation_producer=get_transformation_for_division,
                 epsilon= -np.inf,
                 c_max=4,
                 folds=10,
                 score=make_scorer(f1_score, average='micro'),
                 max_seconds=10000,
                 save_logs=None,
                 reader=None,
                 upload2openml=False,
                 remove_parents=True,
                 n_jobs=None,
                 max_feature_depth=np.inf
                 ):
        super(ComplexityDrivenFeatureConstruction, self).__init__(dataset_config, classifier, grid_search_parameters,
                                                        transformation_producer)
        self.epsilon = epsilon
        self.c_max = c_max
        self.folds = folds
        self.score = score
        self.save_logs = save_logs
        self.reader = reader
        self.upload2openml = upload2openml
        self.remove_parents = remove_parents

        self.max_timestamp = None
        if type(max_seconds) != type(None):
            self.max_timestamp = time.time() + max_seconds

        if type(n_jobs) == type(None):
            self.n_jobs = int(Config.get_default("parallelism", mp.cpu_count()))
        else:
            self.n_jobs = n_jobs

        self.max_feature_depth = max_feature_depth

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

    def get_all_features_equal_n_cost(self, cost, candidates):
        filtered_candidates = []
        for i in range(len(candidates)):
            if (candidates[i].get_number_of_transformations() + 1) == cost:
                filtered_candidates.append(candidates[i])
        return filtered_candidates

    def get_all_possible_representations_for_step_x(self, x, candidates):

        all_representations = set()
        partitions = self.partition(x)

        #get candidates of partitions
        candidates_with_cost_x = {}
        for i in range(x+1):
            candidates_with_cost_x[i] = self.get_all_features_equal_n_cost(i, candidates)

        for p in partitions:
            current_list = itertools.product(*[candidates_with_cost_x[pi] for pi in p])
            for c_output in current_list:
                if len(set(c_output)) == len(p):
                    all_representations.add(frozenset(c_output))

        return all_representations


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


    def generate_features(self, transformations: List[Transformation], features: List[CandidateFeature], all_evaluated_features: Set) -> List[CandidateFeature]:
        generated_features: List[CandidateFeature] = []
        for t_i in transformations:
            for f_i in t_i.get_combinations(features):
                if t_i.is_applicable(f_i):
                    sympy_representation = t_i.get_sympy_representation([p.get_sympy_representation() for p in f_i])
                    try:
                        if len(sympy_representation.free_symbols) > 0: # if expression is not constant
                            if not sympy_representation in all_evaluated_features:
                                candidate = CandidateFeature(copy.deepcopy(t_i), f_i)  # do we need a deep copy here?
                                candidate.sympy_representation = copy.deepcopy(sympy_representation)
                                all_evaluated_features.add(sympy_representation)
                                generated_features.append(candidate)
                            else:
                                #print("skipped: " + str(sympy_representation))
                                pass
                    except:
                        pass
        return generated_features


    def get_length_2_partition(self, cost: int) -> List[List[int]]:
        partition: List[List[int]] = []

        p = cost - 1
        while p >= cost - p:
            partition.append([p, cost - p])
            p = p - 1
        return partition

    #generate combinations for binary transformations
    def generate_merge(self, a: List[CandidateFeature], b: List[CandidateFeature], order_matters=False, repetition_allowed=False) -> List[List[CandidateFeature]]:
        # e.g. sum
        if not order_matters and repetition_allowed:
            return set([frozenset([x, y]) if x != y else (x, x) for x, y in itertools.product(*[a, b])])

        # feature concat, but does not work
        if not order_matters and not repetition_allowed:
            return set([frozenset([x, y]) for x, y in itertools.product(*[a, b]) if x != y])

        if order_matters and repetition_allowed:
            order = set(list(itertools.product(*[a, b])))
            order = order.union(set(list(itertools.product(*[b, a]))))
            return order

        # e.g. subtraction
        if order_matters and not repetition_allowed:
            order = set([(x, y) for x, y in itertools.product(*[a, b]) if x != y])
            order = order.union([(x, y) for x, y in itertools.product(*[b, a]) if x != y])
            return order







    def generate_merge_for_combination(self, all_evaluated_features, a: List[CandidateFeature], b: List[CandidateFeature]) -> Set[Set[CandidateFeature]]:
        cat_candidates_to_be_applied = []
        id_t = IdentityTransformation(None)
        for a_i in range(len(a)):
            for b_i in range(len(b)):
                combo = [a[a_i], b[b_i]]
                if id_t.is_applicable(combo):

                    sympy_representation = id_t.get_sympy_representation([p.get_sympy_representation() for p in combo])
                    if not sympy_representation in all_evaluated_features:
                        cat_candidate = CandidateFeature(copy.deepcopy(id_t), combo)
                        cat_candidate.sympy_representation = copy.deepcopy(sympy_representation)
                        all_evaluated_features.add(sympy_representation)
                        cat_candidates_to_be_applied.append(cat_candidate)

        return cat_candidates_to_be_applied


    # filter candidates that use one raw feature twice
    def filter_non_unique_combinations(self, candidates: List[CandidateFeature]):
        filtered_list: List[CandidateFeature] = []
        for candidate in candidates:
            all_raw_features = candidate.get_raw_attributes()
            if len(all_raw_features) == len(set(all_raw_features)):
                filtered_list.append(candidate)
        return filtered_list


    def materialize_raw_features(self, candidate):
        train_transformed = [None] * len(self.preprocessed_folds)
        test_transformed = [None] * len(self.preprocessed_folds)

        # test
        training_all = None
        one_test_set_transformed = None

        candidate.fit(self.dataset.splitted_values['train'])
        raw_feature = candidate.transform(self.dataset.splitted_values['train'])

        for fold in range(len(self.preprocessed_folds)):
            train_transformed[fold] = raw_feature[self.preprocessed_folds[fold][0]]
            test_transformed[fold] = raw_feature[self.preprocessed_folds[fold][1]]

        if Config.get_default('score.test', 'False') == 'True':
            training_all = raw_feature
            if Config.get_default('instance.selection', 'False') == 'True':
                candidate.fit(self.train_X_all)
                training_all = candidate.transform(self.train_X_all)

            if len(self.dataset.splitted_values['test']) > 0:
                one_test_set_transformed = candidate.transform(self.dataset.splitted_values['test'])
                candidate.runtime_properties['one_test_set_transformed'] = one_test_set_transformed

                candidate.runtime_properties['training_all'] = training_all


        candidate.runtime_properties['train_transformed'] = train_transformed
        candidate.runtime_properties['test_transformed'] = test_transformed

    def count_smaller_or_equal(self, candidates: List[CandidateFeature], current_score):
        count_smaller_or_equal = 0
        for c in candidates:
            if c.runtime_properties['score'] <= current_score:
                count_smaller_or_equal += 1
        return count_smaller_or_equal

    # P(Accuracy <= current) -> 1.0 = highest accuracy
    def getAccuracyScore(self, current_score, complexity, cost_2_raw_features, cost_2_unary_transformed, cost_2_binary_transformed, cost_2_combination):
        count_smaller_or_equal_v = 0
        count_all = 0
        for c in range(1, complexity + 1):
            if c in cost_2_raw_features:
                count_smaller_or_equal_v += self.count_smaller_or_equal(cost_2_raw_features[c], current_score)
            if c in cost_2_unary_transformed:
                count_smaller_or_equal_v += self.count_smaller_or_equal(cost_2_unary_transformed[c], current_score)
            if c in cost_2_binary_transformed:
                count_smaller_or_equal_v += self.count_smaller_or_equal(cost_2_binary_transformed[c], current_score)
            if c in cost_2_combination:
                count_smaller_or_equal_v += self.count_smaller_or_equal(cost_2_combination[c], current_score)

            if c in cost_2_raw_features:
                count_all += len(cost_2_raw_features[c])
            if c in cost_2_unary_transformed:
                count_all += len(cost_2_unary_transformed[c])
            if c in cost_2_binary_transformed:
                count_all += len(cost_2_binary_transformed[c])
            if c in cost_2_combination:
                count_all += len(cost_2_combination[c])

        return count_smaller_or_equal_v / float(count_all)

    # P(Complexity >= current) -> 1.0 = lowest complexity
    def getSimplicityScore(self, current_complexity, complexity, cost_2_raw_features, cost_2_unary_transformed, cost_2_binary_transformed, cost_2_combination):
        count_greater_or_equal_v = 0
        count_all = 0

        for c in range(1, complexity + 1):
            if c >= current_complexity:
                if c in cost_2_raw_features:
                    count_greater_or_equal_v += len(cost_2_raw_features[c])
                if c in cost_2_unary_transformed:
                    count_greater_or_equal_v += len(cost_2_unary_transformed[c])
                if c in cost_2_binary_transformed:
                    count_greater_or_equal_v += len(cost_2_binary_transformed[c])
                if c in cost_2_combination:
                    count_greater_or_equal_v += len(cost_2_combination[c])

            if c in cost_2_raw_features:
                count_all += len(cost_2_raw_features[c])
            if c in cost_2_unary_transformed:
                count_all += len(cost_2_unary_transformed[c])
            if c in cost_2_binary_transformed:
                count_all += len(cost_2_binary_transformed[c])
            if c in cost_2_combination:
                count_all += len(cost_2_combination[c])

        return count_greater_or_equal_v / float(count_all)

    def harmonic_mean(self, complexity, accuracy):
        return (2 * complexity * accuracy) / (complexity + accuracy)


    def run(self):

        self.global_starting_time = time.time()

        # generate all candidates
        self.generate()
        #starting_feature_matrix = self.create_starting_features()
        self.generate_target()

        unary_transformations, binary_transformations = self.transformation_producer(self.train_X_all, self.raw_features)

        cost_2_raw_features: Dict[int, List[CandidateFeature]] = {}
        cost_2_unary_transformed: Dict[int, List[CandidateFeature]] = {}
        cost_2_binary_transformed: Dict[int, List[CandidateFeature]] = {}
        cost_2_combination: Dict[int, List[CandidateFeature]] = {}


        if self.save_logs:
            cost_2_dropped_evaluated_candidates: Dict[int, List[CandidateFeature]] = {}

        self.complexity_delta = 1.0

        unique_raw_combinations = False


        baseline_score = 0.0 #self.evaluate_candidates([CandidateFeature(DummyOneTransformation(None), [self.raw_features[0]])])[0]['score']
        #print("baseline: " + str(baseline_score))


        max_feature = CandidateFeature(IdentityTransformation(None), [self.raw_features[0]])
        max_feature.runtime_properties['score'] = -float("inf")

        max_feature_per_complexity: Dict[int, CandidateFeature] = {}

        all_evaluated_features = set()

        my_globale_module.global_starting_time_global = copy.deepcopy(self.global_starting_time)
        my_globale_module.grid_search_parameters_global = copy.deepcopy(self.grid_search_parameters)
        my_globale_module.score_global = copy.deepcopy(self.score)
        my_globale_module.classifier_global = copy.deepcopy(self.classifier)
        my_globale_module.target_train_folds_global = copy.deepcopy(self.target_train_folds)
        my_globale_module.target_test_folds_global = copy.deepcopy(self.target_test_folds)
        my_globale_module.train_y_all_target_global = copy.deepcopy(self.train_y_all_target)
        my_globale_module.test_target_global = copy.deepcopy(self.test_target)
        my_globale_module.max_timestamp_global = copy.deepcopy(self.max_timestamp)
        my_globale_module.preprocessed_folds_global = copy.deepcopy(self.preprocessed_folds)
        my_globale_module.epsilon_global = copy.deepcopy(self.epsilon)
        my_globale_module.complexity_delta_global = copy.deepcopy(self.complexity_delta)
        my_globale_module.remove_parents = copy.deepcopy(self.remove_parents)

        my_globale_module.materialized_set = set()
        my_globale_module.predictions_set = set()

        number_of_multiple_cvs = 10
        nested_my_globale_module.splitting_seeds = np.random.randint(low=0, high=10000, size=number_of_multiple_cvs)
        nested_my_globale_module.model_seeds = np.random.randint(low=0, high=10000, size=number_of_multiple_cvs)

        #pickle.dump(my_globale_module.target_test_folds_global, open('/tmp/test_groundtruth.p', 'wb+'))


        c = 1
        while(True):
            current_layer: List[CandidateFeature] = []

            if c <= self.max_feature_depth:
                #0th
                if c == 1:
                    cost_2_raw_features[c]: List[CandidateFeature] = []
                    #print(self.raw_features)
                    for raw_f in self.raw_features:
                        sympy_representation = sympy.Symbol('X' + str(raw_f.column_id))
                        raw_f.sympy_representation = sympy_representation
                        all_evaluated_features.add(sympy_representation)
                        if raw_f.is_numeric():
                            if raw_f.properties['missing_values']:
                                raw_f.runtime_properties['score'] = 0.0
                                cost_2_raw_features[c].append(raw_f)
                            else:
                                current_layer.append(raw_f)
                            #print("numeric: " + str(raw_f))
                        else:
                            raw_f.runtime_properties['score'] = 0.0
                            cost_2_raw_features[c].append(raw_f)
                            #print("nonnumeric: " + str(raw_f))

                        self.materialize_raw_features(raw_f)
                        #raw_f.derive_properties(raw_f.runtime_properties['train_transformed'][0])

                # first unary
                # we apply all unary transformation to all c-1 in the repo (except combinations and other unary?)
                unary_candidates_to_be_applied: List[CandidateFeature] = []
                if (c - 1) in cost_2_raw_features:
                    unary_candidates_to_be_applied.extend(cost_2_raw_features[c - 1])
                if (c - 1) in cost_2_unary_transformed:
                    unary_candidates_to_be_applied.extend(cost_2_unary_transformed[c - 1])
                if (c - 1) in cost_2_binary_transformed:
                    unary_candidates_to_be_applied.extend(cost_2_binary_transformed[c - 1])

                all_unary_features = self.generate_features(unary_transformations, unary_candidates_to_be_applied, all_evaluated_features)
                current_layer.extend(all_unary_features)

                #second binary
                #get length 2 partitions for current cost
                partition = self.get_length_2_partition(c-1)
                #print("bin: c: " + str(c) + " partition" + str(partition))

                #apply cross product from partitions
                binary_candidates_to_be_applied: List[CandidateFeature] = []
                for p in partition:
                    lists_for_each_element: List[List[CandidateFeature]] = [[], []]
                    for element in range(2):
                        if p[element] in cost_2_raw_features:
                            lists_for_each_element[element].extend(cost_2_raw_features[p[element]])
                        if p[element] in cost_2_unary_transformed:
                            lists_for_each_element[element].extend(cost_2_unary_transformed[p[element]])
                        if p[element] in cost_2_binary_transformed:
                            lists_for_each_element[element].extend(cost_2_binary_transformed[p[element]])

                    for bt in binary_transformations:
                        list_of_combinations = self.generate_merge(lists_for_each_element[0], lists_for_each_element[1], bt.parent_feature_order_matters, bt.parent_feature_repetition_is_allowed)
                        #print(list_of_combinations)
                        for combo in list_of_combinations:
                            if bt.is_applicable(combo):
                                sympy_representation = bt.get_sympy_representation(
                                    [p.get_sympy_representation() for p in combo])
                                try:
                                    if len(sympy_representation.free_symbols) > 0:  # if expression is not constant
                                        if not sympy_representation in all_evaluated_features:
                                            bin_candidate = CandidateFeature(copy.deepcopy(bt), combo)
                                            bin_candidate.sympy_representation = copy.deepcopy(sympy_representation)
                                            all_evaluated_features.add(sympy_representation)
                                            binary_candidates_to_be_applied.append(bin_candidate)
                                        else:
                                            #print(str(bin_candidate) + " skipped: " + str(sympy_representation))
                                            pass
                                    else:
                                        #print(str(bin_candidate) + " skipped: " + str(sympy_representation))
                                        pass
                                except:
                                    pass
                current_layer.extend(binary_candidates_to_be_applied)

            #third: feature combinations
            #first variant: treat combination as a transformation
            #therefore, we can use the same partition as for binary data
            partition = self.get_length_2_partition(c)
            #print("combo c: " + str(c) + " partition" + str(partition))


            def filter_minus(features: List[CandidateFeature]):
                filtered_features: List[CandidateFeature] = []
                if my_globale_module.classifier_global == LogisticRegression:
                    for check_f in features:
                        if not isinstance(check_f.transformation, MinusTransformation):
                            filtered_features.append(check_f)
                return filtered_features

            # combinations_to_be_applied: List[CandidateFeature] = []
            # for p in partition:
            #     lists_for_each_element: List[List[CandidateFeature]] = [[], []]
            #     for element in range(2):
            #         if p[element] in cost_2_raw_features:
            #             lists_for_each_element[element].extend(cost_2_raw_features[p[element]])
            #         if p[element] in cost_2_unary_transformed:
            #             lists_for_each_element[element].extend(filter_minus(cost_2_unary_transformed[p[element]]))
            #         if p[element] in cost_2_binary_transformed:
            #             lists_for_each_element[element].extend(filter_minus(cost_2_binary_transformed[p[element]]))
            #         if p[element] in cost_2_combination:
            #             lists_for_each_element[element].extend(cost_2_combination[p[element]])
            #
            #     combinations_to_be_applied = self.generate_merge_for_combination(all_evaluated_features, lists_for_each_element[0], lists_for_each_element[1])
            # current_layer.extend(combinations_to_be_applied)



            if unique_raw_combinations:
                length = len(current_layer)
                current_layer = self.filter_non_unique_combinations(current_layer)
                print("From " + str(length) + " combinations, we filter " +  str(length - len(current_layer)) + " nonunique raw feature combinations.")



            #now evaluate all from this layer
            #print(current_layer)

            print("----------- Evaluation of " + str(len(current_layer)) + " representations -----------")
            results = evaluate_candidates_parallel(current_layer, self.n_jobs)
            print("----------- Evaluation Finished -----------")





            ##nested cv
            '''
            new_results_with_nested = []
            for r_result in results:
                if type(r_result) != type(None):
                    new_results_with_nested.append(r_result)
            #results = nested_cv_score_parallel(new_results_with_nested, self.reader.splitted_values['train'], self.reader.splitted_target['train'])
            results = multiple_cv_score_parallel(new_results_with_nested, self.reader.splitted_values['train'], self.reader.splitted_target['train'])
            for r_result in results:
                #print(str(r_result) + ' cv: ' + str(r_result.runtime_properties['score']) + ' test: ' + str(r_result.runtime_properties['test_score']) + ' nested: ' + str(r_result.runtime_properties['nested_cv_score']))
                print(str(r_result) + ' cv: ' + str(r_result.runtime_properties['score']) + ' test: ' + str(
                    r_result.runtime_properties['test_score']) + ' nested: ' + str(
                    r_result.runtime_properties['multiple_cv_score']))
            '''


            #print(results)

            layer_end_time = time.time() - self.global_starting_time

            #calculate whether we drop the evaluated candidate
            for candidate in results:

                ## check if we computed an equivalent feature before
                if type(candidate) != type(None) and not isinstance(candidate.transformation, IdentityTransformation):
                    materialized_all = []
                    for fold_ii in range(len(my_globale_module.preprocessed_folds_global)):
                        materialized_all.extend(candidate.runtime_properties['test_transformed'][fold_ii].flatten())
                    materialized = tuple(materialized_all)
                    if materialized in my_globale_module.materialized_set:
                        candidate = None
                    else:
                        my_globale_module.materialized_set.add(materialized)

                '''
                ## check if predictions exist already
                if type(candidate) != type(None) and 'test_fold_predictions' in candidate.runtime_properties:
                    materialized_all = []
                    for fold_ii in range(len(my_globale_module.preprocessed_folds_global)):
                        materialized_all.extend(candidate.runtime_properties['test_fold_predictions'][fold_ii].flatten())
                    materialized = tuple(materialized_all)
                    if materialized in my_globale_module.predictions_set:
                        candidate = None
                    else:
                        my_globale_module.predictions_set.add(materialized)
                '''



                if type(candidate) != type(None):
                    candidate.runtime_properties['layer_end_time'] = layer_end_time

                    #print(str(candidate) + " -> " + str(candidate.runtime_properties['score']))


                    if candidate.runtime_properties['score'] > max_feature.runtime_properties['score']:
                        max_feature = candidate

                    if candidate.runtime_properties['passed']:

                        if isinstance(candidate, RawFeature):
                            if not c in cost_2_raw_features:
                                cost_2_raw_features[c]: List[CandidateFeature] = []
                            cost_2_raw_features[c].append(candidate)
                        elif isinstance(candidate.transformation, UnaryTransformation):
                            if not c in cost_2_unary_transformed:
                                cost_2_unary_transformed[c]: List[CandidateFeature] = []
                            cost_2_unary_transformed[c].append(candidate)
                        elif isinstance(candidate.transformation, IdentityTransformation):
                            if not c in cost_2_combination:
                                cost_2_combination[c]: List[CandidateFeature] = []
                            cost_2_combination[c].append(candidate)
                        else:
                            if not c in cost_2_binary_transformed:
                                cost_2_binary_transformed[c]: List[CandidateFeature] = []
                            cost_2_binary_transformed[c].append(candidate)
                    else:
                        if self.save_logs:
                            if not c in cost_2_dropped_evaluated_candidates:
                                cost_2_dropped_evaluated_candidates[c]: List[CandidateFeature] = []
                            cost_2_dropped_evaluated_candidates[c].append(candidate)
            


            satisfied_count = 0
            if c in cost_2_raw_features:
                satisfied_count += len(cost_2_raw_features[c])
            if c in cost_2_unary_transformed:
                satisfied_count += len(cost_2_unary_transformed[c])
            if c in cost_2_binary_transformed:
                satisfied_count += len(cost_2_binary_transformed[c])
            if c in cost_2_combination:
                satisfied_count += len(cost_2_combination[c])

            all_count = len(current_layer)
            if c == 1:
                all_count = len(cost_2_raw_features[c])


            print("Of " + str(all_count) + " candidate representations, " + str(satisfied_count) + " did satisfy the epsilon threshold.")


            if len(current_layer) > 0:
                if 'test_score' in max_feature.runtime_properties:
                    print("\nBest representation found for complexity = " + str(c) + ": " + str(max_feature) + "\nmean cross-validation score: " + "{0:.2f}".format(max_feature.runtime_properties['score']) + ", score on test: " + "{0:.2f}".format(max_feature.runtime_properties['test_score']) + "\n")
                else:
                    print("\nBest representation found for complexity = " + str(c) + ": " + str(
                        max_feature) + "\nmean cross-validation score: " + "{0:.2f}".format(
                        max_feature.runtime_properties['score']) + "\n")
                #print("hyper: " + str(max_feature.runtime_properties['hyperparameters']))

                #print(max_feature.runtime_properties['fold_scores'])

            # upload best feature to OpenML
            if self.upload2openml:
                candidate2openml(max_feature, my_globale_module.classifier_global, self.reader.task, 'ComplexityDriven')


            if self.save_logs:
                try:
                    pickle.dump(cost_2_raw_features, open(Config.get_default("tmp.folder", "/tmp") + "/data_raw" + str(self.reader.rotate_test) + ".p", "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_unary_transformed, open(Config.get_default("tmp.folder", "/tmp") + "/data_unary" + str(self.reader.rotate_test) + ".p", "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_binary_transformed, open(Config.get_default("tmp.folder", "/tmp") + "/data_binary" + str(self.reader.rotate_test) + ".p", "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_combination, open(Config.get_default("tmp.folder", "/tmp") + "/data_combination" + str(self.reader.rotate_test) + ".p", "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_dropped_evaluated_candidates, open(Config.get_default("tmp.folder", "/tmp") + "/data_dropped" + str(self.reader.rotate_test) + ".p", "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                except:
                    pickle.dump(cost_2_raw_features, open(
                        Config.get_default("tmp.folder", "/tmp") + "/data_raw.p", "wb"),
                                protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_unary_transformed, open(
                        Config.get_default("tmp.folder", "/tmp") + "/data_unary.p",
                        "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_binary_transformed, open(
                        Config.get_default("tmp.folder", "/tmp") + "/data_binary.p",
                        "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_combination, open(
                        Config.get_default("tmp.folder", "/tmp") + "/data_combination.p",
                        "wb"), protocol=pickle.HIGHEST_PROTOCOL)
                    pickle.dump(cost_2_dropped_evaluated_candidates, open(
                        Config.get_default("tmp.folder", "/tmp") + "/data_dropped.p",
                        "wb"), protocol=pickle.HIGHEST_PROTOCOL)


            max_feature_per_complexity[c] = max_feature


            if type(self.c_max) == type(None) and c > 2:
                # calculate harmonic mean
                harmonic_means = [0.0]*3
                for h_i in range(len(harmonic_means)):
                    simplicity_cum_score = self.getSimplicityScore(max_feature_per_complexity[c-h_i].get_complexity(), c,
                                                                       cost_2_raw_features, cost_2_unary_transformed,
                                                                       cost_2_binary_transformed, cost_2_combination)
                    accuracy_cum_score = self.getAccuracyScore(max_feature_per_complexity[c-h_i].runtime_properties['score'], c,
                                                                   cost_2_raw_features, cost_2_unary_transformed,
                                                                   cost_2_binary_transformed, cost_2_combination)

                    harmonic_means[h_i] = self.harmonic_mean(simplicity_cum_score, accuracy_cum_score)
                    #print(str(max_feature_per_complexity[c-h_i]) + ": " + str(harmonic_means[h_i]) + " h: " + str(h_i))

                if harmonic_means[2] >= harmonic_means[1] and harmonic_means[2] >= harmonic_means[0]:
                    print("Best Harmonic Mean: " + str(max_feature_per_complexity[c-2]))
                    break


            if type(self.max_timestamp) != type(None) and time.time() >= self.max_timestamp:
                break

            c += 1

            if type(self.c_max) != type(None) and self.c_max < c:
                break





        def extend_all(all_representations: List[CandidateFeature], new_llist):
            for mylist in new_llist:
                all_representations.extend(mylist)

        #get all representation
        all_representations: List[CandidateFeature] = []
        extend_all(all_representations, cost_2_raw_features.values())
        extend_all(all_representations, cost_2_unary_transformed.values())
        extend_all(all_representations, cost_2_binary_transformed.values())
        extend_all(all_representations, cost_2_combination.values())

        self.all_representations = all_representations

        '''

        #find top k based on cv score
        scores = [c.runtime_properties['score'] for c in all_representations]
        sorted_cv_score_ids = np.argsort(np.array(scores)*-1)
        checking_k = 50
        top_k_representations = [all_representations[sorted_id] for sorted_id in sorted_cv_score_ids[0:checking_k]]

        #from top k - select best based on nested cv score
        top_k_representations = multiple_cv_score_parallel(top_k_representations, self.reader.splitted_values['train'],
                                           self.reader.splitted_target['train'])

        scores = [c.runtime_properties['multiple_cv_score'] for c in top_k_representations]

        max_nested_cv_score = -1
        max_nested_rep = None
        for eval_candidate in top_k_representations:
            if eval_candidate.runtime_properties['multiple_cv_score'] > max_nested_cv_score:
                max_nested_cv_score = eval_candidate.runtime_properties['multiple_cv_score']
                max_nested_rep = eval_candidate

        print(max_nested_rep)
        max_feature = max_nested_rep
        '''

        '''
        all_features = list(max_feature_per_complexity.values())
        all_features = multiple_cv_score_parallel(all_features, self.reader.splitted_values['train'], self.reader.splitted_target['train'])

        best_multiple_cv_score = -np.inf
        best_multiple_cv_candidate = None
        for all_f in all_features:
            if all_f.runtime_properties['multiple_cv_score'] > best_multiple_cv_score:
                best_multiple_cv_score = all_f.runtime_properties['multiple_cv_score']
                best_multiple_cv_candidate = all_f

        #find the most simple representation that is within the best representation's std
        complexities = [all_f.get_complexity() for all_f in all_features]
        ids_complex = np.argsort(complexities)
        for all_f_i in range(len(all_features)):
            print(str(all_features[ids_complex[all_f_i]]) + ' mcv: ' + str(all_features[ids_complex[all_f_i]].runtime_properties['multiple_cv_score']) + ' mcv_std: ' + str(
                all_features[ids_complex[all_f_i]].runtime_properties['multiple_cv_score_std']))

            if all_features[ids_complex[all_f_i]].runtime_properties['multiple_cv_score'] > best_multiple_cv_candidate.runtime_properties['multiple_cv_score'] - best_multiple_cv_candidate.runtime_properties['multiple_cv_score_std']:
                max_feature = all_features[ids_complex[all_f_i]]
                break

        print(max_feature)
        '''

        #min AICc selection
        min_aicc = np.inf
        min_aicc_feature = None

        all_aiccs = []
        for rep in list(max_feature_per_complexity.values()):
            try:
                all_aiccs.append(np.mean(rep.runtime_properties['additional_metrics']['AICc_complexity']))
            except KeyError:
                pass

        def calculate_AIC_for_classification_paper(rss, n, k):
            AIC = 2 * k + float(n) * np.log(rss / float(n))
            return AIC

        def calculate_AICc_for_classification_paper(rss, n, k):
            AIC = calculate_AIC_for_classification_paper(rss, n, k)
            AICc = AIC + ((2 * k * (k + 1)) / (n - k - 1))
            return AICc


        def calc_global_aicc(rep):
            return calculate_AICc_for_classification_paper(np.sum(rep.runtime_properties['additional_metrics']['rss']), np.sum(rep.runtime_properties['additional_metrics']['n']), rep.get_complexity())

        def is_better(old_aics, new_aics):
            print(np.sum(np.array(new_aics) < np.array(old_aics)))
            return np.sum(np.array(new_aics) < np.array(old_aics)) > len(new_aics) / 2.0

        for rep in list(max_feature_per_complexity.values()):
            try:
                curr = np.mean(rep.runtime_properties['additional_metrics']['AICc_complexity'])
                #print(str(rep) + ': ' + str(curr) + ' AICc min: ' + str(np.min(rep.runtime_properties['additional_metrics']['AICc_complexity'])) + ' AICc std: ' + str(np.std(rep.runtime_properties['additional_metrics']['AICc_complexity'])) + ' P: ' + str(np.exp((min(all_aiccs) - curr)/2)) + ' CV AUC: ' + str(rep.runtime_properties['score']))
                print(str(rep) + ':' + str(rep.runtime_properties['additional_metrics']['AICc_complexity']))
                print(str(rep) + ':' + str(rep.runtime_properties['additional_metrics']['rss']))
                print(str(rep) + ':' + str(rep.runtime_properties['additional_metrics']['n']))

                print(str(rep) + 'global_aicc: ' + str(calc_global_aicc(rep)))

                #if type(min_aicc_feature) == type(None) or is_better(min_aicc_feature.runtime_properties['additional_metrics']['AICc_complexity'], rep.runtime_properties['additional_metrics']['AICc_complexity']):
                if type(min_aicc_feature) == type(None) or calc_global_aicc(rep) < calc_global_aicc(min_aicc_feature):
                    #min_aicc = np.min(rep.runtime_properties['additional_metrics']['AICc_complexity'])
                    min_aicc_feature = rep
            except KeyError:
                pass
        max_feature = min_aicc_feature

        print(max_feature)

        return max_feature





if __name__ == '__main__':
    #dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_27_colic_horse.csv", 22)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/phpAmSP4g_cancer.csv", 30)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_29_credit-a_credit.csv", 15)
    #dataset = ("/home/felix/datasets/ExploreKit/csv/dataset_37_diabetes_diabetes.csv", 8)

    #dataset = (Config.get('data_path') + "/phpn1jVwe_mammography.csv", 6)
    #dataset = (Config.get('data_path') + "/dataset_31_credit-g.csv", 20)
    #dataset = (Config.get('data_path') + '/dataset_53_heart-statlog_heart.csv', 13)
    #dataset = (Config.get('data_path') + '/ILPD.csv', 10)
    #dataset = (Config.get('data_path') + '/data_banknote_authentication.txt', 4)
    #dataset = (Config.get('data_path') + '/test_categorical.data', 4)
    #dataset = (Config.get('data_path') + '/wine.data', 0)

    #dataset = (Config.get('data_path') + '/house_price.csv', 79)
    #dataset = (Config.get('data_path') + '/synthetic_data.csv', 3)

    #dataset = (Config.get('data_path') + '/transfusion.data', 4)


    from fastsklearnfeature.reader.OnlineOpenMLReader import OnlineOpenMLReader

    from fastsklearnfeature.feature_selection.openml_wrapper.openMLdict import openMLname2task

    task_id = openMLname2task['transfusion'] #interesting
    #task_id = openMLname2task['iris'] # feature selection is enough
    #task_id = openMLname2task['breast cancer']#only feature selection
    #task_id = openMLname2task['contraceptive'] #until 3 only feature selection
    #task_id = openMLname2task['german credit'] #cool with onehot
    #task_id = openMLname2task['banknote'] #raw features are already amazing
    #task_id = openMLname2task['heart-statlog']
    #task_id = openMLname2task['musk'] # feature selection only
    #task_id = openMLname2task['eucalyptus'] # cool with imputation
    #task_id = openMLname2task['haberman']
    #task_id = openMLname2task['quake'] #ok task with 4 folds
    #task_id = openMLname2task['volcanoes'] #with 4 folds, it is a good example
    #task_id = openMLname2task['analcatdata'] #with 4 folds, it is a good example
    #task_id = openMLname2task['humandevel'] # feature selection only
    #task_id = openMLname2task['diabetes'] #feature selection of deficiency works best
    #task_id = openMLname2task['lupus'] #with 4 folds, it is a good example
    #task_id = openMLname2task['credit approval']
    #task_id = openMLname2task['covertype']
    #task_id = openMLname2task['eeg_eye_state']
    #task_id = openMLname2task['MagicTelescope']
    #task_id = openMLname2task['adult']
    #task_id = openMLname2task['mushroom']
    #task_id = openMLname2task['ildp']
    #task_id = openMLname2task['biodeg']
    #task_id = openMLname2task['vowel']
    #task_id = openMLname2task['cylinder-bands']
    #task_id = openMLname2task['glass']
    #task_id = openMLname2task['kc2']
    #task_id = openMLname2task['australia']
    #task_id = openMLname2task['ada_prior']
    #dataset = None





    start = time.time()


    #regression
    #selector = ComplexityDrivenFeatureConstruction(dataset,classifier=LinearRegression,grid_search_parameters={'fit_intercept': [True, False],'normalize': [True, False]},score=r2_scorer,c_max=6,save_logs=True, epsilon=-np.inf)
    #selector = ComplexityDrivenFeatureConstruction(dataset, classifier=LinearRegression,grid_search_parameters={'fit_intercept': [True, False],'normalize': [True, False]}, score=r2_scorer,c_max=15, save_logs=True)
    #selector = ComplexityDrivenFeatureConstruction(dataset, classifier=LinearRegression, grid_search_parameters={'fit_intercept': [True, False],'normalize': [True, False]}, score=r2_scorer, c_max=15, save_logs=True, reader=OnlineOpenMLReader(task_id))


    #selector = ComplexityDrivenFeatureConstruction(dataset, classifier=LinearRegression, grid_search_parameters={'fit_intercept': [True, False],'normalize': [True, False]}, score=neg_mean_squared_error_scorer, c_max=5, save_logs=True)

    #classification
    #selector = ComplexityDrivenFeatureConstruction(dataset, c_max=10, folds=10, max_seconds=None, save_logs=True)
    #selector = ComplexityDrivenFeatureConstruction(dataset, c_max=10, folds=10, max_seconds=None, save_logs=True, epsilon=-np.inf)


    #selector = ComplexityDrivenFeatureConstruction(dataset, c_max=10, folds=10, max_seconds=None, save_logs=True, reader=OnlineOpenMLReader(task_id))


    #paper featureset
    #selector = ComplexityDrivenFeatureConstruction(dataset, c_max=10, folds=10, max_seconds=None, save_logs=True, transformation_producer=get_transformation_for_cat_feature_space)
    #selector = ComplexityDrivenFeatureConstruction(None, c_max=10, folds=10, max_seconds=None, save_logs=True, transformation_producer=get_transformation_for_division, reader=OnlineOpenMLReader(task_id, test_folds=1), score=make_scorer(f1_score, average='micro'))
    #selector = ComplexityDrivenFeatureConstruction(None, c_max=4, folds=10, max_seconds=None, save_logs=True, transformation_producer=get_transformation_for_division, reader=OnlineOpenMLReader(task_id, test_folds=1), score=make_scorer(roc_auc_score), epsilon=-np.inf, remove_parents=False, upload2openml=True)

    #for rotation in range(10):
    for rotation in range(10):
        selector = ComplexityDrivenFeatureConstruction(None, c_max=5, folds=10, max_seconds=None, save_logs=True,
                                                       transformation_producer=get_transformation_for_division,
                                                       reader=OnlineOpenMLReader(task_id, test_folds=1, rotate_test=rotation),
                                                       score=make_scorer(roc_auc_score, greater_is_better=True, needs_threshold=True),
                                                       remove_parents=False, upload2openml=True, epsilon=0)
        selector.run()

    '''
    selector = ComplexityDrivenFeatureConstruction(dataset, c_max=10, folds=10, max_seconds=None, save_logs=True,
                                                   transformation_producer=get_transformation_for_division,
                                                   score=make_scorer(f1_score, average='micro'), epsilon=-np.inf,
                                                   remove_parents=False)
    '''

    '''
    selector = ComplexityDrivenFeatureConstruction(None, c_max=10, folds=10, max_seconds=None, save_logs=True,
                                                   transformation_producer=get_transformation_for_division,
                                                   reader=OnlineOpenMLReader(task_id, test_folds=1),
                                                   score=make_scorer(roc_auc_score))
    '''

    #selector = ComplexityDrivenFeatureConstruction(dataset, c_max=5, folds=10,
    #                                               max_seconds=None, save_logs=True, transformation_producer=get_transformation_for_cat_feature_space)

    '''
    selector = ComplexityDrivenFeatureConstruction(dataset, classifier=KNeighborsClassifier,
                                                   grid_search_parameters={'n_neighbors': np.arange(3, 10),
                                                                           'weights': ['uniform', 'distance'],
                                                                           'metric': ['minkowski', 'euclidean',
                                                                                      'manhattan']}, c_max=5,
                                                   save_logs=True,
                                                   transformation_producer=get_transformation_for_cat_feature_space)
    '''


    print(time.time() - start)







