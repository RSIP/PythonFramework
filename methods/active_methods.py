import abc
from saveable.saveable import Saveable
from configs.base_configs import MethodConfigs
from sklearn.linear_model import LinearRegression
from sklearn import linear_model
from sklearn import neighbors
from sklearn import dummy
from sklearn import grid_search
from sklearn.metrics import pairwise
import numpy as np
from numpy.linalg import norm
from copy import deepcopy
from results_class.results import Output
from results_class.results import FoldResults
from results_class import results as results_lib
from data_sets import create_data_split
from data import data as data_lib
from utility import array_functions
from metrics import metrics
import collections
import scipy
from timer.timer import tic,toc
from utility import helper_functions
from copy import deepcopy
import cvxpy as cvx
from methods import method
from numpy.linalg import *
from scipy import optimize
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest
from sklearn.feature_selection import f_regression

class ActiveMethod(method.Method):
    def __init__(self,configs=MethodConfigs()):
        super(ActiveMethod, self).__init__(configs)
        self.base_learner = method.SKLRidgeRegression(configs)

    def train_and_test(self, data):
        if self.configs.num_features < data.p:
            select_k_best = SelectKBest(f_regression, self.configs.num_features)
            data.x = select_k_best.fit_transform(data.x, data.true_y)
        num_items_per_iteration = self.configs.active_items_per_iteration
        active_iterations = self.configs.active_iterations
        curr_data = deepcopy(data)
        active_fold_results = results_lib.ActiveFoldResults(active_iterations)
        for iter_idx in range(active_iterations):
            I = np.empty(0)
            if iter_idx > 0:
                sampling_distribution, items = self.create_sampling_distribution(self.base_learner,
                                                                                 curr_data,
                                                                                 fold_results)
                I = array_functions.sample(items,
                                           num_items_per_iteration,
                                           sampling_distribution)
                try:
                    all_inds = helper_functions.flatten_list_of_lists(I)
                    assert curr_data.is_train[all_inds].all()
                except AssertionError as error:
                    assert False, 'Pairwise labeling of test data isn''t implemented yet!'
                except:
                    assert not curr_data.is_labeled[I].any()
                curr_data.reveal_labels(I)
            fold_results = self.base_learner.train_and_test(curr_data)
            active_iteration_results = results_lib.ActiveIterationResults(fold_results,I)
            active_fold_results.set(active_iteration_results, iter_idx)
        return active_fold_results

    def create_sampling_distribution(self, base_learner, data, fold_results):
        I = data.is_train & ~data.is_labeled
        d = np.zeros(data.y.shape)
        d[I] = 1
        d = d / d.sum()
        return d, d.size


    def run_method(self, data):
        assert False, 'Not implemented for ActiveMethod'

    def train(self, data):
        assert False, 'Not implemented for ActiveMethod'
        pass

    def predict(self, data):
        assert False, 'Not implemented for ActiveMethod'
        pass

    @property
    def prefix(self):
        return 'ActiveRandom+' + self.base_learner.prefix

class OptimizationData(object):
    def __init__(self, x, C):
        self.x = x
        self.C = C
        self.x_labeled = None


def eval_oed(t, opt_data):
    x = opt_data.x
    n, p = x.shape
    M = opt_data.C * np.eye(p)
    if opt_data.x_labeled is not None:
        xl = opt_data.x_labeled
        M += xl.T.dot(xl)
    for i in range(n):
        M += t[i]*np.outer(x[i,:], x[i,:])

    return np.trace(inv(M))

class OEDLinearActiveMethod(ActiveMethod):
    def __init__(self, configs=MethodConfigs()):
        super(OEDLinearActiveMethod, self).__init__(configs)
        self.transform = StandardScaler()
        self.use_labeled = True

    def create_sampling_distribution(self, base_learner, data, fold_results):
        is_train_unlabeled = data.is_train & (~data.is_labeled)
        is_train_labeled = data.is_train & data.is_labeled
        inds = np.nonzero(is_train_unlabeled)[0]
        inds = inds[:50]
        I = array_functions.false(data.n)
        I[inds] = True
        x = data.x[I, :]
        x_labeled = data.x[is_train_labeled, :]
        if self.use_labeled:
            x_all = np.vstack((x, x_labeled))
            self.transform.fit(x_all)
            x = self.transform.transform(x)
            x_labeled = self.transform.transform(x_labeled)
        else:
            x = self.transform.fit_transform(x)
        C = base_learner.params['alpha']
        n = I.sum()
        t0 = np.zeros((n,1))
        opt_data = OptimizationData(x, C)
        if self.use_labeled:
            opt_data.x_labeled = x_labeled
        constraints = [
            {
                'type': 'eq',
                'fun': lambda t: t.sum() - 1
            },
            {
                'type': 'ineq',
                'fun': lambda t: t
            }
        ]
        options = {}
        results = optimize.minimize(
            lambda t: eval_oed(t, opt_data),
            t0,
            method='SLSQP',
            jac=None,
            options=options,
            constraints=constraints
        )
        if results.success:
            t = results.x
        else:
            print 'OED Optimization failed'
            t = np.ones(n)
        t[t < 0] = 0
        t += 1e-4
        t /= t.sum()
        return t, inds

    @property
    def prefix(self):
        s = 'OED+' + self.base_learner.prefix
        if self.use_labeled:
            s += '_use-labeled'
        return s


class RelativeActiveMethod(ActiveMethod):
    def __init__(self,configs=MethodConfigs()):
        super(RelativeActiveMethod, self).__init__(configs)

    def create_sampling_distribution(self, base_learner, data, fold_results):
        all_pairs = self.create_pairs(data)
        d = np.zeros(all_pairs.shape[0])
        d[:] = 1
        d = d / d.sum()
        return d, all_pairs

    def create_pairs(self, data):
        assert False, 'Use PairwiseConstraint instead of tuples'
        if not hasattr(data, 'pairwise_relationships'):
            data.pairwise_relationships = set()
        I = data.is_train.nonzero()[0]
        all_pairs = set()
        for x1 in I:
            for x2 in I:
                if x1 <= x2 or (x1,x2) in data.pairwise_relationships or (x2,x1) in data.pairwise_relationships:
                    continue
                all_pairs.add((x1,x2))
        all_pairs = np.asarray(list(all_pairs))

    @property
    def prefix(self):
        return 'RelActiveRandom+' + self.base_learner.prefix

class IGRelativeActiveMethod(RelativeActiveMethod):
    def __init__(self,configs=MethodConfigs()):
        super(IGRelativeActiveMethod, self).__init__(configs)

    def create_sampling_distribution(self, base_learner, data, fold_results):
        all_pairs = self.create_pairs(data)
        d = np.zeros(all_pairs.shape[0])
        for x1, x2 in all_pairs:
            pass
        d = d / d.sum()
        return d, all_pairs

    @property
    def prefix(self):
        return 'RelActiveRandom+' + self.base_learner.prefix






































