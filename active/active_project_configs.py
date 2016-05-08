import methods.constrained_methods
import methods.local_transfer_methods
import methods.method

__author__ = 'Aubrey'
from collections import OrderedDict
from configs import base_configs as bc
import numpy as np
from data_sets import create_data_set
from loss_functions import loss_function
from data_sets import create_data_set
from utility import array_functions
from utility import helper_functions
from results_class import results as results_lib


#Command line arguments for ProjectConfigs
arguments = None
def create_project_configs():
    return ProjectConfigs()

pc_fields_to_copy = bc.pc_fields_to_copy + [
]
#data_set_to_use = bc.DATA_BOSTON_HOUSING
data_set_to_use = bc.DATA_SYNTHETIC_LINEAR_REGRESSION
#data_set_to_use = bc.DATA_ADIENCE_ALIGNED_CNN_1
#data_set_to_use = bc.DATA_WINE_RED

data_sets_for_exps = [data_set_to_use]

active_iterations = 2
active_items_per_iteration = 50
use_pairwise = True
num_pairwise = 10
pair_bound = .5

use_bound = False
num_bound = 10
use_quartiles = True

use_neighbor = False
num_neighbor = 10
use_min_pair_neighbor = True

use_test_error_for_model_selection = True

run_active_experiments = False

run_experiments = True
show_legend_on_all = True

max_rows = 3

synthetic_dim = 1
if helper_functions.is_laptop():
    use_pool = False
    pool_size = 1
else:
    use_pool = False
    pool_size = 1

class ProjectConfigs(bc.ProjectConfigs):
    def __init__(self, data_set=None, use_arguments=True):
        super(ProjectConfigs, self).__init__()
        self.project_dir = 'active'
        self.use_pool = use_pool
        self.pool_size = pool_size
        if run_active_experiments:
            self.method_results_class = results_lib.ActiveMethodResults
        if data_set is None:
            data_set = data_set_to_use
        self.set_data_set(data_set)
        self.num_splits = 30
        if use_arguments and arguments is not None:
            if arguments.num_labels is not None:
                self.overwrite_num_labels = arguments.num_labels
            if arguments.split_idx is not None:
                self.split_idx = arguments.split_idx
            pass

    def set_data_set(self, data_set):
        self.data_set = data_set
        if data_set == bc.DATA_BOSTON_HOUSING:
            self.set_boston_housing()
            self.num_labels = [5, 10, 20]
            if run_active_experiments:
                self.num_labels = [5]
        elif data_set == bc.DATA_SYNTHETIC_LINEAR_REGRESSION:
            self.set_synthetic_linear_reg()
            self.num_labels = [10, 20, 40]
            if run_active_experiments:
                self.num_labels = [20]
        elif data_set == bc.DATA_ADIENCE_ALIGNED_CNN_1:
            self.set_adience_aligned_cnn_1()
            self.num_labels = [10, 20, 40]
            if run_active_experiments:
                self.num_labels = [20]
        elif data_set == bc.DATA_WINE_RED:
            self.set_wine_red()
            self.num_labels = [10, 20, 40]
            if run_active_experiments:
                self.num_labels = [20]


    def set_boston_housing(self):
        self.loss_function = loss_function.MeanSquaredError()
        self.cv_loss_function = loss_function.MeanSquaredError()
        self.data_dir = 'data_sets/boston_housing'
        self.data_name = 'boston_housing'
        self.results_dir = 'boston_housing'
        self.data_set_file_name = 'split_data.pkl'

    def set_synthetic_linear_reg(self):
        self.loss_function = loss_function.MeanSquaredError()
        self.cv_loss_function = loss_function.MeanSquaredError()
        self.data_dir = 'data_sets/synthetic_linear_reg500-50-1'
        self.data_name = 'synthetic_linear_reg500-50-1'
        self.results_dir = 'synthetic_linear_reg500-50-1'
        self.data_set_file_name = 'split_data.pkl'

    def set_adience_aligned_cnn_1(self):
        self.loss_function = loss_function.MeanSquaredError()
        self.cv_loss_function = loss_function.MeanSquaredError()
        self.data_dir = 'data_sets/adience_aligned_cnn_1_per_instance_id'
        self.data_name = 'adience_aligned_cnn_1_per_instance_id'
        self.results_dir = 'adience_aligned_cnn_1_per_instance_id'
        self.data_set_file_name = 'split_data.pkl'

    def set_wine_red(self):
        self.loss_function = loss_function.MeanSquaredError()
        self.cv_loss_function = loss_function.MeanSquaredError()
        s = 'wine-red'
        self.data_dir = 'data_sets/' + s
        self.data_name = s
        self.results_dir = s
        self.data_set_file_name = 'split_data.pkl'


