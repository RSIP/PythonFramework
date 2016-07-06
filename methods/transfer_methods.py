__author__ = 'Aubrey'
import copy
from copy import deepcopy
import numpy as np
from numpy.linalg import norm
import method
from preprocessing import NanLabelEncoding, NanLabelBinarizer
from data import data as data_lib
from sklearn.neighbors import KernelDensity
from sklearn.grid_search import GridSearchCV
from sklearn.preprocessing import LabelEncoder
from sklearn.preprocessing import StandardScaler
from results_class.results import Output
import cvxpy as cvx
import scipy

class TargetTranfer(method.Method):
    def __init__(self, configs=None):
        super(TargetTranfer, self).__init__(configs)
        self.base_learner = method.SKLLogisticRegression(configs)
        self.cv_params = {}
        self.base_learner.experiment_results_class = self.experiment_results_class

    def train(self, data):
        self.base_learner.train_and_test(data)

    def train_and_test(self, data):
        #data_copy2 = self._prepare_data(data,include_unlabeled=True)
        #results2 = super(TargetTranfer, self).train_and_test(data_copy2)
        data_copy = self._prepare_data(data,include_unlabeled=True)
        #data_copy = data_copy.get_with_labels(self.configs.target_labels)
        #data_copy = data_copy.get_transfer_subset(self.configs.target_labels, include_unlabeled=True)
        results = super(TargetTranfer, self).train_and_test(data_copy)
        #a = results.prediction.fu - results2.prediction.fu[data_copy2.is_labeled,:]
        #print str(a.any())
        return results

    def _prepare_data(self, data, include_unlabeled=True):
        target_labels = self.configs.target_labels
        data_copy = data.get_transfer_subset(target_labels,include_unlabeled=include_unlabeled)

        data_copy = data_copy.get_subset(data_copy.is_target)
        is_source = ~data_copy.has_true_label(target_labels)
        data_copy.type[is_source] = data_lib.TYPE_SOURCE
        data_copy.is_train[is_source] = True
        #data_copy = data.get_with_labels(target_labels)
        return data_copy

    def predict(self, data):
        o = self.base_learner.predict(data)
        if self.label_transform is not None:
            o.true_y = self.label_transform.transform(o.true_y)
        return o

    @method.Method.estimated_error.getter
    def estimated_error(self):
        return self.base_learner.estimated_error

    @property
    def prefix(self):
        return 'TargetTransfer+' + self.base_learner.prefix

class FuseTransfer(TargetTranfer):
    def __init__(self, configs=None):
        super(FuseTransfer, self).__init__(configs)
        self.use_oracle = False
        #self.target_weight_scale = None
        self.target_weight_scale = .75
        self.label_transform = NanLabelBinarizer()

    def train(self, data):
        is_labeled_train = data.is_labeled & data.is_train
        n_labeled_target = (data.is_train & is_labeled_train).sum()
        n_labeled_source = (data.is_train & is_labeled_train).sum()
        data.instance_weights = np.ones(data.n)
        if self.target_weight_scale is not None:
            assert 0 <= self.target_weight_scale <= 1
            data.instance_weights[data.is_source] /= n_labeled_source
            data.instance_weights[data.is_target] /= n_labeled_target
            data.instance_weights[data.is_target] *= self.target_weight_scale
            data.instance_weights[data.is_source] *= (1-self.target_weight_scale)
        y_old = data.y
        if self.label_transform is not None:
            data.y = self.label_transform.fit_transform(data.y)
        super(FuseTransfer, self).train(data)
        data.y = y_old

    def _prepare_data(self, data,include_unlabeled=True):
        source_labels = self.configs.source_labels
        target_labels = self.configs.target_labels
        data_copy = copy.deepcopy(data)
        if data.data_set_ids is not None:
            assert source_labels is None
            assert target_labels is None
            data_copy.type[data_copy.data_set_ids > 0] = data_lib.TYPE_SOURCE
            return data_copy
        #source_inds = array_functions.find_set(data_copy.true_y,source_labels)
        if self.use_oracle:
            oracle_labels = self.configs.oracle_labels
            data_copy = data_copy.get_transfer_subset(
                np.concatenate((oracle_labels.ravel(),target_labels.ravel())),
                include_unlabeled=True
            )
        data_copy.data_set_ids = np.zeros(data_copy.n)
        for i, s in enumerate(source_labels):
            source_inds = data_copy.get_transfer_inds(s)
            if not data_copy.is_regression:
                data_copy.change_labels(s, target_labels)
            data_copy.type[source_inds] = data_lib.TYPE_SOURCE
            data_copy.is_train[source_inds] = True
            data_copy.data_set_ids[source_inds] = i+1
        data_copy.reveal_labels(data_copy.is_source)
        return data_copy

    @property
    def prefix(self):
        s = 'FuseTransfer+' + self.base_learner.prefix
        if 'target_weight_scale' in self.__dict__ and self.target_weight_scale is not None:
            s += '-tws=' + str(self.target_weight_scale)
        if 'use_oracle' in self.__dict__ and self.use_oracle:
            s += '-Oracle'
        return s


