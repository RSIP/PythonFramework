import cvxpy as cvx

from methods.constrained_methods import PairwiseConstraint
from timer import timer

__author__ = 'Aubrey'

import abc
from copy import deepcopy

import numpy as np
from sklearn import dummy
from sklearn import grid_search
from sklearn import linear_model
from sklearn import neighbors
from sklearn.metrics import pairwise
from sklearn.preprocessing import StandardScaler

from configs.base_configs import MethodConfigs
from data import data as data_lib
from data_sets import create_data_split
from results_class import results as results_lib
from results_class.results import FoldResults, Output
from results_class.results import Output
from saveable.saveable import Saveable
from utility import array_functions


#from pyqt_fit import nonparam_regression
#from pyqt_fit import npr_methods

class Method(Saveable):

    def __init__(self,configs=MethodConfigs()):
        super(Method, self).__init__(configs)
        self._params = []
        self.cv_params = {}
        self.is_classifier = True
        self.experiment_results_class = results_lib.ExperimentResults
        self.cv_use_data_type = True
        self.use_test_error_for_model_selection = False
        self.can_use_test_error_for_model_selection = False
        self._estimated_error = None
        self.quiet = True
        self.best_params = None
        self.transform = None
        self.warm_start = False

    @property
    def params(self):
        return self._params

    @property
    def estimated_error(self):
        return self._estimated_error

    @estimated_error.setter
    def estimated_error(self, value):
        self._estimated_error = value

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._params = kwargs

    def run_method(self, data):
        self.train(data)
        if data.x.shape[0] == 0:
            assert False
            self.train(data)
        return self.predict(data)

    def _create_cv_splits(self,data):
        data_splitter = create_data_split.DataSplitter()
        num_splits = 10
        if hasattr(self, 'num_splits'):
            num_splits = self.num_splits
        perc_train = .8
        is_regression = data.is_regression
        if self.cv_use_data_type:
            splits = data_splitter.generate_splits(data.y,num_splits,perc_train,is_regression,data.is_target)
        else:
            splits = data_splitter.generate_splits(data.y,num_splits,perc_train,is_regression)
        return splits

    def run_cross_validation(self,data):
        assert data.n_train_labeled > 0
        train_data = deepcopy(data)
        test_data = data.get_subset(data.is_test)
        if self.configs.use_validation:
            I = train_data.is_labeled
            train_data.reveal_labels()
            ds = create_data_split.DataSplitter()
            splits = ds.generate_identity_split(I)
        elif self.use_test_error_for_model_selection:
            I = train_data.is_train
            ds = create_data_split.DataSplitter()
            splits = ds.generate_identity_split(I)
        else:
            train_data = data.get_subset(data.is_train)
            splits = self._create_cv_splits(train_data)
        data_and_splits = data_lib.SplitData(train_data,splits)
        param_grid = list(grid_search.ParameterGrid(self.cv_params))
        if not self.cv_params:
            return param_grid[0], None
        #Results when using cross validation
        param_results = [self.experiment_results_class(len(splits)) for i in range(len(param_grid))]

        #Results when using test data to do model selection
        param_results_on_test = [self.experiment_results_class(len(splits)) for i in range(len(param_grid))]
        for i in range(len(splits)):
            curr_split = data_and_splits.get_split(i)
            curr_split.remove_test_labels()
            self.warm_start = False
            for param_idx, params in enumerate(param_grid):
                self.set_params(**params)
                results = self.run_method(curr_split)
                fold_results = FoldResults()
                fold_results.prediction = results
                param_results[param_idx].set(fold_results, i)
                results_on_test_data = self.predict(test_data)
                fold_results_on_test_data = FoldResults()
                fold_results_on_test_data.prediction = results_on_test_data
                param_results_on_test[param_idx].set(fold_results_on_test_data, i)

                #Make sure error can be computed
                #param_results[param_idx].aggregate_error(self.configs.cv_loss_function)
                self.warm_start = True
        self.warm_start = False
        errors = np.empty(len(param_grid))
        errors_on_test_data = np.empty(len(param_grid))
        for i in range(len(param_grid)):
            agg_results = param_results[i].aggregate_error(self.configs.cv_loss_function)
            assert len(agg_results) == 1
            errors[i] = agg_results[0].mean

            agg_results_test = param_results_on_test[i].aggregate_error(self.configs.cv_loss_function)
            assert len(agg_results_test) == 1
            errors_on_test_data[i] = agg_results_test[0].mean

        min_error = errors.min()
        best_params = param_grid[errors.argmin()]
        if not self.quiet:
            print best_params
        self.best_params = best_params
        return [best_params, min_error, errors_on_test_data[errors.argmin()]]

    def process_data(self, data):
        labels_to_keep = np.empty(0)
        t = getattr(self.configs,'target_labels',None)
        s = getattr(self.configs,'source_labels',None)
        if t is not None and t.size > 0:
            labels_to_keep = np.concatenate((labels_to_keep,t))
        if s is not None and s.size > 0:
            s = s.ravel()
            labels_to_keep = np.concatenate((labels_to_keep,s))
            inds = array_functions.find_set(data.y,s)
            data.type[inds] = data_lib.TYPE_SOURCE
            data.is_train[inds] = True
        if labels_to_keep.size > 0:
            data = data.get_transfer_subset(labels_to_keep,include_unlabeled=True)
        return data


    def train_and_test(self, data):
        self.should_plot_g = False
        data = self.process_data(data)
        if len(self.cv_params) == 0:
            best_params = None
            min_error = None
            error_on_test_data = None
        else:
            best_params, min_error, error_on_test_data = self.run_cross_validation(data)
            self.set_params(**best_params)
        self.should_plot_g = True
        output = self.run_method(data)
        f = FoldResults()
        f.prediction = output
        f.estimated_error = min_error
        f.error_on_test_data = error_on_test_data
        self.estimated_error = min_error
        self.error_on_test_data = error_on_test_data
        if best_params is not None:
            for key,value in best_params.iteritems():
                setattr(f,key,value)
        return f


    @abc.abstractmethod
    def train(self, data):
        pass

    @abc.abstractmethod
    def predict(self, data):
        pass

    def predict_loo(self, data):
        assert False, 'Not implemented!'