class MainConfigs(bc.MainConfigs):
    def __init__(self, pc):
        super(MainConfigs, self).__init__()
        #pc = create_project_configs()
        self.copy_fields(pc,pc_fields_to_copy)
        from methods import method
        from methods import active_methods
        method_configs = MethodConfigs(pc)
        method_configs.active_iterations = active_iterations
        method_configs.active_items_per_iteration = active_items_per_iteration
        method_configs.metric = 'euclidean'

        method_configs.use_pairwise = use_pairwise
        method_configs.num_pairwise = num_pairwise
        method_configs.pair_bound = pair_bound

        method_configs.use_bound = use_bound
        method_configs.num_bound = num_bound
        method_configs.use_quartiles = use_quartiles

        method_configs.use_neighbor = use_neighbor
        method_configs.num_neighbor = num_neighbor
        method_configs.use_min_pair_neighbor = use_min_pair_neighbor

        method_configs.use_test_error_for_model_selection = use_test_error_for_model_selection

        #active = active_methods.ActiveMethod(method_configs)
        active = active_methods.RelativeActiveMethod(method_configs)
        active.base_learner = methods.method.RelativeRegressionMethod(method_configs)
        relative_reg = methods.method.RelativeRegressionMethod(method_configs)
        ridge_reg = method.SKLRidgeRegression(method_configs)
        mean_reg = method.SKLMeanRegressor(method_configs)
        if run_active_experiments:
            self.learner = active
        else:
            self.learner = relative_reg
            #self.learner = ridge_reg
            #self.learner = mean_reg

class MethodConfigs(bc.MethodConfigs):
    def __init__(self, pc):
        super(MethodConfigs, self).__init__()
        self.copy_fields(pc,pc_fields_to_copy)

class VisualizationConfigs(bc.VisualizationConfigs):
    def __init__(self, data_set=None):
        super(VisualizationConfigs, self).__init__()
        pc = ProjectConfigs(data_set)
        self.copy_fields(pc,pc_fields_to_copy)
        self.files = OrderedDict()
        if run_active_experiments:
            self.files['RelActiveRandom+SKL-RidgeReg.pkl'] = 'Random Pairwise, SKLRidge'
            self.files['ActiveRandom+SKL-RidgeReg.pkl'] = 'Random, SKLRidge'
            self.files['RelActiveRandom+RelReg-cvx-log-with-log-noLinear-TEST.pkl'] = 'TEST: RandomPairwise, RelReg'
        else:
            self.files['RelReg-cvx-constraints-noPairwiseReg.pkl'] = 'Ridge Regression'
            base_file_name = 'RelReg-cvx-constraints-%s=%s-solver=SCS'
            use_test = False
            sizes = []
            #sizes.append(10)
            sizes.append(50)
            sizes.append(100)
            methods = []
            #methods.append(('numRandPairs','RelReg, %s pairs'))
            methods.append(('numRandBound', 'RelReg, %s bounds'))
            #methods.append(('numMinNeighbor', 'RelReg, %s min neighbors'))
            methods.append(('numRandQuartiles', 'RelReg, %s quartiles'))
            for file_suffix, legend_name in methods:
                for size in sizes:
                    key = base_file_name % (file_suffix, str(size))
                    legend = legend_name % str(size)
                    if use_test:
                        key += '-TEST'
                        legend = 'TEST: ' + legend
                    key += '.pkl'
                    self.files[key] = legend

        self.figsize = (7,7)
        self.borders = (.1,.9,.9,.1)
        self.data_set_to_use = pc.data_set
        self.title = bc.data_name_dict.get(self.data_set_to_use, 'Unknown Data Set')
        self.show_legend_on_all = show_legend_on_all
        self.x_axis_string = 'Number of labeled instances'


class BatchConfigs(bc.BatchConfigs):
    def __init__(self, pc):
        super(BatchConfigs, self).__init__()
        self.config_list = [MainConfigs(pc)]
        from experiment.experiment_manager import MethodExperimentManager
        self.method_experiment_manager_class = MethodExperimentManager