class HypothesisTransfer(FuseTransfer):

    WEIGHTS_ALL = 0
    WEIGHTS_JUST_TARGET = 1
    WEIGHTS_JUST_OPTIMAL = 2
    def __init__(self, configs=None):
        super(HypothesisTransfer, self).__init__(configs)
        self.cv_params = {
            'C': self.create_cv_params(-5,5),
            'C2': self.create_cv_params(-5, 5),
            'C3': self.create_cv_params(-5, 5),
        }
        self.w = None
        self.b = None

        #self.base_source_learner = method.SKLRidgeClassification(deepcopy(configs))
        self.base_source_learner = None
        self.label_transform = None

        self.source_w = []
        self.transform = StandardScaler()
        #self.transform = None
        self.use_oracle = False
        self.tune_C = False
        #self.weight_type = HypothesisTransfer.WEIGHTS_ALL
        #self.weight_type = HypothesisTransfer.WEIGHTS_JUST_TARGET
        self.weight_type = HypothesisTransfer.WEIGHTS_JUST_OPTIMAL
        if hasattr(configs, 'weight_type'):
            self.weight_type = configs.weight_type
        self.c_value = None
        self.use_test_error_for_model_selection = configs.use_test_error_for_model_selection
        if self.weight_type == HypothesisTransfer.WEIGHTS_JUST_TARGET:
            del self.cv_params['C2']
            del self.cv_params['C3']
            self.C2 = 0
            self.C3 = 0
        elif not getattr(self, 'tune_C', True):
            del self.cv_params['C']
            self.C = 0


    def train_and_test(self, data):
        #data = data.get_subset(data.data_set_ids == 0)
        source_labels = self.configs.source_labels
        data = self._prepare_data(data)
        target_data = data.get_subset(data.data_set_ids == 0)
        #self.cv_params['C'] = np.zeros(1)
        if self.weight_type != HypothesisTransfer.WEIGHTS_JUST_TARGET:
            base_configs = deepcopy(self.configs)
            base_configs.weight_type = HypothesisTransfer.WEIGHTS_JUST_TARGET
            self.base_source_learner = HypothesisTransfer(base_configs)
            self.base_source_learner.cv_use_data_type = False
            self.base_source_learner.use_test_error_for_model_selection = False
            #self.base_source_learner.cv_params['C'] = np.zeros(1)

            #for i, s in enumerate(source_labels):
            for data_set_id in np.unique(data.data_set_ids):
                if data_set_id == 0:
                    continue
                #source_inds = data.get_transfer_inds(s)
                source_data = data.get_subset(data.data_set_ids == data_set_id)
                source_data.data_set_ids[:] = 0
                source_data.is_target[:] = True
                self.base_source_learner.train_and_test(source_data)
                best_params = self.base_source_learner.best_params
                w = np.squeeze(self.base_source_learner.w)
                w /= np.linalg.norm(w)
                b = self.base_source_learner.b
                self.source_w.append(w)
                pass
            ws1 = self.source_w[0]
            ws2 = self.source_w[1]
            target_data_copy = deepcopy(target_data)
            target_data_copy.is_train[:] = True
            target_data_copy.y = target_data_copy.true_y
            self.base_source_learner.train_and_test(target_data_copy)
            wt = np.squeeze(self.base_source_learner.w)
            wt /= np.linalg.norm(wt)
            d1 = norm(ws1-wt)
            d2 = norm(ws2-wt)
            #print 'using wt!  Change this back'
            #self.source_w[0] = wt/norm(wt)
            #self.source_w[1] = wt / norm(wt)
            self.source_w[0] = ws1
            self.source_w[1] = ws2
            pass

        o = super(HypothesisTransfer, self).train_and_test(target_data)
        print 'c: ' + str(np.squeeze(self.c_value))
        return o

    def estimate_c(self, data):
        x = data.x[data.is_labeled & data.is_train]
        if self.transform is not None:
            x = self.transform.fit_transform(x)
        y = data.y[data.is_labeled]
        if self.label_transform is not None:
            y = self.label_transform.fit_transform(y)
        n = y.size
        p = data.p
        c = cvx.Variable(len(self.source_w))
        ws1 = self.source_w[0]
        ws2 = self.source_w[1]

        constraints = [c >= 0]
        if self.weight_type == HypothesisTransfer.WEIGHTS_JUST_OPTIMAL:
            constraints.append(c[1] == 0)
        loss = 0
        for i in range(y.size):
            xi = x[i, :]
            yi = y[i]
            x_mi = np.delete(x, i, axis=0)
            y_mi = np.delete(y, i, axis=0)
            b_mi = y_mi.mean()
            A = x_mi.T.dot(x_mi) + (self.C + self.C2) * np.eye(p)
            k = x_mi.T.dot(y_mi) - x_mi.T.sum(1) * b_mi + self.C2 * (ws1 * c[0] + ws2 * c[1])
            # w_mi = np.linalg.solve(A, k)
            w_mi = scipy.linalg.inv(A) * k
            loss += cvx.power(w_mi.T * xi + b_mi - yi, 2)
            #loss += cvx.max_elemwise(1 - (w_mi.T * xi + b_mi)*yi, 0)
        # reg = cvx.power(cvx.norm2(c),2)
        reg = cvx.norm1(c)
        obj = cvx.Minimize(loss + self.C3 * reg)
        prob = cvx.Problem(obj, constraints)
        assert prob.is_dcp()
        try:
            prob.solve(cvx.SCS)
            c_value = np.asarray(c.value)
        except Exception as e:
            print str(e)
            c_value = np.zeros(p)
        # c_value[np.abs(c_value) <= 1e-4] = 0
        # assert np.all(c_value >= 0)
        c_value[c_value < 0] = 0
        return c_value

    def train(self, data):
        x = data.x[data.is_labeled & data.is_train]
        if self.transform is not None:
            x = self.transform.fit_transform(x)
        y = data.y[data.is_labeled]
        if self.label_transform is not None:
            y = self.label_transform.fit_transform(y)
        n = y.size
        p = data.p
        self.b = y.mean()

        #print str(np.squeeze(c_value))
        if self.weight_type == HypothesisTransfer.WEIGHTS_JUST_TARGET:
            c_value = np.zeros(2)
            ws1 = 0
            ws2 = 0
        else:
            c_value = self.estimate_c(data)
            ws1 = self.source_w[0]
            ws2 = self.source_w[1]
        A = x.T.dot(x) + (self.C + self.C2)*np.eye(p)
        k = x.T.dot(y) - x.T.sum(1)*self.b + self.C2*(ws1*c_value[0] + ws2*c_value[1])
        self.w = np.linalg.solve(A, k)
        self.c_value = c_value
        pass

    def predict(self, data):
        o = Output(data)
        x = data.x
        if self.transform is not None:
            x = self.transform.transform(x)
        y = x.dot(self.w) + self.b
        #y = np.round(y)
        #y[y >= .5] = 1
        #y[y < .5] = 0
        y = np.sign(y)
        o.y = y
        o.fu = y
        if self.label_transform is not None:
            o.true_y = self.label_transform.transform(o.true_y)

        if not self.running_cv:
            is_correct = (o.y == o.true_y)
            mean_train = is_correct[o.is_train].mean()
            mean_test = is_correct[o.is_test].mean()
            mean_train_labeled = is_correct[data.is_train & data.is_labeled].mean()
            pass
        return o

    @property
    def prefix(self):
        s = 'HypTransfer'
        weight_type = getattr(self, 'weight_type', HypothesisTransfer.WEIGHTS_ALL)
        if weight_type == HypothesisTransfer.WEIGHTS_JUST_TARGET:
            s += '-target'
        else:
            if weight_type == HypothesisTransfer.WEIGHTS_JUST_OPTIMAL:
                s += '-optimal'
            if not getattr(self, 'tune_C', False):
                s += '-noC'
        if getattr(self, 'use_test_error_for_model_selection', False):
            s += '-TEST'
        return s


