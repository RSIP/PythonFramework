import scipy
from methods import method
from configs import base_configs
from utility import array_functions
import numpy as np
from numpy.linalg import norm
import math
from results_class import results
from data import data as data_lib
from loss_functions import loss_function
import cvxpy as cvx
import copy
from utility import cvx_functions
from methods import scipy_opt_methods

class CombinePredictionsDelta(scipy_opt_methods.ScipyOptNonparametricHypothesisTransfer):
    def __init__(self, configs=None):
        super(CombinePredictionsDelta, self).__init__(configs)
        self.use_radius = None
        self.C3 = None
        self.use_l2 = True
        self.constant_b = configs.constant_b

    def train(self, data):
        y_s = np.squeeze(data.y_s[:,0])
        y_t = np.squeeze(data.y_t[:,0])
        y = data.y
        if self.constant_b:
            self.g = (y_t - y_s).mean()
            return

        is_labeled = data.is_labeled
        labeled_inds = is_labeled.nonzero()[0]
        n_labeled = len(labeled_inds)
        g = cvx.Variable(n_labeled)
        if self.use_radius:
            W = array_functions.make_graph_radius(data.x[is_labeled,:], self.radius, self.configs.metric)
        else:
            W = array_functions.make_graph_adjacent(data.x[is_labeled,:], self.configs.metric)

        if W.sum() > 0:
            W = W / W.sum()
        if self.use_fused_lasso:
            reg = cvx_functions.create_fused_lasso(W, g)
        else:
            #assert False, 'Make Laplacian!'
            reg =0
            if W.any():
                L = array_functions.make_laplacian_with_W(W)
                reg = cvx.quad_form(g,L)
        err = self.C3*y_t + (1 - self.C3)*(y_s+g) - y
        #err = y_s + g - y
        err_abs = cvx.abs(err)
        err_l2 = cvx.power(err,2)
        err_huber = cvx.huber(err, 2)
        if self.use_l2:
            loss = cvx.sum_entries(err_l2)
        else:
            loss = cvx.sum_entries(err_huber)
        #constraints = [g >= -2, g <= 2]
        #constraints = [g >= -4, g <= 0]
        #constraints = [g >= 4, g <= 4]
        constraints = [f(g) for f in self.configs.constraints]
        obj = cvx.Minimize(loss + self.C*reg + self.C2*cvx.norm(g))
        prob = cvx.Problem(obj,constraints)

        assert prob.is_dcp()
        try:
            prob.solve()
            g_value = np.reshape(np.asarray(g.value),n_labeled)
        except:
            k = 0
            #assert prob.status is None
            print 'CVX problem: setting g = ' + str(k)
            print '\tC=' + str(self.C)
            print '\tC2=' + str(self.C2)
            print '\tC3=' + str(self.C3)
            g_value = k*np.ones(n_labeled)
        labeled_train_data = data.get_subset(labeled_inds)
        assert labeled_train_data.y.shape == g_value.shape
        labeled_train_data.is_regression = True
        labeled_train_data.y = g_value
        labeled_train_data.true_y = g_value

        self.g_nw.train_and_test(labeled_train_data)

    def combine_predictions(self,x,y_source,y_target):
        data = data_lib.Data()
        data.x = x
        data.is_regression = True
        if self.constant_b:
            g = self.g
        else:
            g = self.g_nw.predict(data).fu
        fu = self.C3*y_target + (1-self.C3)*(y_source + g)
        #fu = y_source + g
        return fu


    def predict_g(self, x):
        if self.constant_b:
            g = self.g
        else:
            g = super(CombinePredictionsDelta, self).predict_g(x)
        return g

    @property
    def prefix(self):
        s = 'DelTra'
        return s

class CombinePredictionsDeltaSMS(CombinePredictionsDelta):
    def __init__(self, configs=None):
        super(CombinePredictionsDeltaSMS, self).__init__(configs)
        self.g_nw = None
        self.include_scale = True

    def train(self, data):
        assert data.is_regression
        is_labeled = data.is_labeled
        y_s = data.y_s[is_labeled]
        y = data.y[is_labeled]
        assert not is_labeled.all()
        labeled_inds = is_labeled.nonzero()[0]
        n_labeled = len(labeled_inds)
        g = cvx.Variable(n_labeled)
        w = cvx.Variable(n_labeled)
        W_ll = array_functions.make_rbf(data.x[is_labeled,:], self.sigma, self.configs.metric)


        self.x = data.x[is_labeled,:]
        self.y = y

        self.R_ll = W_ll*np.linalg.inv(W_ll + self.C*np.eye(W_ll.shape[0]))
        R_ul = self.make_R_ul(data.x)
        err = y_s + self.R_ll*g - y
        err_l2 = cvx.power(err,2)
        reg = cvx.norm(R_ul*w - 1)
        loss = cvx.sum_entries(err_l2) + self.C2*reg
        constraints = []
        if not self.include_scale:
            constraints.append(w == 1)
        obj = cvx.Minimize(loss)
        prob = cvx.Problem(obj,constraints)

        assert prob.is_dcp()
        try:
            prob.solve()
            g_value = np.reshape(np.asarray(g.value),n_labeled)
            w_value = np.reshape(np.asarray(w.value),n_labeled)
        except:
            k = 0
            #assert prob.status is None
            print 'CVX problem: setting g = ' + str(k)
            print '\tC=' + str(self.C)
            print '\tC2=' + str(self.C2)
            print '\tsigma=' + str(self.sigma)
            g_value = k*np.ones(n_labeled)
            w_value = np.ones(n_labeled)
        self.g = g_value
        self.w = w_value

    def make_R_ul(self, x):
        W_ul = array_functions.make_rbf(x, self.sigma, self.configs.metric, self.x)
        R_ul = W_ul.dot(self.R_ll)
        return R_ul

    def predict_g(self, x):
        R_ul = self.make_R_ul(x)
        g = R_ul.dot(self.g)
        return g

    def predict_w(self, x):
        R_ul = self.make_R_ul(x)
        w = R_ul.dot(self.w)
        return w

    def combine_predictions(self,x,y_source,y_target):
        fu = np.multiply(self.predict_w(x), y_source) + self.predict_g(x)
        return fu

    @property
    def prefix(self):
        s = 'SMSTra'
        if getattr(self,'include_scale',False):
            s += '_scale'
        return s