class ModelSelectionMethod(Method):
    def __init__(self, configs=None):
        super(ModelSelectionMethod, self).__init__(configs)
        self.methods = []
        self.chosen_method_idx = None

    @property
    def selected_method(self):
        assert self.chosen_method_idx is not None
        return self.methods[self.chosen_method_idx]

    def train(self, data):
        assert len(self.methods) > 0
        estimated_errors = np.zeros(len(self.methods))
        for i, method in enumerate(self.methods):
            results = method.train_and_test(data)
            estimated_errors[i] = method.estimated_error
        self.chosen_method_idx = estimated_errors.argmin()
        print 'Chose: ' + str(self.selected_method.__class__)


    def predict(self, data):
        return self.selected_method.predict(data)

    @property
    def prefix(self):
        return 'ModelSelection'

class NadarayaWatsonMethod(Method):
    def __init__(self,configs=MethodConfigs()):
        super(NadarayaWatsonMethod, self).__init__(configs)
        self.cv_params['sigma'] = 10**np.asarray(range(-8,8),dtype='float64')
        #self.sigma = 1
        self.metric = 'euclidean'
        if 'metric' in configs.__dict__:
            self.metric = configs.metric
        self.instance_weights = None
        #self.metric = 'cosine'

    def compute_kernel(self,x,y):
        #TODO: Optimize this for cosine similarity using cross product and matrix multiplication
        W = pairwise.pairwise_distances(x,y,self.metric)
        W = np.square(W)
        W = -self.sigma * W
        W = np.exp(W)
        return W
        #return pairwise.rbf_kernel(x,y,self.sigma)

    def train(self, data):
        is_labeled_train = data.is_train & data.is_labeled
        labeled_train = data.labeled_training_data()
        x_labeled = labeled_train.x
        self.x = x_labeled
        self.y = labeled_train.y
        self.is_classifier = not data.is_regression

        if 'instance_weights' in data.__dict__ and data.instance_weights is not None:
            self.instance_weights = data.instance_weights[is_labeled_train]

    def predict(self, data):
        o = Output(data)
        #W = pairwise.rbf_kernel(data.x,self.x,self.sigma)
        W = self.compute_kernel(data.x, self.x)
        if self.instance_weights is not None:
            W = W*self.instance_weights
        '''
        W = array_functions.replace_invalid(W,0,0)
        D = W.sum(1)
        D[D==0] = 1
        D_inv = 1 / D
        array_functions.replace_invalid(D_inv,x_min=1,x_max=1)
        S = (W.swapaxes(0, 1) * D_inv).swapaxes(0, 1)
        '''
        S = array_functions.make_smoothing_matrix(W)
        if not data.is_regression:
            fu = np.zeros((data.n,self.y.max()+1))
            for i in np.unique(self.y):
                I = self.y == i
                Si = S[:,I]
                fu_i = Si.sum(1)
                fu[:,i] = fu_i
            fu2 = fu
            fu = array_functions.replace_invalid(fu,0,1)
            fu = array_functions.normalize_rows(fu)
            o.fu = fu
            y = fu.argmax(1)
            I = y == 0
            if I.any():
                fu[I,self.y[0]] = 1
                y = fu.argmax(1)
                #assert False
        else:
            y = np.dot(S,self.y)
            y = array_functions.replace_invalid(y,self.y.min(),self.y.max())
            o.fu = y
        o.y = y
        return o

    def predict_loo(self, data):
        data = data.get_subset(data.is_labeled)
        o = Output(data)
        n = data.n
        W = self.compute_kernel(data.x, data.x)
        W[np.diag(np.ones(n)) == 1] = 0
        D = W.sum(1)
        D_inv = 1 / D
        array_functions.replace_invalid(D_inv,x_min=1,x_max=1)
        S = np.dot(np.diag(D_inv),W)

        if not data.is_regression:
            y_mat = array_functions.make_label_matrix(data.y)
            fu = np.dot(S,array_functions.try_toarray(y_mat))
            fu = array_functions.replace_invalid(fu,0,1)
            fu = array_functions.normalize_rows(fu)
            o.fu = fu
            o.y = fu.argmax(1)
        else:
            o.y = np.dot(S,data.y)
            o.fu = o.y
        return o

    def tune_loo(self, data):
        train_data = data.get_subset(data.is_train)

        param_grid = list(grid_search.ParameterGrid(self.cv_params))
        if not self.cv_params:
            return
        errors = np.empty(len(param_grid))
        for param_idx, params in enumerate(param_grid):
            self.set_params(**params)
            results = self.predict_loo(train_data)
            errors[param_idx] = results.compute_error_train(self.configs.loss_function)
        min_error = errors.min()
        best_params = param_grid[errors.argmin()]
        #print best_params
        self.set_params(**best_params)

    @property
    def prefix(self):
        return 'NW'