class ModelSelectionTransfer(method.ModelSelectionMethod):
    def __init__(self, configs=None):
        super(ModelSelectionTransfer, self).__init__(configs)
        self.methods.append(TargetTranfer(configs))
        self.methods.append(FuseTransfer(configs))
        for m in self.methods:
            m.base_learner = method.NadarayaWatsonMethod(configs)

    @property
    def prefix(self):
        return 'ModelSelTransfer'

class ReweightedTransfer(method.Method):
    def __init__(self, configs=None):
        super(ReweightedTransfer, self).__init__(configs)
        self.target_kde = None
        self.source_kde = None
        self.kde_bandwidths = 10**np.asarray(range(-6,6),dtype='float64')
        c = deepcopy(configs)
        c.temp_dir = None
        self.base_learner = method.NadarayaWatsonMethod(configs)
        self.cv_params = {
            'B': np.asarray([2, 4, 8, 16, 32])
        }
        self.base_learner_cv_keys = []

    def train_and_test(self, data):
        assert self.base_learner.can_use_instance_weights
        target_data = data.get_transfer_subset(self.configs.target_labels.ravel(),include_unlabeled=False)
        source_data = data.get_transfer_subset(self.configs.source_labels.ravel(), include_unlabeled=False)
        is_source = data.get_transfer_inds(self.configs.source_labels.ravel())
        data.type[is_source] = data_lib.TYPE_SOURCE

        x_T = target_data.x
        x_S = source_data.x

        params = {'bandwidth': self.kde_bandwidths}
        grid = GridSearchCV(KernelDensity(), params)
        grid.fit(x_T)
        self.target_kde = deepcopy(grid.best_estimator_)
        grid.fit(x_S)
        self.source_kde = deepcopy(grid.best_estimator_)

        old_cv = self.cv_params.copy()
        old_base_cv = self.base_learner.cv_params.copy()

        assert set(old_cv.keys()) & set(old_base_cv.keys()) == set()
        self.cv_params.update(self.base_learner.cv_params)
        self.base_learner_cv_keys = old_base_cv.keys()

        o = super(ReweightedTransfer, self).train_and_test(data)
        self.cv_params = old_cv
        self.base_learner.cv_params = old_base_cv
        return o

    def train(self, data):
        I = data.is_labeled
        weights = self.get_weights(data.x)
        assert np.all(weights >=0 )
        weights[weights > self.B] = self.B
        data.instance_weights = weights
        for key in self.base_learner_cv_keys:
            setattr(self.base_learner, key, getattr(self, key))
        self.base_learner.train(data)

    def get_weights(self, x):
        target_scores = np.exp(self.target_kde.score_samples(x))
        source_scores = np.exp(self.source_kde.score_samples(x))
        return target_scores / source_scores

    def predict(self, data):
        data.instance_weights = self.get_weights(data.x)
        return self.base_learner.predict(data)

    @property
    def prefix(self):
        return 'CovShift'

