import jax
import jaxopt
import jax.numpy as np
import numpy
from jax import jit
import jaxlie
from jaxlie import SE2, SE3
from sample_point_clouds import get_rect, get_circle
import time
import scipy
import matplotlib.pyplot as plt

transforms_c = []
transforms_sq = []

def callback_fun(x):
    transforms_c.append(x[0])
    transforms_sq.append(x[1])

def sdf_sq(T, point):
    # transform point cloud
    T = SE2.from_xy_theta(T[0], T[1], 0.)
    T_inv = SE2.inverse(T)
    T_p = SE2.from_xy_theta(point[0], point[1], 0.)
    point_pos = np.array([(T_inv@T_p).translation()[0],
                            (T_inv@T_p).translation()[1]])
    
    # measure sdf at each point of transformed point cloud
    a = np.array([0., -1])
    b = np.array([0., 1])
    t = 2.
    p = point_pos
    l = np.linalg.norm(b-a)
    d = (b-a)/l
    q = (p-(a+b)*.5)
    q = np.array([[d[0],-d[1]],
                [d[1],d[0]]])@q
    q = np.abs(q)-np.array([l,t])*0.5
    sdf = np.linalg.norm(np.maximum(q, 0.)) + np.minimum(np.maximum(q[0],q[1]), 0.)
    return sdf


def sdf_c(T, point):
    # transform point cloud
    T = SE2.from_xy_theta(T[0], T[1], 0.)
    T_inv = SE2.inverse(T)
    T_p = SE2.from_xy_theta(point[0], point[1], 0.)
    point_pos = np.array([(T_inv@T_p).translation()[0],
                          (T_inv@T_p).translation()[1]])
    
    # measure sdf at each point of transformed point cloud
    r = 1.
    sdf = np.linalg.norm(point_pos) - r
    return sdf

#TODO: figure out indexing issue for 'index choice'
def sdf_t(T, point):
    T = SE2.from_xy_theta(T[0], T[1], 0.)
    T_inv = SE2.inverse(T)
    T_p = SE2.from_xy_theta(point[0], point[1], 0.)
    p = np.array([(T_inv@T_p).translation()[0],
                  (T_inv@T_p).translation()[1]])

    r = 1.
    k = np.sqrt(3.0)
    p_x = abs(p[0]) - r
    p_y = p[1] + r/k

    pos_point = np.array([p[0]-k*p[1],-k*p[0]-p[1]])/2.0
    neg_point = np.array([p_x, p_y])
    point_choice = [pos_point, neg_point]

    index_choice = np.argmax(np.array([p_x+k*p_y, 0.0]))
    point = point_choice[index_choice]

    p_clamp_x = np.min(np.array([np.max(np.array([point[0], -2.0*r])), 0.0]))
    p_clamp_y = point[1]
    p_clamp = np.array([p_clamp_x, p_clamp_y])

    return -np.linalg.norm((p_clamp))*np.sign(p_clamp[1])

batch_sdf_sq = jax.vmap(sdf_sq, in_axes=[None, 0])
batch_sdf_c = jax.vmap(sdf_c, in_axes=[None, 0])
batch_sdf_t = jax.vmap(sdf_t, in_axes=[None, 0])

def sum_sdf_seg_c(transform, point_cloud):
    sdf_array = batch_sdf_c(transform, point_cloud)
    cost = np.linalg.norm(sdf_array, ord = 1)
    return cost

def sum_sdf_seg_sq(transform, point_cloud):
    sdf_array = batch_sdf_sq(transform, point_cloud)
    cost = np.linalg.norm(sdf_array, ord = 1)
    return cost

def total_cost_c(transforms, point_clouds):
    cost_1 = np.linalg.norm(sum_sdf_seg_c(transforms[0], point_clouds[0]))
    cost_2 = np.linalg.norm(sum_sdf_seg_c(transforms[1], point_clouds[1]))
    return cost_1 + cost_2

def total_cost_sq(transforms, point_clouds):
    cost_1 = np.linalg.norm(sum_sdf_seg_sq(transforms[0], point_clouds[0]))
    cost_2 = np.linalg.norm(sum_sdf_seg_sq(transforms[1], point_clouds[1]))
    return cost_1 + cost_2

def opt_T(num_clouds, point_clouds):
    T_i_c = np.zeros((num_clouds[0], 2))
    solver_c = jaxopt.ScipyMinimize(method = 'nelder-mead', fun = total_cost_c, maxiter = 500, callback=callback_fun)
    T_opt_c, state_c = solver_c.run(T_i_c, point_clouds[0:num_clouds[0]])

    T_i_sq = np.zeros((num_clouds[1], 2))
    solver_sq = jaxopt.ScipyMinimize(method = 'nelder-mead', fun = total_cost_sq, maxiter = 500, callback=callback_fun)
    T_opt_sq, state_sq = solver_sq.run(T_i_sq, point_clouds[num_clouds[0]:num_clouds[0]+num_clouds[1]])
    
    return np.concatenate((T_opt_c, T_opt_sq)), state_c.fun_val + state_sq.fun_val

def sdf_segmentation(transform_init, point_cloud, num_clouds):
    sdf_array_c = batch_sdf_c(transform_init, point_cloud)
    filter = np.diff(sdf_array_c)
    split_indices = np.where(np.abs(filter)>2.5)[0].tolist()
    split_indices.append(len(point_cloud))
    split_indices = np.array(split_indices)
    split_clouds = [point_cloud[0:split_indices[0]]]
    for i in range(0, num_clouds-1):
        split_clouds.append(point_cloud[(split_indices[i]):(split_indices[i+1])])
    return split_clouds


point_cloud_c1 = get_circle(np.array([1., 1.]), 1, 50)
point_cloud_c2 = get_circle(np.array([-4., 5.]), 1, 50)
point_cloud_sq1 = get_rect(np.array([13., 5.]), 1, 1, 50)
point_cloud_sq2 = get_rect(np.array([0., -6.]), 1, 1, 50)

point_clouds_test = np.concatenate((point_cloud_c1, point_cloud_c2, point_cloud_sq1, point_cloud_sq2), axis=0)
init_segmentation = sdf_segmentation(np.array([0., 0.]), point_clouds_test, 4)
start_time = time.time()
print(opt_T(np.array([2,2]), init_segmentation))
print(time.time()-start_time)