class ScikitLearnMethod(Method):

    _short_name_dict = {
        'Ridge': 'RidgeReg',
        'DummyClassifier': 'DumClass',
        'DummyRegressor': 'DumReg',
        'LogisticRegression': 'LogReg',
        'KNeighborsClassifier': 'KNN',
    }

    def __init__(self,configs=MethodConfigs(),skl_method=None):
        super(ScikitLearnMethod, self).__init__(configs)
        self.skl_method = skl_method

    def train(self, data):
        labeled_train = data.labeled_training_data()
        x = labeled_train.x
        if self.transform is not None:
            x = self.transform.fit_transform(x)
        self.skl_method.fit(x, labeled_train.y)

    def predict(self, data):
        o = Output(data)
        x = data.x
        if self.transform is not None:
            x = self.transform.transform(x)
        o.y = self.skl_method.predict(x)
        o.y = array_functions.vec_to_2d(o.y)
        o.fu = o.y
        return o

    def set_params(self, **kwargs):
        super(ScikitLearnMethod,self).set_params(**kwargs)
        self.skl_method.set_params(**kwargs)

    def _skl_method_name(self):
        return repr(self.skl_method).split('(')[0]

    @property
    def prefix(self):
        return "SKL-" + ScikitLearnMethod._short_name_dict[self._skl_method_name()]

