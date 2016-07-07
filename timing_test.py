import numpy as np
import cvxpy as cvx
from timer.timer import tic, toc
from mpi4py import MPI
from utility import mpi_utility
from utility import mpi_group_pool
from mpipool import core as mpipool

def run_test():
    num_iterations = 100
    pool = None
    comm = MPI.COMM_WORLD
    if comm.Get_size() > 1:
        #pool = mpi_group_pool.MPIGroupPool(debug=False, loadbalance=True, comms=mpi_comms)
        pool = mpipool.MPIPool(debug=False, loadbalance=True)

    if pool is None:
        for i in range(num_iterations):
            print str(i) + ' of ' + str(num_iterations)
            inv_test()
    else:
        args = [(i,) for i in range(num_iterations)]
        pool.map(inv_test, args)
        pool.close()
        pass

def inv_test(*args):
    size = (1000, 1000)
    X = np.random.uniform(-1, 1, size)
    C = 1e-3
    XX = X.T.dot(X) + C*np.eye(X.shape[1])
    np.linalg.inv(XX)

if __name__ == '__main__':
    comm = MPI.COMM_WORLD
    is_master = comm.Get_rank() == 0
    if is_master:
        tic()
    run_test()
    if is_master:
        toc()