class SKLRidgeRegression(ScikitLearnMethod):
    def __init__(self,configs=None):
        super(SKLRidgeRegression, self).__init__(configs, linear_model.Ridge())
        self.cv_params['alpha'] = 10**np.asarray(range(-8,8),dtype='float64')
        self.set_params(alpha=0,fit_intercept=True,normalize=True,tol=1e-12)
        self.set_params(solver='auto')

        useStandardScale = True
        if useStandardScale:
            self.set_params(normalize=False)
            self.transform = StandardScaler()

    def predict_loo(self, data):
        d = data.get_subset(data.is_train & data.is_labeled)
        y = np.zeros(d.n)
        for i in range(d.n):
            xi = d.x[i,:]
            d.y[i] = np.nan
            self.train(d)
            o_i = self.predict(d)
            y[i] = o_i.y[i]
            d.reveal_labels(i)
        o = Output(d)
        o.fu = y
        o.y = y
        return o

class SKLLogisticRegression(ScikitLearnMethod):
    def __init__(self,configs=None):
        super(SKLLogisticRegression, self).__init__(configs, linear_model.LogisticRegression())
        self.cv_params['C'] = 10**np.asarray(list(reversed(range(-5, 5))),dtype='float64')
        self.set_params(C=0,fit_intercept=True,penalty='l2')

    def predict(self, data):
        assert False, 'Incorporate probabilities?'
        o = Output(data)
        o.y = self.skl_method.predict(data.x)
        return o

class SKLKNN(ScikitLearnMethod):
    def __init__(self,configs=None):
        super(SKLKNN, self).__init__(configs, neighbors.KNeighborsClassifier())
        self.cv_params['n_neighbors'] = np.asarray(list(reversed([1,3,5,15,31])))
        #self.set_params(metric=metrics.CosineDistanceMetric())
        self.set_params(algorithm='brute')

    def train(self, data):
        labeled_train = data.labeled_training_data()
        #self.skl_method.fit(array_functions.try_toarray(labeled_train.x), labeled_train.y)
        self.skl_method.fit(array_functions.try_toarray(labeled_train.x), labeled_train.y)

    def predict(self, data):
        o = Output(data)
        o.y = self.skl_method.predict(array_functions.try_toarray(data.x))
        return o

class SKLGuessClassifier(ScikitLearnMethod):
    def __init__(self,configs=None):
        assert False, 'Test this'
        super(SKLGuessClassifier, self).__init__(configs,dummy.DummyClassifier('uniform'))

class SKLMeanRegressor(ScikitLearnMethod):
    def __init__(self,configs=None):
        #assert False, 'Test this'
        super(SKLMeanRegressor, self).__init__(configs,dummy.DummyRegressor('mean'))

'''
class PyQtFitMethod(Method):
    _short_name_dict = {
        'NW': 'NW'
    }

    def __init__(self,configs=MethodConfigs(),skl_method=None):
        super(PyQtFitMethod, self).__init__(configs)
        self.pyqtfit_method = nonparam_regression.NonParamRegression
        self.model = None

    def train(self, data):
        labeled_train = data.labeled_training_data()
        self.model = self.pyqtfit_method(
            labeled_train.x,
            labeled_train.y,
            method=npr_methods.SpatialAverage()
        )
        self.model.fit()
        self.model.evaluate(labeled_train.x)
        pass

    def predict(self, data):
        o = Output(data)
        assert False
        o.y = self.model.evaluate(data.x)
        return o

    def set_params(self, **kwargs):
        super(ScikitLearnMethod,self).set_params(**kwargs)

    def _pyqtfit_method_name(self):
        assert False
        return repr(self.pyqtfit_method).split('(')[0]

    @property
    def prefix(self):
        return "PyQtfit-" + PyQtFitMethod._short_name_dict[self._pyqtfit_method_name()]
'''


class RelativeRegressionMethod(Method):
    METHOD_ANALYTIC = 1
    METHOD_CVX = 2
    METHOD_RIDGE = 3
    METHOD_RIDGE_SURROGATE = 4
    METHOD_CVX_LOGISTIC = 5
    METHOD_CVX_LOGISTIC_WITH_LOG = 6
    METHOD_CVX_LOGISTIC_WITH_LOG_NEG = 7
    METHOD_CVX_LOGISTIC_WITH_LOG_SCALE = 8
    METHOD_CVX_NEW_CONSTRAINTS = 9
    CVX_METHODS = {
        METHOD_CVX,
        METHOD_CVX_LOGISTIC,
        METHOD_CVX_LOGISTIC_WITH_LOG,
        METHOD_CVX_LOGISTIC_WITH_LOG_NEG,
        METHOD_CVX_LOGISTIC_WITH_LOG_SCALE
    }
    CVX_METHODS_LOGISTIC = {
        METHOD_CVX_LOGISTIC,
        METHOD_CVX_LOGISTIC_WITH_LOG,
        METHOD_CVX_LOGISTIC_WITH_LOG_NEG,
        METHOD_CVX_LOGISTIC_WITH_LOG_SCALE
    }
    CVX_METHODS_LOGISTIC_WITH_LOG = {
        METHOD_CVX_LOGISTIC_WITH_LOG,
        METHOD_CVX_LOGISTIC_WITH_LOG_NEG,
        METHOD_CVX_LOGISTIC_WITH_LOG_SCALE
    }
    METHOD_NAMES = {
        METHOD_ANALYTIC: 'analytic',
        METHOD_CVX: 'cvx',
        METHOD_RIDGE: 'ridge',
        METHOD_RIDGE_SURROGATE: 'ridge-surr',
        METHOD_CVX_LOGISTIC: 'cvx-log',
        METHOD_CVX_LOGISTIC_WITH_LOG: 'cvx-log-with-log',
        METHOD_CVX_LOGISTIC_WITH_LOG_NEG: 'cvx-log-with-log-neg',
        METHOD_CVX_LOGISTIC_WITH_LOG_SCALE: 'cvx-log-with-log-scale',
        METHOD_CVX_NEW_CONSTRAINTS: 'cvx-constraints'
    }
    def __init__(self,configs=MethodConfigs()):
        super(RelativeRegressionMethod, self).__init__(configs)
        self.can_use_test_error_for_model_selection = True
        self.cv_params['C'] = 10**np.asarray(list(reversed(range(-8,8))),dtype='float64')
        self.cv_params['C2'] = 10**np.asarray(list(reversed(range(-8,8))),dtype='float64')
        self.w = None
        self.b = None
        self.transform = StandardScaler()
        self.add_random_pairwise = True
        self.use_pairwise = configs.use_pairwise
        self.num_pairwise = configs.num_pairwise
        self.use_test_error_for_model_selection = True
        self.no_linear_term = True
        self.neg_log = False
        self.prob = None
        self.solver = None
        self.solver = cvx.SCS
        self.method = RelativeRegressionMethod.METHOD_CVX_LOGISTIC_WITH_LOG

        if not self.use_pairwise:
            self.cv_params['C2'] = np.asarray([0])

    def train(self, data):
        if self.add_random_pairwise:
            data.pairwise_relationships = set()
            I = data.is_train & ~data.is_labeled
            sampled_pairs = array_functions.sample_pairs(I.nonzero()[0], self.num_pairwise)
            for i,j in sampled_pairs:
                pair = (i,j)
                if data.true_y[j] <= data.true_y[i]:
                    pair = (j,i)
                #data.pairwise_relationships.add(pair)
                x1 = data.x[pair[0],:]
                x2 = data.x[pair[1],:]
                data.pairwise_relationships.add(PairwiseConstraint(x1,x2))
                #data.pairwise_relationships.add(pair)
        is_labeled_train = data.is_train & data.is_labeled
        labeled_train = data.labeled_training_data()
        x = labeled_train.x
        y = labeled_train.y
        x_orig = x
        x = self.transform.fit_transform(x, y)

        use_ridge = self.method in {
            RelativeRegressionMethod.METHOD_RIDGE,
            RelativeRegressionMethod.METHOD_RIDGE_SURROGATE
        }
        n, p = x.shape
        if use_ridge:
            ridge_reg = SKLRidgeRegression(self.configs)
            ridge_reg.set_params(alpha=self.C)
            ridge_reg.set_params(normalize=False)
            '''
            d = deepcopy(data)
            d.x[is_labeled_train,:] = x
            ridge_reg.train(d)
            '''
            ridge_reg.train(data)
            w_ridge = array_functions.vec_to_2d(ridge_reg.skl_method.coef_)
            b_ridge = ridge_reg.skl_method.intercept_
            self.w = w_ridge
            self.b = b_ridge
            self.ridge_reg = ridge_reg
        elif self.method == RelativeRegressionMethod.METHOD_ANALYTIC:
            x_bias = np.hstack((x,np.ones((n,1))))
            A = np.eye(p+1)
            A[p,p] = 0
            XX = x_bias.T.dot(x_bias)
            v = np.linalg.lstsq(XX + self.C*A,x_bias.T.dot(y))
            w_anal = array_functions.vec_to_2d(v[0][0:p])
            b_anal = v[0][p]
            self.w = w_anal
            self.b = b_anal
        elif self.method in RelativeRegressionMethod.CVX_METHODS:
            w = cvx.Variable(p)
            b = cvx.Variable(1)
            loss = cvx.sum_entries(
                cvx.power(
                    x*w + b - y,
                    2
                )
            )
            reg = cvx.norm(w)**2
            pairwise_reg2 = 0
            assert self.no_linear_term

            if self.method == RelativeRegressionMethod.METHOD_CVX_NEW_CONSTRAINTS:
                for c in data.pairwise_relationships:
                    c.transform(self.transform)
                    pairwise_reg2 += c.to_cvx(w)
            else:
                #for i,j in data.pairwise_relationships:
                for p in data.pairwise_relationships:
                    #x1 <= x2
                    #x1 = self.transform.transform(data.x[i,:])
                    #x2 = self.transform.transform(data.x[j,:])
                    x1 = self.transform.transform(p.x[0])
                    x2 = self.transform.transform(p.x[1])
                    if self.method == RelativeRegressionMethod.METHOD_CVX:
                        pairwise_reg += (x1 - x2)*w
                    elif self.method in RelativeRegressionMethod.CVX_METHODS_LOGISTIC:
                        a = (x1 - x2)*w
                        if self.method == RelativeRegressionMethod.METHOD_CVX_LOGISTIC:
                            pairwise_reg += self.C2*a
                        elif self.method in RelativeRegressionMethod.CVX_METHODS_LOGISTIC_WITH_LOG:
                            #pairwise_reg += self.C2*a
                            if self.C2 == 0:
                                continue
                            a2 = (x1 - x2)*w
                            if self.method == RelativeRegressionMethod.METHOD_CVX_LOGISTIC_WITH_LOG_SCALE:
                                a2 *= self.C2
                            if self.method == RelativeRegressionMethod.METHOD_CVX_LOGISTIC_WITH_LOG_NEG or self.neg_log:
                                a2 = -a2
                            from utility import cvx_logistic
                            a3 = cvx_logistic.logistic(a2)
                            if self.method == RelativeRegressionMethod.METHOD_CVX_LOGISTIC_WITH_LOG:
                                pass
                                #a3 *= self.C2
                            pairwise_reg2 += a3
                    else:
                        assert False, 'Unknown CVX Method'

            warm_start = self.prob is not None and self.warm_start
            if warm_start:
                prob = self.prob
                self.C_param.value = self.C
                self.C2_param.value = self.C2
                w = self.w_var
                b = self.b_var
            else:
                constraints = []
                self.C_param = cvx.Parameter(sign='positive', value=self.C)
                self.C2_param = cvx.Parameter(sign='positive', value=self.C2)
                obj = cvx.Minimize(loss + self.C_param*reg + self.C2_param*pairwise_reg2)
                prob = cvx.Problem(obj,constraints)
                self.w_var = w
                self.b_var = b

            assert prob.is_dcp()
            print_messages = False
            if print_messages:
                timer.tic()
            try:
                #ret = prob.solve(cvx.ECOS, False, {'warm_start': warm_start})
                ret = prob.solve(self.solver, False, {'warm_start': warm_start})
                w_value = w.value
                b_value = b.value
                #print prob.status
                assert w_value is not None and b_value is not None
                #print a.value
                #print b.value
            except Exception as e:
                print e
                #print 'cvx status: ' + str(prob.status)
                k = 0
                w_value = k*np.zeros((p,1))
                b_value = 0
            if print_messages:
                print 'params: ' + str(self.C) + ',' + str(self.C2)
                timer.toc()
            self.prob = prob
            self.w = w_value
            self.b = b_value
            '''
            obj2 = cvx.Minimize(loss + self.C*reg)
            try:
                prob2 = cvx.Problem(obj2, constraints)
                prob2.solve()
                w2 = w.value
                b2 = b.value
                print 'b error: ' + str(array_functions.relative_error(b_value,b2))
                print 'w error: ' + str(array_functions.relative_error(w_value,w2))
                print 'pairwise_reg value: ' + str(pairwise_reg.value)
            except:
                pass
            '''
        '''
        print 'w rel error: ' + str(array_functions.relative_error(w_value,w_ridge))
        #print 'b rel error: ' + str(array_functions.relative_error(b_value,b_ridge))

        print 'w analytic rel error: ' + str(array_functions.relative_error(w_value,w_anal))
        #print 'b analytic rel error: ' + str(array_functions.relative_error(b_value,b_anal))
        print 'w norm: ' + str(norm(w_value))
        print 'w analytic norm: ' + str(norm(w_anal))
        print 'w ridge norm: ' + str(norm(w_ridge))
        assert self.b is not None
        '''

    def predict(self, data):
        o = Output(data)

        if self.method == RelativeRegressionMethod.METHOD_RIDGE_SURROGATE:
            o = self.ridge_reg.predict(data)
        else:
            x = self.transform.transform(data.x)
            y = x.dot(self.w) + self.b
            o.fu = y
            o.y = y
        return o

    @property
    def prefix(self):
        s = 'RelReg'
        if self.method != RelativeRegressionMethod.METHOD_CVX:
            s += '-' + RelativeRegressionMethod.METHOD_NAMES[self.method]
        if not self.use_pairwise:
            s += '-noPairwiseReg'
        else:
            if self.num_pairwise > 0 and self.add_random_pairwise:
                s += '-numRandPairs=' + str(int(self.num_pairwise))
            if self.no_linear_term:
                s += '-noLinear'
            if self.neg_log:
                s += '-negLog'
            if hasattr(self, 'solver'):
                s += '-solver=' + str(self.solver)
        if self.use_test_error_for_model_selection:
            s += '-TEST'
        return s